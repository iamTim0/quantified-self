"""OpenID Connect Authorization Code flow with PKCE.

Provider-agnostic by construction: Google is a row in ``oidc_providers``, not a
branch in the code. Everything provider-specific — issuer, client id, secret,
scopes, redirect URI, claim names — is configuration.

What is validated on the way back, and why each matters:

* **state** — bound to a single server-side row, single-use. Without it the
  callback is forgeable (CSRF login).
* **PKCE (S256)** — the code is useless to anyone who intercepts it without the
  verifier, which never leaves the server.
* **issuer** — must equal the configured issuer exactly, so a token minted by some
  other provider cannot be replayed here.
* **audience** — must be our client id, so a token issued for a different
  application is refused.
* **signature** — verified against the provider's JWKS, fetched from its discovery
  document. ``alg: none`` and symmetric algorithms are rejected outright.
* **expiry / issued-at** — with a small leeway for clock skew.
* **nonce** — must match the one generated for this request, which binds the ID
  token to this authorization request.

Identity is keyed on ``(provider, sub)``, never on the email address: email
addresses change hands and can be re-registered, and matching on them is precisely
how account-takeover happens.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient

logger = logging.getLogger(__name__)

# Only asymmetric algorithms. A symmetric one would let anyone holding the client
# secret mint tokens, and "none" needs no explanation.
ALLOWED_ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "PS256"]
CLOCK_SKEW_SECONDS = 60
DISCOVERY_TIMEOUT = 10.0
AUTH_REQUEST_TTL_SECONDS = 600

_discovery_cache: dict[str, dict[str, Any]] = {}
_jwk_clients: dict[str, PyJWKClient] = {}


class OidcError(Exception):
    """Raised when a provider is misconfigured or a response fails validation."""

    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class AuthorizationRequest:
    """What the caller needs to start a login, plus what we must remember."""

    authorization_url: str
    state: str
    nonce: str
    code_verifier: str


@dataclass(frozen=True)
class VerifiedIdentity:
    """A validated federated identity."""

    subject: str
    email: str | None
    email_verified: bool
    name: str | None
    raw_claims: dict[str, Any]


def generate_pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for the S256 method."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


async def fetch_discovery(issuer: str) -> dict[str, Any]:
    """Load and cache the provider's OpenID configuration.

    The issuer is normalised and the document's own ``issuer`` is checked against
    it, so a discovery document cannot redirect us to a different identity provider.
    """
    normalised = issuer.rstrip("/")
    if normalised in _discovery_cache:
        return _discovery_cache[normalised]

    url = f"{normalised}/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=DISCOVERY_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        raise OidcError(
            f"OIDC discovery failed for {normalised}: {type(exc).__name__}", 502
        ) from exc

    if response.status_code != 200:
        raise OidcError(f"OIDC discovery returned HTTP {response.status_code}", 502)

    document = response.json()
    if document.get("issuer", "").rstrip("/") != normalised:
        raise OidcError("OIDC discovery document issuer does not match the configured issuer", 502)

    for required in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not document.get(required):
            raise OidcError(f"OIDC discovery document is missing {required}", 502)

    _discovery_cache[normalised] = document
    return document


def end_session_url(
    discovery: dict[str, Any], *, post_logout_redirect_uri: str, client_id: str
) -> str | None:
    """The provider's RP-initiated logout URL, or None if it does not offer one.

    Logging out here previously ended only the local session. The provider's stays
    live, so the next "sign in with…" click completes instantly with no prompt and
    the user reasonably concludes that logging out did nothing.

    `end_session_endpoint` is optional in OpenID Connect. Returning None rather
    than guessing a URL matters: a fabricated logout endpoint would send the user
    to a 404 on someone else's domain.
    """
    endpoint = discovery.get("end_session_endpoint")
    if not endpoint:
        return None

    # No id_token_hint. Passing one would identify the user to the provider in a
    # URL that lands in browser history and any intermediate log; the tradeoff is
    # that some providers will ask the user to confirm which account to sign out
    # of, which is the safer failure.
    query = urlencode(
        {
            "client_id": client_id,
            "post_logout_redirect_uri": post_logout_redirect_uri,
        }
    )
    separator = "&" if "?" in endpoint else "?"
    return f"{endpoint}{separator}{query}"


def clear_discovery_cache() -> None:
    """Drop cached discovery documents and JWKS clients (config change, tests)."""
    _discovery_cache.clear()
    _jwk_clients.clear()


def build_authorization_request(
    *,
    discovery: dict[str, Any],
    client_id: str,
    redirect_uri: str,
    scopes: str,
) -> AuthorizationRequest:
    """Assemble the provider URL the browser should be sent to."""

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier, challenge = generate_pkce_pair()

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = f"{discovery['authorization_endpoint']}?{urlencode(params)}"
    return AuthorizationRequest(
        authorization_url=url, state=state, nonce=nonce, code_verifier=verifier
    )


async def exchange_code(
    *,
    discovery: dict[str, Any],
    client_id: str,
    client_secret: str | None,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict[str, Any]:
    """Trade the authorization code for tokens."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    # Public clients (no secret) are legitimate precisely because PKCE protects them.
    if client_secret:
        data["client_secret"] = client_secret

    try:
        async with httpx.AsyncClient(timeout=DISCOVERY_TIMEOUT) as client:
            response = await client.post(
                discovery["token_endpoint"],
                data=data,
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise OidcError(f"Token exchange failed: {type(exc).__name__}", 502) from exc

    if response.status_code != 200:
        # The provider's body can contain the code; never echo it back.
        logger.warning("OIDC token exchange rejected with HTTP %s", response.status_code)
        raise OidcError("The identity provider rejected the authorization code", 401)

    payload = response.json()
    if not payload.get("id_token"):
        raise OidcError("The identity provider returned no id_token", 502)
    return payload


def verify_id_token(
    *,
    id_token: str,
    discovery: dict[str, Any],
    client_id: str,
    issuer: str,
    expected_nonce: str,
) -> VerifiedIdentity:
    """Validate signature, issuer, audience, expiry and nonce, then return claims."""
    jwks_uri = discovery["jwks_uri"]
    if jwks_uri not in _jwk_clients:
        _jwk_clients[jwks_uri] = PyJWKClient(jwks_uri, cache_keys=True)

    try:
        signing_key = _jwk_clients[jwks_uri].get_signing_key_from_jwt(id_token)
    except Exception as exc:
        raise OidcError(f"Could not resolve the signing key: {type(exc).__name__}", 401) from exc

    try:
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=ALLOWED_ALGORITHMS,
            audience=client_id,
            issuer=issuer.rstrip("/"),
            leeway=CLOCK_SKEW_SECONDS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise OidcError("The identity token has expired", 401) from exc
    except jwt.PyJWTError as exc:
        # Deliberately generic: the specific failure is an oracle.
        logger.warning("OIDC id_token validation failed: %s", type(exc).__name__)
        raise OidcError("The identity token could not be validated", 401) from exc

    # Not covered by jwt.decode: the nonce binds the token to *this* request.
    if claims.get("nonce") != expected_nonce:
        raise OidcError("The identity token does not match this login attempt", 401)

    subject = str(claims.get("sub") or "")
    if not subject:
        raise OidcError("The identity token has no subject", 401)

    return VerifiedIdentity(
        subject=subject,
        email=claims.get("email"),
        email_verified=bool(claims.get("email_verified", False)),
        name=claims.get("name") or claims.get("given_name"),
        raw_claims=claims,
    )


# ─── Back-channel logout ─────────────────────────────────────

# The event a logout token must carry. Its absence is what distinguishes a logout
# token from any other token the provider signs.
BACKCHANNEL_LOGOUT_EVENT = "http://schemas.openid.net/event/backchannel-logout"

# How old a logout token may be. The specification recommends remembering `jti`
# values to reject replays; re-revoking an already revoked session is idempotent,
# so a replay only matters if it can reach past a *subsequent* legitimate sign-in
# and end that session too. A freshness window closes exactly that case without a
# second denylist table to write, index and prune. Generous enough for clock skew
# and a provider's retry, short enough that a captured token is worthless by the
# time anybody could sign in again.
LOGOUT_TOKEN_MAX_AGE_SECONDS = 120


@dataclass(frozen=True)
class LogoutSubject:
    """Who a validated logout token is about."""

    subject: str | None
    session_id: str | None


def verify_logout_token(
    *,
    logout_token: str,
    discovery: dict[str, Any],
    client_id: str,
    issuer: str,
    now: float | None = None,
) -> LogoutSubject:
    """Validate an OIDC Back-Channel Logout token and return who it names.

    This is the only thing standing between an unauthenticated, internet-facing
    endpoint and the ability to end anyone's session, so every clause below is
    load-bearing. ``specs/oidc_backchannel_logout.fizz`` states the check list as
    an invariant: remove one and the model checker produces the defect that then
    gets through.

    Raises:
        OidcError: with 400 for a token that is invalid, and 503 when the
            provider's keys cannot be reached — a distinction the caller passes
            on, so the provider retries the second and does not retry the first.
    """
    jwks_uri = discovery["jwks_uri"]
    if jwks_uri not in _jwk_clients:
        _jwk_clients[jwks_uri] = PyJWKClient(jwks_uri, cache_keys=True)

    try:
        signing_key = _jwk_clients[jwks_uri].get_signing_key_from_jwt(logout_token)
    except Exception as exc:
        # Cannot verify, so cannot act. Fail closed and let the provider retry:
        # acting on an unverifiable token would let anyone who can reach this
        # endpoint end any session by posting plausible JSON during an outage.
        raise OidcError(
            f"Could not resolve the signing key: {type(exc).__name__}", 503
        ) from exc

    try:
        claims = jwt.decode(
            logout_token,
            signing_key.key,
            algorithms=ALLOWED_ALGORITHMS,
            audience=client_id,
            issuer=issuer.rstrip("/"),
            leeway=CLOCK_SKEW_SECONDS,
            # `exp` is deliberately absent: it is optional in a logout token, and
            # requiring it would reject conformant providers. Freshness is
            # enforced below on `iat`, which is mandatory.
            options={"require": ["iss", "aud", "iat", "jti"]},
        )
    except jwt.PyJWTError as exc:
        logger.warning("OIDC logout token rejected: %s", type(exc).__name__)
        raise OidcError("The logout token could not be validated", 400) from exc

    # A `nonce` means this is an ID token. Without this check, an ID token
    # captured during a *login* could be replayed here as a logout.
    if "nonce" in claims:
        raise OidcError("A logout token must not carry a nonce", 400)

    events = claims.get("events")
    if not isinstance(events, dict) or not isinstance(
        events.get(BACKCHANNEL_LOGOUT_EVENT), dict
    ):
        raise OidcError("The token is not a back-channel logout event", 400)

    reference = time.time() if now is None else now
    age = reference - float(claims["iat"])
    if age > LOGOUT_TOKEN_MAX_AGE_SECONDS + CLOCK_SKEW_SECONDS:
        raise OidcError("The logout token is too old", 400)

    subject = claims.get("sub")
    session_id = claims.get("sid")
    if not subject and not session_id:
        raise OidcError("The logout token names neither a subject nor a session", 400)

    return LogoutSubject(
        subject=str(subject) if subject else None,
        session_id=str(session_id) if session_id else None,
    )


def apply_claims_mapping(
    identity: VerifiedIdentity, mapping: dict[str, Any]
) -> VerifiedIdentity:
    """Re-read fields from provider-specific claim names, if configured."""
    if not mapping:
        return identity

    claims = identity.raw_claims
    return VerifiedIdentity(
        subject=str(claims.get(mapping.get("subject", "sub"), identity.subject)),
        email=claims.get(mapping.get("email", "email"), identity.email),
        email_verified=bool(
            claims.get(mapping.get("email_verified", "email_verified"), identity.email_verified)
        ),
        name=claims.get(mapping.get("name", "name"), identity.name),
        raw_claims=claims,
    )


def is_redirect_uri_allowed(candidate: str, configured: str) -> bool:
    """Exact match only.

    Prefix or host matching is how open redirects get shipped: an attacker
    registers ``https://our-app.example.com.evil.test`` and the token goes to them.
    """
    return candidate.strip() == configured.strip()
