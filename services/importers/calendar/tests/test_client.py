"""Tests for calendar feed fetching and auth-mode detection.

The reported bug: an Outlook/Office ``.ics`` URL demanded an unrelated API key.
The dashboard refused to save the connector without one, and the importer sent
``Authorization: Bearer`` unconditionally and then tried to parse JSON.

These tests pin the four modes the brief asks to distinguish, and the rule that a
valid ICS URL works without a key.
"""

import httpx
import pytest
from calendar_importer.client import (
    CalendarAuthError,
    CalendarFetchError,
    build_feed_config,
    fetch_feed,
    infer_auth_mode,
)

PUBLIC_ICS = "https://outlook.office365.com/owa/calendar/public/calendar.ics"
SECRET_ICS = (
    "https://outlook.office365.com/owa/calendar/"
    "a1b2c3d4e5f60718293a4b5c6d7e8f90/reachcalendar.ics"
)
QUERY_ICS = "https://calendar.example.test/feed.ics?token=abcdef123456"

MINIMAL_ICS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//EN\r\n"
    "BEGIN:VEVENT\r\nUID:a@b\r\nDTSTART:20260805T090000Z\r\nDTEND:20260805T100000Z\r\n"
    "END:VEVENT\r\nEND:VCALENDAR"
)


class _Transport(httpx.AsyncBaseTransport):
    """Serve a canned response and record what was requested."""

    def __init__(self, response: httpx.Response):
        self.response = response
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.response.request = request
        return self.response


@pytest.fixture
def patched_client(monkeypatch):
    """Install a transport into every AsyncClient the module creates."""

    def _install(response: httpx.Response) -> _Transport:
        transport = _Transport(response)
        original = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = transport
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        return transport

    return _install


# ─── Auth-mode inference ─────────────────────────────────────


def test_plain_ics_url_needs_no_credential():
    """This is the reported bug: a public .ics must not require an API key."""
    assert infer_auth_mode({"ics_url": PUBLIC_ICS}, None) == "public_ics"


def test_tokenized_ics_url_is_recognised_as_private():
    """The URL itself is the secret; it must be treated as a credential."""
    assert infer_auth_mode({"ics_url": SECRET_ICS}, None) == "private_ics"
    assert infer_auth_mode({"ics_url": QUERY_ICS}, None) == "private_ics"


def test_username_and_password_select_basic_auth():
    assert (
        infer_auth_mode(
            {"base_url": "https://caldav.example.test/", "username": "u", "password": "p"},
            None,
        )
        == "basic_auth"
    )


def test_non_ics_url_with_token_uses_api_key():
    assert infer_auth_mode({"base_url": "https://api.example.test"}, "tok") == "api_key"


def test_explicit_auth_mode_wins():
    assert infer_auth_mode({"ics_url": PUBLIC_ICS, "auth_mode": "api_key"}, "t") == "api_key"


def test_missing_url_is_rejected():
    with pytest.raises(CalendarFetchError):
        build_feed_config({}, None)


def test_non_http_url_is_rejected():
    with pytest.raises(CalendarFetchError):
        build_feed_config({"ics_url": "file:///etc/passwd"}, None)


def test_safe_url_hides_the_secret_part():
    """A private feed URL must never be loggable in full."""
    feed = build_feed_config({"ics_url": QUERY_ICS}, None)
    assert "token=abcdef123456" not in feed.safe_url
    assert "calendar.example.test" in feed.safe_url


# ─── Fetching ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_public_feed_is_fetched_without_authorization(patched_client):
    transport = patched_client(
        httpx.Response(200, text=MINIMAL_ICS, headers={"content-type": "text/calendar"})
    )
    feed = build_feed_config({"ics_url": PUBLIC_ICS}, None)

    body = await fetch_feed(feed)

    assert "BEGIN:VCALENDAR" in body
    assert "authorization" not in {k.lower() for k in transport.requests[0].headers}


@pytest.mark.asyncio
async def test_api_key_mode_sends_a_bearer_token(patched_client):
    transport = patched_client(
        httpx.Response(200, text=MINIMAL_ICS, headers={"content-type": "text/calendar"})
    )
    feed = build_feed_config(
        {"base_url": "https://api.example.test/cal", "auth_mode": "api_key"}, "secret-token"
    )

    await fetch_feed(feed)

    assert transport.requests[0].headers["authorization"] == "Bearer secret-token"


@pytest.mark.asyncio
async def test_ics_served_as_text_plain_is_still_accepted(patched_client):
    """Plenty of servers serve .ics as text/plain; content sniffing covers it."""
    patched_client(
        httpx.Response(200, text=MINIMAL_ICS, headers={"content-type": "text/plain"})
    )
    feed = build_feed_config({"ics_url": PUBLIC_ICS}, None)

    assert "BEGIN:VCALENDAR" in await fetch_feed(feed)


@pytest.mark.asyncio
async def test_html_login_page_is_reported_as_an_auth_problem(patched_client):
    """The classic symptom of an expired secret address."""
    patched_client(
        httpx.Response(
            200, text="<html>Sign in</html>", headers={"content-type": "text/html"}
        )
    )
    feed = build_feed_config({"ics_url": SECRET_ICS}, None)

    with pytest.raises(CalendarAuthError):
        await fetch_feed(feed)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_rejected_credentials_raise_auth_error(patched_client, status):
    patched_client(httpx.Response(status, text="nope"))
    feed = build_feed_config({"ics_url": PUBLIC_ICS}, None)

    with pytest.raises(CalendarAuthError):
        await fetch_feed(feed)


@pytest.mark.asyncio
async def test_revoked_feed_url_reports_404_clearly(patched_client):
    patched_client(httpx.Response(404, text="gone"))
    feed = build_feed_config({"ics_url": SECRET_ICS}, None)

    with pytest.raises(CalendarFetchError, match="revoked"):
        await fetch_feed(feed)


@pytest.mark.asyncio
async def test_error_message_never_contains_the_feed_url(patched_client):
    """A failure must not leak a private calendar address into logs."""
    patched_client(httpx.Response(500, text="boom"))
    feed = build_feed_config({"ics_url": QUERY_ICS}, None)

    with pytest.raises(CalendarFetchError) as excinfo:
        await fetch_feed(feed)

    assert "abcdef123456" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_json_response_is_rejected_as_not_a_calendar(patched_client):
    patched_client(
        httpx.Response(200, text='{"events": []}', headers={"content-type": "application/json"})
    )
    feed = build_feed_config({"ics_url": PUBLIC_ICS}, None)

    with pytest.raises(CalendarFetchError):
        await fetch_feed(feed)
