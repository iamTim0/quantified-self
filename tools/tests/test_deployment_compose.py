"""Every topology has to migrate before Core serves a request.

This is the test for a failure that happened rather than one that might. Applying
migrations was a *step in the instructions* — `run --rm core alembic upgrade head`
after `up -d` — and an instruction is not a mechanism: a deployment that starts the
Compose stack has nowhere to type it, and the development stack's `up` never ran it
either. A migration adding `sync_runs.points_expected` sat committed for weeks while
the database it belonged to did not have the column, and every import run answered
500 from a schema that was simply behind.

So each deployment file gets a one-shot `core-migrate` service and Core waits for it
to exit successfully. What this file checks is that the next topology cannot be added
without one.

Parsed by hand rather than with PyYAML, deliberately: the tools suite runs with
nothing but pytest, and a guard that needs a dependency is a guard that gets skipped.
"""

from pathlib import Path

import pytest

from tools.build_images import IMAGES

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every Compose file that starts Core. The development stack is in here for the same
#: reason as the deployed ones: it drifted the same way.
TOPOLOGIES = [
    "docker-compose.prod.yml",
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


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_timescale_data_volume_matches_pgdata_and_is_initialized(topology):
    """Prevents the HA image from storing data in the disposable container layer."""
    services = service_blocks(REPO_ROOT / topology)
    postgres = " ".join(services["postgres"])
    volume_init = " ".join(services["postgres-volume-init"])

    assert "PGDATA: /var/lib/postgresql/data" in postgres, (
        f"{topology}: the Timescale HA data directory must be explicit"
    )
    assert _depends_on(services["postgres"]).get("postgres-volume-init") == "service_completed_successfully", (
        f"{topology}: postgres must wait for volume ownership initialization"
    )
    assert "chown -R 1000:1000 /var/lib/postgresql/data" in volume_init, (
        f"{topology}: the HA volume must be writable by the postgres UID"
    )


def test_production_routes_public_traffic_through_cloudflare_and_traefik():
    """Keeps Coolify as the deployment controller, not a second ingress path."""
    services = service_blocks(REPO_ROOT / "docker-compose.prod.yml")
    traefik = " ".join(services["traefik"])
    cloudflared = " ".join(services["cloudflared"])

    assert "TUNNEL_TOKEN=${TUNNEL_TOKEN:?set TUNNEL_TOKEN}" in cloudflared
    assert "command: tunnel --no-autoupdate run" in cloudflared
    assert "  - qs-network" in traefik and "  - qs-network" in cloudflared
    assert "${QS_BIND_IP:-127.0.0.1}:${QS_HTTP_PORT:-80}:80" in traefik


def test_production_traefik_has_a_private_container_healthcheck():
    """Keeps Coolify's health signal on the stack's actual public entrypoint."""
    services = service_blocks(REPO_ROOT / "docker-compose.prod.yml")
    traefik = " ".join(services["traefik"])

    assert "--ping=true" in traefik
    assert "healthcheck:" in traefik
    assert 'test: ["CMD", "traefik", "healthcheck", "--ping"]' in traefik
    assert "127.0.0.1:${QS_TRAEFIK_DASHBOARD_PORT:-8081}:8080" in traefik


def test_every_published_runtime_image_declares_a_docker_healthcheck():
    """Keeps the image contract enforceable for existing and future importers."""
    for image in IMAGES:
        if image.name == "core-migrate":
            # A successful exit is the healthy outcome for this one-shot image.
            continue
        dockerfile = REPO_ROOT / image.dockerfile
        assert "HEALTHCHECK" in dockerfile.read_text(encoding="utf-8"), image.name


def test_every_published_production_service_declares_a_healthcheck():
    """Keeps Coolify's service-level health signal aligned with published images."""
    services = service_blocks(REPO_ROOT / "docker-compose.prod.yml")
    published = {
        name
        for name, block in services.items()
        if any(line.startswith("image: ${QS_IMAGE_PREFIX") for line in block)
    }

    for name in published - {"core-migrate"}:
        assert any(line.startswith("healthcheck:") for line in services[name]), name


def test_versioned_health_aggregation_uses_private_compose_targets():
    """Keeps the browser check and Compose liveness check on separate contracts."""
    text = (REPO_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")

    assert "Path(`/health`)" in text
    assert "Path(`/healthz`)" in text
    assert "127.0.0.1:8000/healthz" in text
    for target in (
        "CORE_INGEST_URL=http://core-ingest:8001",
        "CORE_SCHEDULER_URL=http://core-scheduler:8001",
        "DOCS_URL=http://docs:8003",
        "YAZIO_IMPORTER_URL=http://yazio-importer:8008",
        "DAWARICH_IMPORTER_URL=http://dawarich-importer:8009",
        "HOME_ASSISTANT_IMPORTER_URL=http://home-assistant-importer:8011",
        "WEATHER_IMPORTER_URL=http://weather-importer:8012",
        "CALENDAR_IMPORTER_URL=http://calendar-importer:8013",
    ):
        assert target in text

    for port in (8008, 8009, 8011, 8012, 8013):
        assert f"127.0.0.1:{port}/health" in text


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
