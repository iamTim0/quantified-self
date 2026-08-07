"""Session cookies for browser clients.

The dashboard used to keep its access and refresh tokens in ``localStorage``.
Anything running in the page could read them -- a cross-site scripting flaw, a
compromised dependency, a browser extension -- and a stolen refresh token is a
30-day session that survives a password change until it is explicitly revoked.

Browser sessions now travel in ``httpOnly`` cookies, which JavaScript cannot
read at all. That closes the exfiltration path but opens a different one: the
browser attaches cookies to *any* request it makes to this origin, including one
triggered by an attacker's page. Two things guard against that:

* ``SameSite=Lax`` -- the browser withholds the cookie on cross-site subrequests
  (including form posts), sending it only on top-level navigations. That alone
  stops classic CSRF, and Lax rather than Strict is required so the OIDC redirect
  back from the identity provider still arrives authenticated.
* A double-submit CSRF token -- ``qs_csrf`` is deliberately *not* httpOnly, so
  the dashboard can read it and echo it in the ``X-CSRF-Token`` header. An
  attacker's page can cause the cookie to be sent but cannot read it to build the
  matching header, because the same-origin policy stops it reading our response.
  This is defence in depth for the cases Lax does not cover: a same-site
  subdomain that has been compromised, and browsers that do not enforce Lax.

Bearer tokens still work on the ``Authorization`` header. That path is for
services, importers and API keys -- credentials no browser attaches on its own,
and therefore not reachable by CSRF.

Maps to Fizzbee Invariants:
- SessionCredentialNotReadableByScript
- StateChangingRequestRequiresCsrfProof
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from core.config import settings
from starlette.responses import Response

ACCESS_COOKIE = "qs_access"
REFRESH_COOKIE = "qs_refresh"
CSRF_COOKIE = "qs_csrf"
CSRF_HEADER = "X-CSRF-Token"

# The refresh token is scoped to the auth endpoints. There is no reason for it to
# ride along on every metrics query, and a narrower path means fewer places it
# can leak from (a proxy log, an error report, a misrouted request).
REFRESH_COOKIE_PATH = "/api/v1/auth"

# Methods that cannot change state and therefore need no CSRF proof.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def _max_age(expires_at: datetime) -> int:
    """Seconds until expiry, floored at zero."""
    delta = expires_at - datetime.now(timezone.utc)
    return max(0, int(delta.total_seconds()))


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def set_session_cookies(
    response: Response,
    *,
    access_token: str,
    access_expires: datetime,
    refresh_token: str,
    refresh_expires: datetime,
) -> str:
    """Attach the session cookies and return the CSRF token that pairs with them.

    The CSRF cookie outlives the access cookie on purpose: it has to still be
    readable when an expired access token is exchanged at ``/auth/refresh``.
    """
    csrf_token = new_csrf_token()
    common = {
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
        "domain": settings.COOKIE_DOMAIN,
    }

    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=_max_age(access_expires),
        httponly=True,
        path="/",
        **common,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=_max_age(refresh_expires),
        httponly=True,
        path=REFRESH_COOKIE_PATH,
        **common,
    )
    # Not httpOnly: the dashboard must read this one to echo it back in a header.
    # It is not a credential on its own -- it only proves the request was composed
    # by code that could read our origin's cookies.
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=_max_age(refresh_expires),
        httponly=False,
        path="/",
        **common,
    )
    return csrf_token


def clear_session_cookies(response: Response) -> None:
    """Expire every session cookie.

    ``delete_cookie`` must repeat the path and domain the cookie was set with, or
    the browser treats it as a different cookie and quietly keeps the original --
    which is exactly the class of bug that made logout not log anybody out.
    """
    common = {
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
        "domain": settings.COOKIE_DOMAIN,
    }
    response.delete_cookie(ACCESS_COOKIE, path="/", httponly=True, **common)
    response.delete_cookie(
        REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, httponly=True, **common
    )
    response.delete_cookie(CSRF_COOKIE, path="/", httponly=False, **common)


def csrf_token_matches(cookie_value: str | None, header_value: str | None) -> bool:
    """Constant-time comparison of the double-submit pair."""
    if not cookie_value or not header_value:
        return False
    return secrets.compare_digest(cookie_value, header_value)
