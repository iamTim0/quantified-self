"""An importer that emits workouts must say which workout each point belongs to.

`core.daily_story` spent a release reconstructing sessions from a timestamp and a
metadata string, and its own docstring records why that fails in both directions.
The fix was a `session_id` written at ingest — and a fix that lives only in three
transformers is a convention, which is to say something the fourth importer will not
know about. Garmin, Strava and Hevy are all named in `ROADMAP.md`.

So this is the tripwire. Any importer whose contract claims a `workout_*` or
`strength_*` metric must call `session_metadata()`, and the whole platform's read
path keys on what that function produces.

Read from source rather than imported, for the reason
`test_importer_metric_names.py` gives at length: each importer has its own
virtualenv, so a test that imported all eight would only run under an environment
that has none of them.
"""

import ast
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
IMPORTERS = REPO_ROOT / "services" / "importers"

#: A metric in one of these families describes a session, so its points need to name
#: one. Prefixes rather than an explicit list, so a metric added to either family is
#: covered the day it is added.
SESSION_METRIC_PREFIXES = ("workout_", "strength_")

#: The one way to mint a session block. Named here so that a transformer which
#: hand-rolls the digest — the failure `events.py` records about the idempotency
#: hash being copied nine times — fails this test rather than passing it.
SESSION_HELPER = "session_metadata"


def _contracts() -> list[tuple[str, dict]]:
    found = []
    for path in sorted(IMPORTERS.glob("*/importer.contract.json")):
        found.append((path.parent.name, json.loads(path.read_text(encoding="utf-8"))))
    return found


def _session_shaped(contract: dict) -> set[str]:
    return {
        metric
        for metric in contract.get("metrics", ())
        if metric.startswith(SESSION_METRIC_PREFIXES)
    }


def _sources(importer: str) -> str:
    """Every Python source of one importer, concatenated.

    The helper may be called from `transformer.py` or, as in Apple Health, from the
    archive reader beside it. Which file does it is not the property under test.
    """
    root = IMPORTERS / importer / "src"
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(root.rglob("*.py"))
    )


SESSION_IMPORTERS = sorted(
    name for name, contract in _contracts() if _session_shaped(contract)
)


def test_the_session_importers_are_the_ones_we_expect():
    """A floor, so this file cannot pass by finding nothing to check.

    `test_importer_metric_names.py` documents the same failure: a scan that
    silently matches nothing reports green over no coverage at all.
    """
    assert SESSION_IMPORTERS == ["apple_health", "streak", "whoop"], SESSION_IMPORTERS


@pytest.mark.parametrize("importer", SESSION_IMPORTERS)
def test_a_workout_importer_writes_a_session_block(importer):
    source = _sources(importer)
    metrics = ", ".join(sorted(_session_shaped(dict(_contracts())[importer]))[:3])
    assert SESSION_HELPER in source, (
        f"{importer} emits session-shaped metrics ({metrics}, …) but never calls "
        f"{SESSION_HELPER}(). Every point of a workout must name the workout it "
        "belongs to — see packages/shared-schemas/src/shared_schemas/sessions.py."
    )


#: The files that turn a provider payload into data points. Only these are checked
#: below: an importer's auth module hashes a service credential and its spool hashes
#: a chunk, and neither is a session id.
POINT_BUILDERS = ("transformer.py", "export_archive.py")


@pytest.mark.parametrize("importer", SESSION_IMPORTERS)
def test_a_workout_importer_does_not_hand_roll_the_digest(importer):
    """One definition, or the ids two importers derive will not agree.

    A transformer reaches the shared helpers for both hashes it needs — the
    idempotency key and the session id. A direct `hashlib` call in a file that
    builds points is the ninth copy `events.py` describes, the one that happens to
    agree with the other eight until somebody changes a separator.
    """
    root = IMPORTERS / importer / "src"
    for name in POINT_BUILDERS:
        for path in sorted(root.rglob(name)):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute):
                    continue
                if (
                    node.attr in {"sha1", "sha256"}
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "hashlib"
                ):
                    pytest.fail(
                        f"{path.relative_to(REPO_ROOT).as_posix()} hashes directly. "
                        "Use shared_schemas.idempotency_key() or session_metadata()."
                    )


#: The one way to attach a canonical activity to a workout. Streak is allowed to set
#: the key directly: its type is a property of the connector — an app that records
#: sets, reps and weight — rather than something to resolve from a provider's word.
ACTIVITY_HELPERS = ("activity_metadata", '"activity_type"')


@pytest.mark.parametrize("importer", SESSION_IMPORTERS)
def test_a_workout_importer_names_the_activity_canonically(importer):
    """A workout must say *what kind* it was in a way a query can compare.

    The same failure as the session id, one field along. Every importer wrote the
    provider's own word for the activity under a key it chose for itself — WHOOP
    `activity_name`, Apple Health `workout_name` — and what was in there was display
    prose in the user's language: `Radfahren`, `Outdoor Radfahren` and `Innenräume
    Radfahren` for one activity, `Laufen` and `Outdoor Ausführen` for another. Rule
    17 is explicit that a field a client compares against is an identifier, and
    there was none, so "which of these were runs" could not be asked of the data.
    """
    source = _sources(importer)
    assert any(helper in source for helper in ACTIVITY_HELPERS), (
        f"{importer} emits session-shaped metrics but never writes an "
        "`activity_type`. Resolve the provider's wording with "
        "shared_schemas.activities.activity_metadata(), which keeps that wording "
        "beside the canonical key as `activity_label`."
    )
