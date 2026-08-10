"""Every topology has to migrate before Core serves a request.

This is the test for a failure that happened rather than one that might. Applying
migrations was a *step in the instructions* — `run --rm core alembic upgrade head`
after `up -d` — and an instruction is not a mechanism: the Coolify topology deploys
by starting the Compose stack, so there was nowhere to type it, and the development
stack's `up` never ran it either. A migration adding `sync_runs.points_expected` sat
committed for weeks while the database it belonged to did not have the column, and
every import run answered 500 from a schema that was simply behind.

So each deployment file gets a one-shot `core-migrate` service and Core waits for it
to exit successfully. What this file checks is that the next topology cannot be added
without one.

Parsed by hand rather than with PyYAML, deliberately: the tools suite runs with
nothing but pytest, and a guard that needs a dependency is a guard that gets skipped.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every Compose file that starts Core. The development stack is in here for the same
#: reason as the deployed ones: it drifted the same way.
TOPOLOGIES = [
    "docker-compose.prod.yml",
    "docker-compose.coolify.yml",
    "infra/docker-compose.yml",
]

MIGRATOR = "core-migrate"


#: Indentation of a service's own keys: two for the service, two for its body.
_BODY_INDENT = 4


def service_blocks(path: Path) -> dict[str, list[str]]:
    """The lines of each service under `services:`, dedented, comments removed.

    Dedented by the service body's own indentation rather than fully, because the
    nesting is what `depends_on` is read from. Comments are dropped because they are
    prose about a service and this test reads configuration: the paragraph above
    `core-migrate` mentions the very command the assertions look for, and matching
    that would prove nothing.
    """
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    in_services = False

    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip().startswith("#") or not raw.strip():
            continue
        if not raw.startswith(" "):
            in_services = raw.rstrip().startswith("services:")
            current = None
            continue
        if not in_services:
            continue
        stripped = raw.lstrip(" ")
        indent = len(raw) - len(stripped)
        if indent == 2 and stripped.rstrip().endswith(":"):
            current = stripped.rstrip().removesuffix(":")
            blocks[current] = []
        elif current is not None and indent >= _BODY_INDENT:
            blocks[current].append(raw.rstrip()[_BODY_INDENT:])

    return blocks


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_the_topology_has_a_one_shot_migration_service(topology):
    services = service_blocks(REPO_ROOT / topology)

    assert MIGRATOR in services, f"{topology} starts Core without a migration step"
    block = " ".join(services[MIGRATOR])
    assert "alembic" in block and "upgrade" in block and "head" in block, (
        f"{topology}: {MIGRATOR} does not run `alembic upgrade head`"
    )
    # Meant to exit. `restart: always` would run it again forever, and Core's
    # `service_completed_successfully` condition would never be satisfied.
    assert 'restart: "no"' in block, f"{topology}: {MIGRATOR} must not be restarted"


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_core_waits_for_the_migration_to_succeed(topology):
    services = service_blocks(REPO_ROOT / topology)
    core = services["core"]

    depends = _depends_on(core)
    assert MIGRATOR in depends, f"{topology}: core does not depend on {MIGRATOR}"
    assert depends[MIGRATOR] == "service_completed_successfully", (
        f"{topology}: core must wait for {MIGRATOR} to *succeed*, not merely to start"
    )


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_the_migration_waits_for_a_database_that_accepts_connections(topology):
    """Otherwise it races the initialisation of an empty volume and loses."""
    services = service_blocks(REPO_ROOT / topology)

    assert _depends_on(services[MIGRATOR]).get("postgres") == "service_healthy", (
        f"{topology}: {MIGRATOR} must wait for postgres to be healthy"
    )
    assert any(line.startswith("healthcheck:") for line in services["postgres"]), (
        f"{topology}: postgres needs a healthcheck for that condition to mean anything"
    )


def _depends_on(block: list[str]) -> dict[str, str]:
    """`{service: condition}` from a service's `depends_on:` mapping.

    Only the long form is read, because only the long form can express a condition —
    and a condition is the whole point here.
    """
    conditions: dict[str, str] = {}
    inside = False
    name: str | None = None

    for line in block:
        if line.startswith("depends_on:"):
            inside = True
            continue
        if inside and not line.startswith(" "):
            break
        if not inside:
            continue
        entry = line.strip()
        if entry.endswith(":"):
            name = entry.removesuffix(":")
        elif entry.startswith("condition:") and name:
            conditions[name] = entry.split(":", 1)[1].strip()

    return conditions
