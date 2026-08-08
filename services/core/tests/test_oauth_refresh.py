"""Tests for OAuth connector credential refresh.

WHOOP access tokens expire in about an hour and the connector polls every six, so
before this a connector worked for one hour after someone pasted a token by hand
and then failed silently until they did it again.

The interesting cases are the ones that lose a credential rather than the happy
path: a rotation whose result is dropped, or a failed refresh that clears what
was there.

Maps to Fizzbee Invariants:
- SecretsAlwaysEncryptedAtRest
- TokenRefreshEnforced
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from core.oauth_refresh import (
    REFRESH_SKEW,
    RefreshedCredential,
    RefreshError,
    apply_refresh,
    can_refresh,
    needs_refresh,
    refresh_credential,
)
from core.security.crypto import decrypt_secret, encrypt_secret

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


def _config(**overrides):
    config = {
        "encrypted_token": encrypt_secret("old-access-token"),
        "encrypted_refresh_token": encrypt_secret("old-refresh-token"),
        "encrypted_client_secret": encrypt_secret("client-secret"),
        "client_id": "client-id",
        "token_expires_at": (NOW + timedelta(hours=1)).isoformat(),
    }
    config.update(overrides)
    return config


# ── When to refresh ──────────────────────────────────────────────────────────


def test_a_token_well_inside_its_lifetime_is_left_alone():
    assert needs_refresh(_config(), now=NOW) is False


def test_a_token_inside_the_skew_window_is_refreshed_before_it_expires():
    """Reacting to a 401 instead would start every import with a failed request."""
    config = _config(
        token_expires_at=(NOW + REFRESH_SKEW - timedelta(seconds=1)).isoformat()
    )
    assert needs_refresh(config, now=NOW) is True


def test_an_expired_token_is_refreshed():
    config = _config(token_expires_at=(NOW - timedelta(minutes=1)).isoformat())
    assert needs_refresh(config, now=NOW) is True


def test_a_token_with_no_recorded_expiry_is_not_refreshed():
    """A long-lived token (Home Assistant, say) must not have its refresh token
    spent on a guess."""
    config = _config()
    config.pop("token_expires_at")
    assert needs_refresh(config, now=NOW) is False
    assert needs_refresh({"token_expires_at": ""}, now=NOW) is False
    assert needs_refresh({"token_expires_at": "not-a-date"}, now=NOW) is False


def test_can_refresh_requires_every_part_of_the_grant():
    assert can_refresh("whoop", _config()) is True
    for missing in (
        "encrypted_refresh_token",
        "encrypted_client_secret",
        "client_id",
    ):
        partial = _config()
        partial.pop(missing)
        assert can_refresh("whoop", partial) is False, missing

    # A provider with no known token endpoint is never refreshable.
    assert can_refresh("yazio", _config()) is False


# ── Performing the refresh ───────────────────────────────────────────────────


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_successful_refresh_returns_the_new_pair(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        body = dict(pair.split("=") for pair in request.content.decode().split("&"))
        assert body["grant_type"] == "refresh_token"
        assert body["refresh_token"] == "old-refresh-token"
        return httpx.Response(
            200,
            json={
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
                "expires_in": 3600,
            },
        )

    _patch_client(monkeypatch, handler)
    result = await refresh_credential("whoop", _config(), req_id="req_test")

    assert result.access_token == "new-access-token"
    assert result.refresh_token == "new-refresh-token"
    assert result.expires_at is not None


@pytest.mark.asyncio
async def test_a_rejected_refresh_token_is_a_terminal_error(monkeypatch):
    """401/400 means the user revoked access. Retrying cannot fix it."""
    _patch_client(
        monkeypatch, lambda request: httpx.Response(401, json={"error": "invalid_grant"})
    )
    with pytest.raises(RefreshError, match="reconnected"):
        await refresh_credential("whoop", _config(), req_id="req_test")


@pytest.mark.asyncio
async def test_a_response_without_an_access_token_raises(monkeypatch):
    """Returning "no new token, carry on" would leave an expired one in use."""
    _patch_client(monkeypatch, lambda request: httpx.Response(200, json={"expires_in": 3600}))
    with pytest.raises(RefreshError, match="no access_token"):
        await refresh_credential("whoop", _config(), req_id="req_test")


@pytest.mark.asyncio
async def test_a_non_json_response_raises(monkeypatch):
    _patch_client(monkeypatch, lambda request: httpx.Response(200, text="<html>oops"))
    with pytest.raises(RefreshError, match="non-JSON"):
        await refresh_credential("whoop", _config(), req_id="req_test")


@pytest.mark.asyncio
async def test_an_unreachable_endpoint_raises_rather_than_returning_nothing(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    _patch_client(monkeypatch, handler)
    with pytest.raises(RefreshError, match="unreachable"):
        await refresh_credential("whoop", _config(), req_id="req_test")


# ── Persisting the result ────────────────────────────────────────────────────


def test_apply_refresh_stores_both_tokens_encrypted():
    """Verifies Fizzbee Invariant: SecretsAlwaysEncryptedAtRest"""
    updated = apply_refresh(
        _config(),
        RefreshedCredential(
            access_token="new-access-token",
            refresh_token="new-refresh-token",
            expires_at=NOW + timedelta(hours=1),
        ),
    )

    assert decrypt_secret(updated["encrypted_token"]) == "new-access-token"
    assert decrypt_secret(updated["encrypted_refresh_token"]) == "new-refresh-token"
    # Nothing in the stored config holds either value in the clear.
    for key, value in updated.items():
        if isinstance(value, str):
            assert "new-access-token" not in value or key == "encrypted_token"
            assert "new-refresh-token" not in value or key == "encrypted_refresh_token"
    assert updated["masked_token"].endswith("oken")
    assert "new-access-token" not in updated["masked_token"]


def test_a_response_without_a_new_refresh_token_keeps_the_existing_one():
    """Clearing it would leave a still-valid connector permanently unrefreshable."""
    original = _config()
    updated = apply_refresh(
        original,
        RefreshedCredential(
            access_token="new-access-token", refresh_token=None, expires_at=None
        ),
    )
    assert updated["encrypted_refresh_token"] == original["encrypted_refresh_token"]
    assert decrypt_secret(updated["encrypted_refresh_token"]) == "old-refresh-token"


def test_a_rotated_refresh_token_replaces_the_old_one():
    """WHOOP invalidates the previous refresh token, so keeping it would break
    the next refresh."""
    original = _config()
    updated = apply_refresh(
        original,
        RefreshedCredential(
            access_token="a", refresh_token="rotated", expires_at=None
        ),
    )
    assert updated["encrypted_refresh_token"] != original["encrypted_refresh_token"]
    assert decrypt_secret(updated["encrypted_refresh_token"]) == "rotated"


def _patch_client(monkeypatch, handler):
    """Route httpx.AsyncClient through a mock transport."""
    real_init = httpx.AsyncClient.__init__

    def init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)
