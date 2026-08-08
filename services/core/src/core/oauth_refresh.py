"""Refreshing expiring OAuth connector credentials.

WHOOP issues an access token that expires in about an hour, alongside a refresh
token. Nothing refreshed either: once the access token expired the importer got
401s until somebody pasted a new token by hand, which for a connector meant to
poll every six hours is a connector that works for one hour.

The refresh happens **in Core**, not in the importer, for the same reason the
credential is stored here: importers are stateless and hold no secrets (rule 8),
and rotating a credential means writing the new one back encrypted, which needs
the database only Core may touch (rule 1).

Design notes worth keeping:

* **Refresh before expiry, not after a 401.** Reacting to a 401 means every
  import starts with a guaranteed-failed request, and a provider that rate-limits
  auth failures will punish that.
* **A rotated refresh token must be persisted, and a rotation failure must not
  destroy the old one.** WHOOP returns a new refresh token with each refresh and
  invalidates the previous one. Writing the new pair before confirming the
  response parsed would leave the connector with no usable credential at all.
* **The refresh token never leaves this service.** It is returned to nobody: the
  importer receives only the short-lived access token.

Maps to Fizzbee Invariants:
- SecretsAlwaysEncryptedAtRest
- TokenRefreshEnforced
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from core.security.crypto import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

# Refresh this far ahead of expiry. Long enough that a sync started now will not
# have its token die mid-run; short enough not to churn tokens needlessly.
REFRESH_SKEW = timedelta(minutes=5)

# Providers whose credentials can be refreshed, and where.
TOKEN_ENDPOINTS: dict[str, str] = {
    "whoop": "https://api.prod.whoop.com/oauth/oauth2/token",
}


class RefreshError(Exception):
    """The credential could not be refreshed."""


@dataclass(frozen=True)
class RefreshedCredential:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None


def _parse_expiry(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def needs_refresh(config: dict[str, Any], *, now: datetime) -> bool:
    """Whether the stored access token is expired or about to be.

    A connector with no recorded expiry is left alone: the token may be
    long-lived (a Home Assistant token, say), and refreshing on a guess would
    burn a single-use refresh token for nothing.
    """
    expires_at = _parse_expiry(config.get("token_expires_at"))
    if expires_at is None:
        return False
    return now + REFRESH_SKEW >= expires_at


def can_refresh(source_type: str, config: dict[str, Any]) -> bool:
    return bool(
        source_type in TOKEN_ENDPOINTS
        and config.get("encrypted_refresh_token")
        and config.get("client_id")
        and config.get("encrypted_client_secret")
    )


async def refresh_credential(
    source_type: str, config: dict[str, Any], *, req_id: str
) -> RefreshedCredential:
    """Exchange the stored refresh token for a new access token.

    Raises RefreshError rather than returning a partial result: a caller that
    received "no new token, carry on" would keep using an expired one.
    """
    endpoint = TOKEN_ENDPOINTS.get(source_type)
    if endpoint is None:
        raise RefreshError(f"No token endpoint known for {source_type}")

    try:
        refresh_token = decrypt_secret(config["encrypted_refresh_token"])
        client_secret = decrypt_secret(config["encrypted_client_secret"])
    except Exception as exc:  # noqa: BLE001 - decryption failure detail must not leak
        raise RefreshError("Stored credential could not be decrypted") from exc

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": config["client_id"],
        "client_secret": client_secret,
        # WHOOP requires `offline` to be re-requested, otherwise the response
        # carries no new refresh token and the chain ends after one rotation.
        "scope": "offline",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(endpoint, data=payload)
    except httpx.RequestError as exc:
        raise RefreshError(f"Token endpoint unreachable: {exc.__class__.__name__}") from exc

    if response.status_code in (400, 401):
        # The refresh token itself is dead -- the user revoked access, or a
        # previous rotation was lost. No amount of retrying fixes it.
        raise RefreshError(
            "Refresh token was rejected; the connector must be reconnected"
        )
    if not response.is_success:
        raise RefreshError(f"Token endpoint returned {response.status_code}")

    try:
        body = response.json()
    except ValueError as exc:
        raise RefreshError("Token endpoint returned a non-JSON response") from exc

    access_token = body.get("access_token")
    if not access_token:
        raise RefreshError("Token response carried no access_token")

    expires_in = body.get("expires_in")
    expires_at = None
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

    logger.info(
        "[req_id=%s] Refreshed %s credential; expires_at=%s",
        req_id,
        source_type,
        expires_at.isoformat() if expires_at else "unknown",
    )
    # Note what is *not* logged: neither token, not even truncated (rule 12).
    return RefreshedCredential(
        access_token=access_token,
        refresh_token=body.get("refresh_token"),
        expires_at=expires_at,
    )


def apply_refresh(config: dict[str, Any], refreshed: RefreshedCredential) -> dict[str, Any]:
    """Return an updated config with the new credential encrypted at rest.

    A provider that rotates its refresh token invalidates the previous one, so a
    new one must replace the stored value. When the response carries none, the
    existing refresh token is kept rather than cleared -- dropping it would leave
    the connector unrefreshable even though it is still valid.
    """
    updated = dict(config)
    updated["encrypted_token"] = encrypt_secret(refreshed.access_token)
    updated["masked_token"] = f"{'•' * 8}{refreshed.access_token[-4:]}"
    if refreshed.refresh_token:
        updated["encrypted_refresh_token"] = encrypt_secret(refreshed.refresh_token)
    if refreshed.expires_at:
        updated["token_expires_at"] = refreshed.expires_at.isoformat()
    updated["token_refreshed_at"] = datetime.now(timezone.utc).isoformat()
    return updated
