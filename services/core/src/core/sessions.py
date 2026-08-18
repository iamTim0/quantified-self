"""Turning scattered rows back into the workout they came from.

A workout is stored as a fan of `data_points` — `workout_duration`, `workout_distance`,
a dozen heart-rate figures, a GPS trace, a set of squats. Nothing in the table records
that they are one thing. `core.daily_story` has always reassembled them at read time
from a shared timestamp and a metadata title, and its own docstring names why that is
thin: two sessions a provider stamped alike merge, one session stamped a second apart
splits.

The importers now write a `session_id` (`shared_schemas.sessions`), so there is a real
key. This module holds the *reading* half of that: how a row is assigned to a session,
and how a session is named in a URL.

**Both shapes are permanent, not transitional.** Rule 4 keys a point on
`(tenant, source, metric, timestamp)` and Core inserts `ON CONFLICT DO NOTHING`, so a
row stored before the change can never gain a session id by being re-imported. There is
no backfill command: a workspace that wants its history tagged wipes and re-imports (see
`docs/operations.md`), and one case could not be recovered even by one — Apple Health's
webhook route fixes carry only a workout name, with nothing tying a fix to a session
start. So a workspace holds tagged and untagged rows side by side and the grouping has to
handle both without ever mixing them.

The consequence worth stating plainly: a workout whose points straddle the change shows
up as **two** sessions rather than one. That is the honest outcome, and it is bounded —
what must never happen is one row appearing in both, because its measures would then be
counted twice and a doubled number is indistinguishable from a right one (rule 19).
`specs/workout_sessions.fizz` model-checks exactly that.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

__all__ = [
    "STREAM_METRICS",
    "SessionRef",
    "decode_session_key",
    "encode_session_key",
    "session_group_key",
    "session_title",
]

#: Metrics that are a *series inside* a session rather than a figure about one.
#:
#: They start with `workout_`, so `daily_story.SESSION_PREFIXES` would otherwise make
#: them event-shaped, and a 90-minute workout at second resolution is 5,400 rows
#: against a 4,000-row scan budget — the day timeline would silently truncate for
#: anyone who trains. A stream metric is neither a lane nor a timeline event; it is
#: read through `/api/v1/data/metrics` and through the workout detail endpoint.
STREAM_METRICS: frozenset[str] = frozenset({"workout_heart_rate"})

#: Metadata fields that can name a session, in the order `daily_story` has always
#: tried them. Kept here so the list has one home.
TITLE_FIELDS: tuple[str, ...] = (
    "workout_name",
    "activity_name",
    # Streak's own field. Its absence here is why a strength session arrived on
    # the workout list with a blank name while carrying "Full Body" in metadata.
    "workout_title",
    "summary",
    "food_name",
    "meal_category",
)

#: Metadata fields that can state when a session ended, in preference order.
END_FIELDS: tuple[str, ...] = ("session_end", "end", "end_time", "workout_end_time", "sleep_end")

_KEY_VERSION = "v1"
_SEP = "|"


def session_title(metadata: dict[str, Any] | None) -> str:
    """The human name of the session a point belongs to, or an empty string."""
    data = metadata or {}
    for field in TITLE_FIELDS:
        value = data.get(field)
        if isinstance(value, str) and value:
            return value
    return ""


def session_group_key(
    timestamp: datetime, metadata: dict[str, Any] | None, category: str
) -> tuple[str, str]:
    """Which session a row belongs to, as ``(kind, key)``.

    ``kind`` is ``"session_id"`` when the row carries one and ``"timestamp_title"``
    otherwise. The two key spaces cannot collide — that is what the discriminator
    is for, and it is the property `SessionGroupingIsStable` checks.

    The fallback is **byte-identical to what `daily_story._events` has always
    built**, deliberately: the day timeline and the workout list must not disagree
    about what a session is for the same untagged rows. `_events` calls this
    function now, so there is one rule rather than two copies drifting.
    """
    data = metadata or {}
    stated = data.get("session_id")
    if isinstance(stated, str) and stated:
        return ("session_id", stated)
    return ("timestamp_title", f"{timestamp.isoformat()}{_SEP}{session_title(data)}{_SEP}{category}")


@dataclass(frozen=True)
class SessionRef:
    """A session named in a URL, decoded back into something queryable."""

    kind: Literal["session_id", "timestamp_title"]
    #: The session's first known instant. Carried in the key itself, and not for
    #: decoration: without it, resolving `metadata->>'session_id'` has nothing to
    #: bound the hypertable's time dimension and the query scans a whole history
    #: to find a 45-minute run. With it, every detail query starts inside a day.
    start: datetime
    session_id: str | None = None
    source_id: str | None = None
    title: str | None = None
    #: The registry category, for a legacy group only.
    #:
    #: The grouping key is `(timestamp, title, category)`, so all three have to come
    #: back out of the URL or the detail resolves a *wider* set than the list
    #: grouped. Without the title, two workouts one connector stamped at the same
    #: second appeared as two rows in the list and each showed both of their
    #: measures when opened.
    category: str | None = None


def _encode_ms(moment: datetime) -> int:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return int(aware.astimezone(timezone.utc).timestamp() * 1000)


def encode_session_key(ref: SessionRef) -> str:
    """An opaque, URL-safe handle for one session.

    Unsigned on purpose. Every query behind it filters on the tenant the Gateway
    injected (rule 2), so the worst a forged key can do is address the caller's own
    workspace — an HMAC would add a secret to rotate and buy nothing.
    `SessionDetailIsTenantScoped` is the model-checked version of that claim.
    """
    stamp = str(_encode_ms(ref.start))
    if ref.kind == "session_id":
        parts = [_KEY_VERSION, "s", stamp, ref.session_id or ""]
    else:
        # `source_id` and `category` are here where `daily_story`'s grouping key
        # omits the first: two connectors stamping the same second with the same
        # title may merge on a day summary, but on a detail page the reader would
        # act on the merge. `title` is last because it is the one field that may
        # itself contain the separator.
        parts = [
            _KEY_VERSION,
            "t",
            stamp,
            ref.source_id or "",
            ref.category or "",
            ref.title or "",
        ]
    raw = _SEP.join(parts).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_session_key(raw: str) -> SessionRef:
    """Parse a session key, or raise ``ValueError``.

    The caller turns that into a `400` with a stable ``code``; a malformed key is a
    client mistake, not a missing session, and the two deserve different answers.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty session key")
    padded = text + "=" * (-len(text) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("session key is not valid base64url") from exc

    # `split` with a maxsplit, because a workout title may legitimately contain the
    # separator and only the fields before it are structured.
    parts = decoded.split(_SEP, 5)
    if len(parts) < 4 or parts[0] != _KEY_VERSION:
        raise ValueError("unrecognised session key")

    try:
        start = datetime.fromtimestamp(int(parts[2]) / 1000, tz=timezone.utc)
    except (ValueError, OSError, OverflowError) as exc:
        raise ValueError("session key carries no usable start") from exc

    if parts[1] == "s":
        session_id = parts[3]
        if not session_id:
            raise ValueError("session key names no session")
        return SessionRef(kind="session_id", start=start, session_id=session_id)

    if parts[1] == "t":
        if len(parts) < 6:
            raise ValueError("legacy session key is incomplete")
        return SessionRef(
            kind="timestamp_title",
            start=start,
            source_id=parts[3] or None,
            category=parts[4] or None,
            title=parts[5],
        )

    raise ValueError("unrecognised session key")
