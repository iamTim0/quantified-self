"""The one derivation of the key that decides what counts as a duplicate.

Rule 4 states the shape; this pins it. Worth pinning by digest rather than by
recomputing the same expression, because a test that rebuilds the formula passes for
any formula — including a changed one, which is the failure that matters: Core inserts
`ON CONFLICT DO NOTHING`, so a key that no longer matches the stored one does not
error, it inserts a second row. The only symptom is a metric that slowly doubles.

The derivation used to be written out nine times — once per importer transformer and
once inline in Core's batch-import endpoint as `__import__("hashlib").sha256(...)`. All
nine agreed, and nothing checked that they did.
"""

from datetime import datetime, timedelta, timezone

import pytest
from shared_schemas import idempotency_key

TENANT = "11111111-1111-1111-1111-111111111111"
SOURCE = "src-1"
STAMP = "2026-05-01T00:00:00+00:00"

#: SHA256(f"{TENANT}:{SOURCE}:steps:{STAMP}"), written down rather than recomputed.
KNOWN = "c02e6bd60ea49605f03ef4fc94ba57cf559aac4c58a34851dbb3b9e09e0b45c9"


def test_the_shape_is_the_one_rule_4_states():
    """`SHA256(tenant_id:source_id:metric_type:timestamp)`, colon-separated, hex.

    Against a constant, not against the formula rebuilt here. Rebuilding it would make
    this test agree with whatever the function does, including a changed separator --
    and a changed separator is invisible at run time, because a key that matches nothing
    stored inserts a row instead of raising.
    """
    assert idempotency_key(TENANT, SOURCE, "steps", STAMP) == KNOWN
    assert len(KNOWN) == 64


def test_it_is_deterministic():
    args = (TENANT, SOURCE, "steps", STAMP)
    assert idempotency_key(*args) == idempotency_key(*args)


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("tenant", ("33333333-3333-3333-3333-333333333333", SOURCE, "steps")),
        ("source", (TENANT, "44444444-4444-4444-4444-444444444444", "steps")),
        ("metric", (TENANT, SOURCE, "distance")),
    ],
)
def test_every_part_of_the_key_changes_it(field: str, changed: tuple[str, str, str]):
    """A part that does not reach the digest would collapse distinct readings into one."""
    assert idempotency_key(*changed, STAMP) != idempotency_key(TENANT, SOURCE, "steps", STAMP)


def test_a_datetime_and_its_iso_string_agree():
    """Core holds a `datetime`, the importers hold a formatted string.

    They have to produce the same key: the manual-import path and an importer can write
    the same reading, and rule 4's uniqueness is `(tenant_id, idempotency_key,
    timestamp)`.
    """
    moment = datetime(2026, 5, 1, tzinfo=timezone.utc)

    assert idempotency_key(TENANT, SOURCE, "steps", moment) == KNOWN


def test_the_same_instant_in_another_offset_is_the_same_key():
    """`+02:00` and `Z` are one reading, and used to be two keys.

    This is the mistake that produced fresh duplicates on every sync before the
    transformers normalized: the timestamp is part of the hash, so an unconverted
    offset made the same measurement look new.
    """
    utc = datetime(2026, 5, 1, tzinfo=timezone.utc)
    berlin = datetime(2026, 5, 1, 2, tzinfo=timezone(timedelta(hours=2)))

    assert idempotency_key(TENANT, SOURCE, "steps", berlin) == idempotency_key(
        TENANT, SOURCE, "steps", utc
    )


def test_two_spellings_of_the_same_string_are_two_keys():
    """Pinned as a decision, not left as an accident.

    `…T00:00:00Z` and `…T00:00:00+00:00` are the same instant, and a string is hashed
    verbatim, so they key differently. Both spellings are in use — Dawarich and Yazio emit
    `Z`, the other six importers and Core emit `+00:00`.

    Converging them here would re-key every point those two sources have already stored,
    and a key that matches nothing inserts rather than raising, so the fix for a
    duplicate would be the cause of thousands. Each source is self-consistent, which is
    what dedup needs; crossing paths for one reading is the documented cost.
    """
    zulu = idempotency_key(TENANT, SOURCE, "steps", "2026-05-01T00:00:00Z")

    assert zulu != KNOWN
    # ...but each spelling remains stable, which is the property that matters.
    assert zulu == idempotency_key(TENANT, SOURCE, "steps", "2026-05-01T00:00:00Z")


def test_a_naive_datetime_is_read_as_utc():
    """Not rejected, because the alternative is worse.

    A naive timestamp reaching here is a bug upstream, but raising would turn it into a
    dropped import; reading it as UTC keys it the way the rest of the platform stores
    time. The importers normalize before they get here — this is the floor, not the
    contract.
    """
    assert idempotency_key(TENANT, SOURCE, "steps", datetime(2026, 5, 1)) == idempotency_key(
        TENANT, SOURCE, "steps", datetime(2026, 5, 1, tzinfo=timezone.utc)
    )


def test_the_canonical_name_is_the_callers_job():
    """An alias must not be silently accepted here.

    The name is part of the hash, so canonicalising inside this function would key a
    point under a name it is not stored under. `IngestEvent` rejects an alias for the
    same reason; here it simply produces a different key, which is what the callers'
    `canonical_metric_type()` call exists to prevent.
    """
    assert idempotency_key(TENANT, SOURCE, "resting_hr", STAMP) != idempotency_key(
        TENANT, SOURCE, "heart_rate_resting", STAMP
    )
