"""Session identity — what ties a workout's scattered rows back into one workout.

A workout is not stored as a workout. It arrives as a fan of rows in ``data_points``
— ``workout_duration``, ``workout_distance``, a dozen heart-rate figures, a GPS trace,
a set of squats — and until now the only thing joining them was a shared timestamp
plus a metadata string. ``core.daily_story`` says so outright, and names the
consequence: two sessions a provider stamped alike merge into one, and one session
whose points differ by a second splits into two. Neither is recoverable at read time.

This module is the join key those rows were missing. Every importer that emits a
``workout_*`` or ``strength_*`` metric calls :func:`session_metadata` and merges the
result into each point's metadata.

**It lives here, not in each transformer, for the reason ``events.py`` writes down at
length about the idempotency hash**: that one was copied nine times, all nine happened
to agree, and nothing in the repository checked that they did. A session id derived
two ways is a workout that appears twice.

**Adding this changes no idempotency key** (rule 4 hashes tenant, source, metric and
timestamp — not metadata), which is deliberate and has one hard consequence: Core
inserts ``ON CONFLICT DO NOTHING``, so a point already stored can never gain a session
id by being re-imported. A workspace holds tagged and untagged rows side by side
indefinitely, and the read path handles both — see ``core.sessions.session_group_key``.
Tagging history is a wipe and a re-import, not a migration; ``docs/operations.md``
says how.

Verified by ``specs/workout_sessions.fizz``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

__all__ = ["SESSION_KEYS", "session_metadata"]

#: Every metadata key this module writes. Consumers that need to strip or copy a
#: session block name them from here rather than spelling them out again.
SESSION_KEYS: tuple[str, ...] = (
    "session_id",
    "session_start",
    "session_end",
    "session_origin",
    "session_derived_from",
)

#: Hex characters kept from the digest. Sixteen is 64 bits — far past collision
#: range for one workspace's workouts, and short enough to read in a log line.
_DIGEST_CHARS = 16


def _normalise_moment(moment: datetime | str) -> str:
    """One spelling of an instant, so two import paths agree on one session.

    Unlike :func:`shared_schemas.events.idempotency_key`, which hashes a string
    exactly as given because re-keying stored points would double them, this
    *does* parse and re-emit. It can: the field is new, so there is nothing stored
    to stay compatible with, and there is something real to gain — Apple Health's
    archive path and its webhook path spell the same workout's start differently
    (``…Z`` against ``…+00:00``), and a workout imported both ways must be one
    workout rather than two.

    An unparseable value is hashed as it stands. That keeps the function total:
    a session id derived from an odd string is still stable and still groups its
    own points, which is better than an importer raising on a payload it could
    otherwise have stored.
    """
    if isinstance(moment, datetime):
        aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
        return aware.astimezone(timezone.utc).isoformat()
    text = str(moment).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    aware = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat()


def session_metadata(
    *,
    source_type: str,
    source_id: str,
    start: datetime | str,
    provider_session_id: str | None = None,
    end: datetime | str | None = None,
    label: str | None = None,
    derived_from: Sequence[str] = (),
) -> dict[str, Any]:
    """The metadata block identifying the session a data point belongs to.

    ``source_id`` goes *inside* the digest and ``source_type`` stays outside it.
    Inside, because two connectors of the same type are two devices and their
    workouts must not merge — the same reasoning that puts ``source_id`` in the
    idempotency key. Outside, because a prefixed id tells a human reading a row
    where the session came from without a lookup.

    ``provider_session_id`` is used when the provider states one, and the block
    then declares ``session_origin="provider"``. Without one, the id is derived
    from the start instant and ``label`` (the activity or workout name), and the
    block declares ``session_origin="derived"`` plus ``session_derived_from`` —
    rule 19: a derived value that does not say it was derived is a value nobody
    can later audit.

    ``session_end`` is omitted entirely when the provider states no end. An
    invented end is worse than an absent one: the read path widens a window it
    can measure and clamps one it cannot, and it can only tell the two apart if
    a missing end stays missing.

    Raises:
        ValueError: when the id has to be derived and ``derived_from`` is empty.
            The declaration is not optional, so forgetting it is a test failure
            rather than an unauditable number in the database.
    """
    start_iso = _normalise_moment(start)

    stated = (provider_session_id or "").strip()
    if stated:
        local_key = stated
        origin = "provider"
    else:
        if not derived_from:
            raise ValueError(
                "A derived session id must name the fields it stands on "
                "(AGENTS.md rule 19). Pass derived_from=(...)."
            )
        local_key = f"{start_iso}|{label or ''}"
        origin = "derived"

    digest = hashlib.sha256(f"{source_id}|{local_key}".encode()).hexdigest()
    block: dict[str, Any] = {
        "session_id": f"{source_type}:{digest[:_DIGEST_CHARS]}",
        "session_start": start_iso,
        "session_origin": origin,
    }
    if end is not None and str(end).strip():
        block["session_end"] = _normalise_moment(end)
    if origin == "derived":
        block["session_derived_from"] = list(derived_from)
    return block
