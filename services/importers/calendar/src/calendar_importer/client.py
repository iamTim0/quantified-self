"""Fetching calendar feeds.

A calendar is reached in one of three ways, inferred from what the tenant
configured unless they set it explicitly, so pasting an Outlook ``.ics`` link
just works:

* ``public_ics``   — a plain ``.ics`` URL. **No credential required.**
* ``private_ics``  — a tokenized ``.ics`` URL (Outlook/Google "secret address").
                     The URL itself is the credential, so it is never logged.
* ``basic_auth``   — CalDAV-style username/password.

There used to be a fourth, ``api_key``, which sent ``Authorization: Bearer``.
It never did what its name suggested: `fetch_feed` still required an *ICS body*
in that mode, so a JSON REST calendar was never actually supported — the bearer
header was the only difference. It has been removed rather than finished,
because every provider people actually use publishes an ICS feed, and keeping a
mode that exists only to demand a credential is what made an Outlook feed
impossible to add.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

ICS_CONTENT_TYPES = ("text/calendar", "application/ics", "text/x-vcalendar")
MAX_FEED_BYTES = 25 * 1024 * 1024


class CalendarFetchError(RuntimeError):
    """Raised when a calendar feed cannot be retrieved."""


class CalendarAuthError(CalendarFetchError):
    """Raised on 401/403 — the stored credential is wrong or expired."""


@dataclass(frozen=True)
class FeedConfig:
    """How to reach one tenant's calendar."""

    url: str
    auth_mode: str = "public_ics"
    username: str | None = None
    password: str | None = None
    display_timezone: str = "UTC"

    @property
    def safe_url(self) -> str:
        """The URL with query and userinfo removed, for logs.

        A private feed URL carries its secret in the path or query string, so the
        full URL must never reach a log line.
        """
        parsed = urlparse(self.url)
        host = parsed.hostname or "?"
        return f"{parsed.scheme}://{host}/…"


def infer_auth_mode(config: dict[str, Any]) -> str:
    """Work out how to authenticate from what the tenant actually configured.

    An ``.ics`` URL with no credential is a public feed — the old behaviour of
    demanding an API key for it was the reported bug.
    """
    explicit = (config.get("auth_mode") or "").strip().lower()
    if explicit in {"public_ics", "private_ics", "basic_auth"}:
        return explicit

    if config.get("username") and config.get("password"):
        return "basic_auth"

    url = (config.get("ics_url") or config.get("base_url") or "").strip()
    looks_like_ics = url.lower().split("?")[0].endswith(".ics")

    # A tokenized feed is still just a URL fetch; the distinction is only whether
    # the URL is a secret, which changes how we log it. The `.ics` suffix is not
    # required -- plenty of providers serve a feed from an extensionless path.
    if not looks_like_ics:
        logger.info("Calendar URL does not end in .ics; fetching it as a feed anyway.")
    return "private_ics" if _url_carries_secret(url) else "public_ics"


def _url_carries_secret(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.query:
        return True
    # Outlook/Google secret addresses embed a long opaque path segment.
    return any(len(segment) >= 32 for segment in parsed.path.split("/"))


def build_feed_config(config: dict[str, Any]) -> FeedConfig:
    """Assemble a FeedConfig from stored connector configuration."""
    url = (config.get("ics_url") or config.get("base_url") or "").strip()
    if not url:
        raise CalendarFetchError("No calendar URL configured")

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise CalendarFetchError("Calendar URL must be http(s)")

    return FeedConfig(
        url=url,
        auth_mode=infer_auth_mode(config),
        username=config.get("username"),
        password=config.get("password"),
        display_timezone=config.get("timezone") or config.get("display_timezone") or "UTC",
    )


async def fetch_feed(feed: FeedConfig, *, timeout: float = 30.0) -> str:
    """Retrieve the raw feed body.

    Redirects are followed, because Outlook and Google both hand out URLs that
    redirect at least once. The response is accepted when it is either declared as
    calendar data or simply looks like it, since plenty of servers serve ``.ics``
    files as ``text/plain`` or ``application/octet-stream``.
    """
    headers = {"Accept": "text/calendar, text/plain;q=0.9, */*;q=0.5"}
    auth: httpx.Auth | None = None

    if feed.auth_mode == "basic_auth":
        if not (feed.username and feed.password):
            raise CalendarAuthError("Basic auth configured but username/password missing")
        auth = httpx.BasicAuth(feed.username, feed.password)

    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, auth=auth
        ) as client:
            response = await client.get(feed.url, headers=headers)
    except httpx.HTTPError as exc:
        # Never interpolate the URL: it may be the credential.
        raise CalendarFetchError(
            f"Could not reach calendar feed at {feed.safe_url}: {type(exc).__name__}"
        ) from exc

    if response.status_code in (401, 403):
        raise CalendarAuthError(
            f"Calendar feed rejected the stored credential ({response.status_code})"
        )
    if response.status_code == 404:
        raise CalendarFetchError("Calendar feed not found (404) — has the URL been revoked?")
    if response.status_code >= 400:
        raise CalendarFetchError(f"Calendar feed returned HTTP {response.status_code}")

    if len(response.content) > MAX_FEED_BYTES:
        raise CalendarFetchError("Calendar feed is implausibly large; refusing to parse")

    body = response.text
    content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()

    if content_type not in ICS_CONTENT_TYPES and "BEGIN:VCALENDAR" not in body[:2048].upper():
        if content_type in ("text/html", "application/xhtml+xml"):
            # The classic symptom of a login wall or an expired secret address.
            raise CalendarAuthError(
                "Calendar URL returned an HTML page instead of a calendar. "
                "The feed may require authentication or the secret address may have expired."
            )
        raise CalendarFetchError(
            f"Calendar URL returned '{content_type or 'unknown content type'}', not iCalendar data"
        )

    logger.info(
        "Fetched calendar feed from %s (%s, %d bytes)",
        feed.safe_url,
        feed.auth_mode,
        len(response.content),
    )
    return body
