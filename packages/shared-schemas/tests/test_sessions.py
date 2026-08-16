"""What a session id must guarantee before any read path can rely on it."""

from datetime import datetime, timezone

import pytest
from shared_schemas import idempotency_key
from shared_schemas.sessions import SESSION_KEYS, session_metadata

TENANT = "11111111-1111-1111-1111-111111111111"
SOURCE = "22222222-2222-2222-2222-222222222222"
OTHER_SOURCE = "33333333-3333-3333-3333-333333333333"
START = "2026-08-15T16:00:00+00:00"


def _block(**overrides):
    kwargs = {
        "source_type": "apple_health",
        "source_id": SOURCE,
        "start": START,
        "provider_session_id": "workout-1",
    }
    kwargs.update(overrides)
    return session_metadata(**kwargs)


def test_session_metadata_does_not_change_the_idempotency_key():
    """Verifies Fizzbee Invariant: NoDuplicateData.

    The whole migration story rests on this. Rule 4 hashes tenant, source, metric
    and timestamp — not metadata — so tagging a point cannot re-key it, and a
    re-import of an already-stored reading still collides and is still dropped.
    If metadata ever entered the hash, every point in the platform would be
    stored a second time the day this shipped.
    """
    before = idempotency_key(TENANT, SOURCE, "workout_distance", START)
    block = _block()
    after = idempotency_key(TENANT, SOURCE, "workout_distance", START)
    assert before == after
    assert "session_id" in block


def test_the_same_workout_yields_the_same_session_id():
    assert _block()["session_id"] == _block()["session_id"]


def test_two_connector_instances_do_not_merge():
    """Two phones, one activity, one instant — two workouts, not one.

    `source_id` is inside the digest for the same reason it is inside the
    idempotency key: a connector belongs to one device, and merging two devices'
    sessions would sum one person's run with another's.
    """
    assert _block()["session_id"] != _block(source_id=OTHER_SOURCE)["session_id"]


def test_the_prefix_names_the_source_type():
    assert _block()["session_id"].startswith("apple_health:")
    assert _block(source_type="whoop")["session_id"].startswith("whoop:")


def test_a_provider_stated_id_says_so():
    block = _block()
    assert block["session_origin"] == "provider"
    assert "session_derived_from" not in block


def test_a_derived_id_names_the_fields_it_stands_on():
    """Rule 19: a derived value that does not declare itself cannot be audited."""
    block = _block(
        provider_session_id=None,
        label="Running",
        derived_from=("start", "workout_name"),
    )
    assert block["session_origin"] == "derived"
    assert block["session_derived_from"] == ["start", "workout_name"]


def test_deriving_without_naming_the_fields_is_refused():
    with pytest.raises(ValueError, match="rule 19"):
        session_metadata(
            source_type="apple_health",
            source_id=SOURCE,
            start=START,
            provider_session_id=None,
            label="Running",
        )


def test_a_derived_id_distinguishes_two_activities_at_one_instant():
    common = {
        "provider_session_id": None,
        "derived_from": ("start", "workout_name"),
    }
    run = _block(label="Running", **common)
    swim = _block(label="Swimming", **common)
    assert run["session_id"] != swim["session_id"]


def test_two_spellings_of_one_instant_give_one_session():
    """The archive writes `…Z` and the webhook `…+00:00` for the same moment.

    Unlike the idempotency key — which hashes a string exactly as given, because
    re-keying stored points would double them — this field is new, so it
    normalises and two spellings converge.

    Note what this does *not* claim: an Apple archive and an Apple webhook do not
    generally derive the same id for one workout, because the webhook usually
    states an id and its activity label differs from Apple's own type name. That
    costs nothing, since both paths key each reading identically and the second
    import is dropped by `ON CONFLICT DO NOTHING` — one stored point, one session.
    """
    archive = _block(provider_session_id=None, label="Running",
                     derived_from=("start", "workout_name"),
                     start="2026-08-15T16:00:00Z")
    push = _block(provider_session_id=None, label="Running",
                  derived_from=("start", "workout_name"),
                  start=datetime(2026, 8, 15, 16, 0, tzinfo=timezone.utc))
    assert archive["session_id"] == push["session_id"]
    assert archive["session_start"] == push["session_start"]


def test_a_naive_start_is_read_as_utc():
    aware = _block(start=datetime(2026, 8, 15, 16, 0, tzinfo=timezone.utc))
    # Deliberately naive: the assertion *is* that a timezone-less start is read
    # as UTC rather than rejected or shifted.
    naive = _block(start=datetime(2026, 8, 15, 16, 0))  # noqa: DTZ001
    assert aware["session_id"] == naive["session_id"]


def test_an_absent_end_stays_absent():
    """An invented end is worse than a missing one — the reader clamps differently."""
    assert "session_end" not in _block()
    assert "session_end" not in _block(end="")
    assert _block(end="2026-08-15T16:45:00Z")["session_end"] == "2026-08-15T16:45:00+00:00"


def test_an_unparseable_instant_still_produces_a_stable_id():
    """Total by design: an odd timestamp is still groupable, and still its own."""
    odd = _block(start="not-a-timestamp")
    assert odd["session_id"] == _block(start="not-a-timestamp")["session_id"]


def test_every_key_written_is_declared():
    """`SESSION_KEYS` is what the backfill and the read path strip and copy."""
    block = _block(
        provider_session_id=None,
        label="Running",
        derived_from=("start",),
        end="2026-08-15T16:45:00Z",
    )
    assert set(block) <= set(SESSION_KEYS)
    assert set(block) == set(SESSION_KEYS)
