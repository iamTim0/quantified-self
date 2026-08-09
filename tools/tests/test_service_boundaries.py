"""Rule 1 for every service, not just the one that already had a test.

`services/analysis/tests/test_service_boundary.py` asserts that the Analysis service
imports no database driver, and it has done its job — Analysis is the service most
tempted to, because it reads the most data. But rule 1 is stated for the whole
repository: *only* `services/core/` may hold a database connection. The Gateway and the
eight importers had no equivalent check, so the invariant was enforced for one service
out of ten and taken on trust for the rest.

Repo-scoped rather than per-service on purpose. A per-service test only exists once
somebody writes it, which is exactly how nine services came to have none; a test that
walks `services/*` covers the importer added next week without being edited. It lives
here beside `test_build_images.py` because that suite already asserts repository-wide
facts (the compose files agree with the image manifest, CI's matrix is derived) and CI
already runs `tools/tests`.

Read from the AST, not by grepping, for the reason the Analysis test gives: a driver
imported under an alias still counts, and a driver *named in a docstring* does not.
`core_client.py` says in its own docstring that there is "no SQLAlchemy, no asyncpg" —
a substring search flags that sentence as the violation it denies.
"""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES = REPO_ROOT / "services"

#: The service that owns the database. Everything else is checked against it.
OWNER = "core"

#: Anything that would mean a service talks to a database directly.
FORBIDDEN_IMPORTS = {
    "sqlalchemy",
    "asyncpg",
    "psycopg",
    "psycopg2",
    "alembic",
    "databases",
}


def _service_dirs() -> list[Path]:
    """Every deployable Python service: `services/<name>` and `services/importers/<name>`."""
    found: list[Path] = []
    for path in sorted(SERVICES.iterdir()):
        if not path.is_dir():
            continue
        if path.name == "importers":
            found.extend(sorted(p for p in path.iterdir() if (p / "pyproject.toml").is_file()))
        elif (path / "pyproject.toml").is_file():
            found.append(path)
    return found


def _guarded() -> list[Path]:
    return [p for p in _service_dirs() if p.name != OWNER]


def _label(path: Path) -> str:
    return path.relative_to(SERVICES).as_posix()


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def _self_composed_hashes(source: str) -> list[int]:
    """Line numbers where this module hashes something built from a `metric_type`.

    One level of local assignment is resolved, because the usual shape does not hash the
    composition directly:

        raw = f"{tenant_id}:{source_id}:{metric_type}:{timestamp}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    The call's argument is the bare name `raw`, so looking only at the argument subtree
    finds nothing — that mistake left six of the nine original copies undetected. Names
    assigned anywhere in the module are substituted once before the check.
    """
    tree = ast.parse(source)

    assigned: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                assigned[target.id] = ast.dump(node.value)

    found: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        called = function.id if isinstance(function, ast.Name) else getattr(function, "attr", "")
        if called != "sha256":
            continue

        hashed = " ".join(ast.dump(argument) for argument in node.args)
        expanded = hashed
        for name, value in assigned.items():
            if f"id='{name}'" in hashed:
                expanded += " " + value

        if "metric_type" in expanded:
            found.append(node.lineno)

    return found


def test_the_self_composed_hash_scan_resolves_an_assignment():
    """The scan's own trap, kept as a test because it already caught us out once.

    Written against the shape the transformers actually used before the derivation moved
    to `shared_schemas`. A scan that only reads the call's arguments passes this file and
    reports the service clean.
    """
    indirect = (
        "import hashlib\n"
        "def key(tenant_id, source_id, metric_type, timestamp):\n"
        '    raw = f"{tenant_id}:{source_id}:{metric_type}:{timestamp}"\n'
        '    return hashlib.sha256(raw.encode("utf-8")).hexdigest()\n'
    )
    direct = (
        "import hashlib\n"
        "def key(t, s, metric_type, ts):\n"
        '    return hashlib.sha256(f"{t}:{s}:{metric_type}:{ts}".encode()).hexdigest()\n'
    )
    innocent = (
        "import hashlib\n"
        "def fingerprint(api_key):\n"
        '    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()\n'
    )

    assert _self_composed_hashes(indirect) == [4]
    assert _self_composed_hashes(direct) == [3]
    assert _self_composed_hashes(innocent) == []


def test_every_service_is_found():
    """A walk that finds nothing would make the parametrized tests vacuous."""
    services = _service_dirs()
    names = {p.name for p in services}
    assert OWNER in names, f"{OWNER} must be among the services found: {sorted(names)}"
    # Core, the Gateway, Analysis and eight importers.
    assert len(services) >= 11, f"expected at least 11 services, found {sorted(names)}"


@pytest.mark.parametrize("service", _guarded(), ids=_label)
def test_no_service_but_core_imports_a_database_driver(service: Path):
    """Verifies Fizzbee Invariant: StrictTenantIsolationOnRead (its precondition).

    Tenant isolation is enforced in Core's queries. A second service with its own
    connection would not be covered by that enforcement at all, which is why the
    boundary is the invariant's precondition rather than a matter of tidiness.
    """
    # Asserted, not assumed: `rglob` on a missing directory yields nothing rather than
    # raising, so a service laid out flat would have passed this and every other
    # parametrized check here by being unreadable.
    assert (service / "src").is_dir(), f"{_label(service)} has no src/ to scan"

    offenders: dict[str, set[str]] = {}
    for path in sorted((service / "src").rglob("*.py")):
        if hits := _imports(path) & FORBIDDEN_IMPORTS:
            offenders[path.relative_to(service).as_posix()] = hits

    assert not offenders, (
        f"{_label(service)} must not import a database driver — only services/{OWNER} "
        f"may hold a connection (AGENTS.md rule 1): {offenders}"
    )


@pytest.mark.parametrize("service", _guarded(), ids=_label)
def test_no_service_but_core_declares_a_database_dependency(service: Path):
    """The import check passes trivially while the driver sits in pyproject.

    A declared dependency is the step before the import, and it is the one a reviewer
    reads past: `asyncpg` in a dependency list looks like infrastructure rather than a
    decision. Catching it here means the boundary is crossed deliberately or not at all.
    """
    declared = (service / "pyproject.toml").read_text(encoding="utf-8").lower()
    offenders = sorted(name for name in FORBIDDEN_IMPORTS if f'"{name}' in declared)

    assert not offenders, (
        f"{_label(service)} declares a database dependency it may not use "
        f"(AGENTS.md rule 1): {offenders}"
    )


@pytest.mark.parametrize("service", _service_dirs(), ids=_label)
def test_no_service_derives_the_idempotency_key_itself(service: Path):
    """Rule 4's hash is defined once, in `shared_schemas.idempotency_key`.

    It used to be written out nine times — once per importer transformer, once inline in
    Core's batch-import endpoint. All nine agreed, and nothing checked that they did. A
    tenth copy with a different separator would not raise anywhere: Core inserts
    `ON CONFLICT DO NOTHING`, so a key that matches nothing stored inserts a second row,
    and the symptom is a metric that slowly doubles months later.

    What it looks for: a call to `sha256` whose argument subtree mentions `metric_type`.
    That is what composing this key looks like, and nothing else in these services hashes
    a metric name. Core's copy was `__import__("hashlib").sha256(...)`, so matching on the
    imported module would have missed it — the call and its argument are the reliable part.

    On the AST rather than on nearby lines. A line window looked cheap and was wrong twice
    over: the common shape assigns `raw = f"{tenant_id}:…:{metric_type}:…"` on the line
    *above* the `sha256(` call, which a forward-only window never sees, and every
    transformer emits an `"idempotency_key":` field within a line or two of the hash, so
    exempting anything that mentions the name exempted the copies as well. Six of the nine
    original copies slipped through both mistakes.
    """
    offenders: list[str] = []

    for path in sorted((service / "src").rglob("*.py")):
        offenders.extend(
            f"{path.relative_to(service).as_posix()}:{line}"
            for line in _self_composed_hashes(path.read_text(encoding="utf-8"))
        )

    assert not offenders, (
        f"{_label(service)} composes the idempotency key itself; call "
        f"shared_schemas.idempotency_key instead (AGENTS.md rule 4): {offenders}"
    )


def test_only_core_holds_migrations():
    """Rule 7: migrations go through `services/core/alembic/` exclusively.

    Looks for the things a migration tree actually has — an Alembic `env.py`, a
    `versions/` directory, an `alembic.ini` — rather than only the ini file. A service
    that grew a `migrations/versions/0001_*.py` with no ini would otherwise not register
    as a migration tree at all.

    Ownership is decided by the first path segment, not by the file's parent directory.
    `path.parent.name != OWNER` happened to work only because the ini sits directly in
    `services/core/`; moving it to `services/core/alembic/alembic.ini` would have made
    this test fail on Core itself.
    """
    signals = ("alembic.ini", "env.py", "versions")
    elsewhere = sorted(
        {
            path.relative_to(REPO_ROOT).as_posix()
            for signal in signals
            for path in SERVICES.rglob(signal)
            if ".venv" not in path.parts
            and path.relative_to(SERVICES).parts[0] != OWNER
            # `env.py` is only telling next to an Alembic layout.
            and (signal != "env.py" or (path.parent / "versions").is_dir())
        }
    )
    assert not elsewhere, f"migrations belong to services/{OWNER} alone: {elsewhere}"
