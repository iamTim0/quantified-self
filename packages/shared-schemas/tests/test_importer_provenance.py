"""Every data point an importer builds carries the number that arrived (rule 19).

A rule nothing checks is a rule that holds until the next importer. Seven of the nine
transformers stored no `provider_value` at all when this was written, so a converted
number was the only record of a reading and a conversion bug was unrecoverable rather
than merely wrong.

Source is scanned rather than imported, for the reason `test_importer_metric_names`
already gives: each importer has its own virtualenv, so a test that imported all of them
would run under none of them.

What it proves, and what it does not: for every dict literal that looks like a data point
— it names both a `metric_type` and an `idempotency_key` — the `metadata` it carries must
reach `provider_value`, whether written outright, unpacked from `provenance()`, or held in
a variable one of those built. Where a transformer routes construction through a builder
that takes `metadata` as a parameter, the parameter cannot be resolved here, so the
builder's *call sites* are checked instead. A metadata dict assembled by a helper this
scan cannot follow would pass unnoticed; the check is a floor, not a proof.
"""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
IMPORTERS = REPO_ROOT / "services" / "importers"

#: The two keys rule 19 requires. `units` is asserted through `provenance()`, which is
#: the only way it is written now; `provider_value` is the one a literal may spell out.
PROVENANCE_MARKERS = ("provider_value", "provenance")


def _sources() -> list[Path]:
    files = [
        path
        for path in IMPORTERS.rglob("*.py")
        if ".venv" not in path.parts and "__pycache__" not in path.parts
    ]
    assert files, "no importer sources found — has the layout moved?"
    return sorted(files)


def _literal(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_data_point(node: ast.Dict) -> bool:
    keys = {_literal(key) for key in node.keys}
    return "metric_type" in keys and "idempotency_key" in keys


def _value_for(node: ast.Dict, wanted: str) -> ast.AST | None:
    for key, value in zip(node.keys, node.values):
        if _literal(key) == wanted:
            return value
    return None


def _mentions_provenance(node: ast.AST) -> bool:
    """True if this subtree writes `provider_value` or calls `provenance()`."""
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):  # noqa: SIM102
            if inner.func.id == "provenance":
                return True
        if isinstance(inner, ast.Constant) and inner.value == "provider_value":
            return True
    return False


def _provenanced_names(tree: ast.AST) -> set[str]:
    """Variables somewhere assigned something that carries the provenance pair."""
    names: set[str] = set()
    for node in ast.walk(tree):
        targets: list[ast.AST] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if node.value is None or not _mentions_provenance(node.value):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                names.add(target.value.id)
    # `metadata["provider_value"] = x` names the variable in the *target*, not the value.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and _literal(target.slice) == "provider_value"
            ):
                names.add(target.value.id)
    return names


def _carries(node: ast.AST | None, provenanced: set[str]) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Name):
        return node.id in provenanced
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            if _literal(key) == "provider_value":
                return True
            # `**provenance(...)` and `**already_provenanced`
            if key is None and _carries(value, provenanced):
                return True
            if key is None and _mentions_provenance(value):
                return True
        return False
    return _mentions_provenance(node)


def _enclosing_parameters(tree: ast.AST, target: ast.Dict) -> tuple[str, set[str]] | None:
    """The function a dict sits in, as `(name, parameter names)`."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if inner is target:
                args = node.args
                params = {
                    arg.arg
                    for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)
                }
                return node.name, params
    return None


def _call_sites_carry(tree: ast.AST, builder: str, provenanced: set[str]) -> bool:
    """Every call to `builder` hands it a metadata argument with the pair."""
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == builder
    ]
    if not calls:
        return False
    for call in calls:
        keyword = next((kw.value for kw in call.keywords if kw.arg == "metadata"), None)
        if keyword is not None:
            if not _carries(keyword, provenanced):
                return False
            continue
        # Positional: any argument that carries the pair will do, since the parameter
        # order is the builder's business and not this test's.
        if not any(_carries(arg, provenanced) for arg in call.args):
            return False
    return True


def test_the_check_can_go_red() -> None:
    """A guard is worth its green tick only if a violation actually trips it.

    Both halves matter: 28 data-point dicts are found across the importers today, so a
    detector that quietly matched nothing would pass just as happily.
    """
    point = (
        "p = {{'metric_type': 'steps', 'value': 1.0,"
        " 'metadata': {metadata}, 'idempotency_key': 'k'}}"
    )

    bare = ast.parse(point.format(metadata="{'source_type': 'x'}"))
    found = [node for node in ast.walk(bare) if isinstance(node, ast.Dict) and _is_data_point(node)]
    assert len(found) == 1, "the detector no longer recognises a data point"
    assert not _carries(_value_for(found[0], "metadata"), _provenanced_names(bare))

    for accepted in (
        "{'source_type': 'x', **provenance('steps', 1.0)}",
        "{'source_type': 'x', 'provider_value': 1.0}",
    ):
        tree = ast.parse(point.format(metadata=accepted))
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.Dict) and _is_data_point(n))
        assert _carries(_value_for(node, "metadata"), _provenanced_names(tree)), accepted


@pytest.mark.parametrize("source", _sources(), ids=lambda p: p.relative_to(IMPORTERS).as_posix())
def test_every_data_point_carries_the_number_that_arrived(source: Path) -> None:
    """Verifies AGENTS.md rule 19: raw provenance travels with every point."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    provenanced = _provenanced_names(tree)

    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict) or not _is_data_point(node):
            continue
        metadata = _value_for(node, "metadata")
        if _carries(metadata, provenanced):
            continue
        # A builder taking `metadata` as a parameter is checked at its call sites.
        enclosing = _enclosing_parameters(tree, node)
        if (
            enclosing is not None
            and isinstance(metadata, ast.Name)
            and metadata.id in enclosing[1]
            and _call_sites_carry(tree, enclosing[0], provenanced)
        ):
            continue
        offenders.append(node.lineno)

    assert not offenders, (
        f"{source.relative_to(REPO_ROOT).as_posix()} builds data points whose metadata "
        f"carries neither `provider_value` nor `provenance()` at line(s) "
        f"{', '.join(str(line) for line in offenders)}. AGENTS.md rule 19: the number "
        f"the provider stated travels with the point, so a converted value is never the "
        f"only record of a reading."
    )
