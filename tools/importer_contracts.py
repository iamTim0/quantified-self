"""Validate the machine-readable contract for every importer.

The contract files are the source of truth for the importer boundary: an external
schema describes what a provider sends, while this contract describes what this
repository supports and publishes. The latter is deliberately format-neutral because
Apple Health and WHOOP exports are not OpenAPI documents.

    python tools/importer_contracts.py
    python tools/importer_contracts.py --json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
IMPORTERS_ROOT = REPO_ROOT / "services" / "importers"
CONTRACT_FILENAME = "importer.contract.json"
REQUIRED_MODULES = frozenset({"config.py", "client.py", "transformer.py", "main.py"})
SCHEMA_KINDS = frozenset({"json", "xml", "zip_csv", "zip_xml_gpx", "ics", "rest_json"})
SOURCE_KINDS = frozenset(
    {"external_documentation", "rfc", "repository_adapter", "generated_schema"}
)
UPSTREAM_SCHEMA_KINDS = frozenset({"openapi", "json_schema", "provider_documentation", "rfc"})
SOURCE_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def _shared_metrics() -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    """Read metric keys and source ownership without importing optional dependencies."""
    registry_path = (
        REPO_ROOT
        / "packages"
        / "shared-schemas"
        / "src"
        / "shared_schemas"
        / "metrics.py"
    )
    tree = ast.parse(registry_path.read_text(encoding="utf-8"), filename=str(registry_path))
    metrics: dict[str, frozenset[str]] = {}
    namespaces: dict[str, frozenset[str]] = {}

    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, (ast.List, ast.Tuple)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        target_names = {
            target.id for target in targets if isinstance(target, ast.Name)
        }
        if "_DEFINITIONS" in target_names:
            for item in value.elts:
                if not isinstance(item, ast.Call):
                    continue
                values = {
                    keyword.arg: ast.literal_eval(keyword.value)
                    for keyword in item.keywords
                    if keyword.arg in {"key", "sources"}
                }
                key = values.get("key")
                sources = values.get("sources", ())
                if isinstance(key, str) and isinstance(sources, tuple):
                    metrics[key] = frozenset(source for source in sources if isinstance(source, str))
        elif "DYNAMIC_NAMESPACES" in target_names:
            for item in value.elts:
                if not isinstance(item, ast.Call):
                    continue
                values = {
                    keyword.arg: ast.literal_eval(keyword.value)
                    for keyword in item.keywords
                    if keyword.arg in {"prefix", "sources"}
                }
                prefix = values.get("prefix")
                sources = values.get("sources", ())
                if isinstance(prefix, str) and isinstance(sources, tuple):
                    namespaces[prefix] = frozenset(
                        source for source in sources if isinstance(source, str)
                    )
    return metrics, namespaces


def importer_directories() -> tuple[Path, ...]:
    """Return importer services discovered by their Python project manifest."""
    if not IMPORTERS_ROOT.is_dir():
        return ()
    return tuple(
        sorted(
            path
            for path in IMPORTERS_ROOT.iterdir()
            if path.is_dir() and (path / "pyproject.toml").is_file()
        )
    )


def contract_paths() -> tuple[Path, ...]:
    """Return the contract path belonging to every discovered importer."""
    return tuple(path / CONTRACT_FILENAME for path in importer_directories())


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing {path.relative_to(REPO_ROOT)}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path.relative_to(REPO_ROOT)}: {exc}") from exc
    if not isinstance(value, dict):
        raise TypeError(f"{path.relative_to(REPO_ROOT)} must contain a JSON object")
    return value


def _required_string(
    value: Any, *, path: Path, field: str, errors: list[str]
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path.relative_to(REPO_ROOT)}: {field} must be a non-empty string")
        return None
    return value


def _validate_input_contracts(
    value: Any, *, path: Path, errors: list[str]
) -> None:
    if not isinstance(value, list) or not value:
        errors.append(
            f"{path.relative_to(REPO_ROOT)}: input_contracts must be a non-empty list"
        )
        return

    for index, item in enumerate(value):
        prefix = f"input_contracts[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path.relative_to(REPO_ROOT)}: {prefix} must be an object")
            continue
        _required_string(item.get("name"), path=path, field=f"{prefix}.name", errors=errors)
        fmt = _required_string(
            item.get("format"), path=path, field=f"{prefix}.format", errors=errors
        )
        if fmt is not None and fmt not in SCHEMA_KINDS:
            errors.append(
                f"{path.relative_to(REPO_ROOT)}: {prefix}.format {fmt!r} is not supported"
            )
        source = item.get("source_of_truth")
        if not isinstance(source, dict):
            errors.append(
                f"{path.relative_to(REPO_ROOT)}: {prefix}.source_of_truth must be an object"
            )
            continue
        kind = _required_string(
            source.get("kind"), path=path, field=f"{prefix}.source_of_truth.kind", errors=errors
        )
        reference = _required_string(
            source.get("reference"),
            path=path,
            field=f"{prefix}.source_of_truth.reference",
            errors=errors,
        )
        if kind is not None and kind not in SOURCE_KINDS:
            errors.append(
                f"{path.relative_to(REPO_ROOT)}: {prefix}.source_of_truth.kind {kind!r} is not supported"
            )
        schema = source.get("schema")
        if schema is not None and schema not in UPSTREAM_SCHEMA_KINDS:
            errors.append(
                f"{path.relative_to(REPO_ROOT)}: {prefix}.source_of_truth.schema {schema!r} is not supported"
            )
        if reference is not None and kind in {"repository_adapter", "generated_schema"}:
            reference_path = REPO_ROOT / reference
            if not reference_path.is_file():
                errors.append(
                    f"{path.relative_to(REPO_ROOT)}: {prefix}.source_of_truth.reference "
                    f"does not exist: {reference}"
                )
        generated = item.get("generated", False)
        if not isinstance(generated, bool):
            errors.append(
                f"{path.relative_to(REPO_ROOT)}: {prefix}.generated must be boolean"
            )
        if generated and not isinstance(item.get("generated_from"), str):
            errors.append(
                f"{path.relative_to(REPO_ROOT)}: {prefix}.generated_from is required for generated inputs"
            )


def _validate_code_boundary(
    contract: dict[str, Any], *, importer_dir: Path, errors: list[str]
) -> None:
    relative = importer_dir.relative_to(REPO_ROOT)
    source_files = tuple((importer_dir / "src").rglob("*.py"))
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in source_files)
    source_type = contract.get("source_type")
    ingest_subject = contract.get("ingest_subject")
    task_subject = contract.get("task_subject")

    if isinstance(ingest_subject, str) and ingest_subject not in source_text:
        errors.append(f"{relative}: ingest_subject {ingest_subject!r} is not used by the importer")
    if isinstance(task_subject, str) and task_subject not in source_text:
        errors.append(f"{relative}: task_subject {task_subject!r} is not used by the importer")
    for invariant in ("tenant_id", "idempotency_key", "canonical_metric_type"):
        if invariant not in source_text:
            errors.append(f"{relative}: importer code does not show required invariant {invariant!r}")
    if source_type == "home_assistant" and "home_assistant_" not in source_text:
        errors.append(f"{relative}: dynamic Home Assistant namespace is not used by the importer")


def validate_contract(path: Path) -> list[str]:
    """Validate one contract and return human-readable errors."""
    errors: list[str] = []
    relative = path.relative_to(REPO_ROOT)
    try:
        contract = _read_json(path)
    except ValueError as exc:
        return [str(exc)]

    if contract.get("$schema") != "../../tools/importer-contract.schema.json":
        errors.append(f"{relative}: $schema must point to the repository contract schema")
    if contract.get("contract_version") != 1:
        errors.append(f"{relative}: contract_version must be 1")

    source_type = _required_string(
        contract.get("source_type"), path=path, field="source_type", errors=errors
    )
    if source_type is not None and not SOURCE_TYPE_PATTERN.fullmatch(source_type):
        errors.append(f"{relative}: source_type must be lowercase snake_case")
    expected_dir = path.parent.name
    if source_type is not None and source_type != expected_dir:
        errors.append(f"{relative}: source_type must match importer directory {expected_dir!r}")

    ingest_subject = _required_string(
        contract.get("ingest_subject"), path=path, field="ingest_subject", errors=errors
    )
    if source_type is not None and ingest_subject != f"qs.ingest.{source_type}":
        errors.append(f"{relative}: ingest_subject must be qs.ingest.<source_type>")

    task_subject = contract.get("task_subject")
    if task_subject is not None:
        task_subject = _required_string(
            task_subject, path=path, field="task_subject", errors=errors
        )
        if source_type is not None and task_subject != f"qs.task.sync.{source_type}":
            errors.append(f"{relative}: task_subject must be qs.task.sync.<source_type>")

    _required_string(contract.get("entrypoint"), path=path, field="entrypoint", errors=errors)

    required_modules = contract.get("required_modules")
    if not isinstance(required_modules, list) or set(required_modules) != REQUIRED_MODULES:
        errors.append(
            f"{relative}: required_modules must be exactly {sorted(REQUIRED_MODULES)}"
        )
    else:
        package_root = path.parent / "src"
        for module in required_modules:
            if not any(package_root.rglob(module)):
                errors.append(f"{relative}: required module {module!r} is missing under src/")

    communication = contract.get("communication")
    if not isinstance(communication, dict):
        errors.append(f"{relative}: communication must be an object")
    else:
        expected_communication = {
            "ingest": "nats_jetstream",
            "credentials": "core_internal_http",
            "database_access": False,
            "request_correlation": "X-Request-ID",
        }
        for field, expected in expected_communication.items():
            if communication.get(field) != expected:
                errors.append(f"{relative}: communication.{field} must be {expected!r}")

    event_fields = contract.get("ingest_event_fields")
    if event_fields != ["tenant_id", "source_id", "source_type", "metric_type", "timestamp", "value", "idempotency_key"]:
        errors.append(
            f"{relative}: ingest_event_fields must list the stable tenant-scoped event fields"
        )

    _validate_input_contracts(contract.get("input_contracts"), path=path, errors=errors)

    catalog, namespaces = _shared_metrics()
    metrics = contract.get("metrics")
    if not isinstance(metrics, list) or metrics != sorted(set(metrics)):
        errors.append(f"{relative}: metrics must be a sorted list of unique canonical names")
        metrics = metrics if isinstance(metrics, list) else []
    namespace_by_prefix = namespaces
    for metric in metrics:
        if not isinstance(metric, str):
            errors.append(f"{relative}: every metrics entry must be a string")
            continue
        definition = catalog.get(metric)
        if definition is None:
            errors.append(f"{relative}: metric {metric!r} is not in the shared registry")
            continue
        if source_type not in definition:
            errors.append(
                f"{relative}: metric {metric!r} is not registered for source_type {source_type!r}"
            )

    dynamic_namespaces = contract.get("dynamic_namespaces")
    if not isinstance(dynamic_namespaces, list) or dynamic_namespaces != sorted(set(dynamic_namespaces)):
        errors.append(f"{relative}: dynamic_namespaces must be a sorted list of unique prefixes")
        dynamic_namespaces = dynamic_namespaces if isinstance(dynamic_namespaces, list) else []
    for prefix in dynamic_namespaces:
        namespace = namespace_by_prefix.get(prefix)
        if namespace is None:
            errors.append(f"{relative}: dynamic namespace {prefix!r} is not registered")
        elif source_type not in namespace:
            errors.append(
                f"{relative}: dynamic namespace {prefix!r} is not registered for {source_type!r}"
            )

    capabilities = contract.get("capabilities")
    if not isinstance(capabilities, dict):
        errors.append(f"{relative}: capabilities must be an object")
    else:
        for field in ("scheduled_sync", "webhook", "file_upload"):
            if not isinstance(capabilities.get(field), bool):
                errors.append(f"{relative}: capabilities.{field} must be boolean")
        if capabilities.get("scheduled_sync") is True and task_subject is None:
            errors.append(f"{relative}: scheduled_sync requires task_subject")

    _validate_code_boundary(contract, importer_dir=path.parent, errors=errors)
    return errors


def validate_all() -> list[str]:
    """Validate discovery, one contract per importer, and every contract."""
    errors: list[str] = []
    for path in contract_paths():
        errors.extend(validate_contract(path))
    return errors


def load_contracts() -> list[dict[str, Any]]:
    """Load validated contracts in deterministic importer-name order."""
    errors = validate_all()
    if errors:
        raise ValueError("\n".join(errors))
    return [_read_json(path) for path in contract_paths()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print errors as a JSON array")
    args = parser.parse_args()
    errors = validate_all()
    if errors:
        if args.json:
            print(json.dumps(errors, indent=2))
        else:
            print("Importer contract validation failed:")
            for error in errors:
                print(f"- {error}")
        return 1
    print(f"Validated {len(contract_paths())} importer contracts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
