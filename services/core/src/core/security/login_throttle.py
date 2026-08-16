"""Refusing the next guess, once there have been too many.

Nothing rate-limited the sign-in endpoint. No attempt counter, no lockout, no
backoff — and nothing at the edge either: the only Traefik middleware defined
anywhere in ``docker-compose.prod.yml`` is a path-strip for the docs. bcrypt made
each guess cost something, which is the only reason a credential-stuffing run was
slow rather than instant, and "slow" is not a control.

## Two buckets, because either alone is walked around

* **Per account** stops someone working through a password list against one
  address. On its own it does nothing about an attacker who tries one common
  password against a thousand addresses — each account sees a single failure.
* **Per client** stops exactly that spray, because all thousand attempts come
  from somewhere.

So both, with different ceilings: an account is allowed fewer failures than a
client, because one person mistyping their own password is a smaller number than
an office behind one address all signing in at nine o'clock.

## The account bucket keys on what was *submitted*

Not on the account that was found — and this is the part that is easy to get
wrong in a way that undoes the other fix in this commit. If a throttle only
engaged for addresses that exist, then a ``429`` would mean "this account is
real" and a ``401`` would mean "it is not", which is the enumeration oracle
:func:`core.main.login` just stopped leaking through timing. Hashing the
submitted string and counting that means both answers look identical from
outside.

## Only failures are counted, and success clears them

A successful sign-in deletes the account's failures. Otherwise somebody who
signs in on six devices a day would eventually lock themselves out of their own
workspace, which is a denial of service we would have written ourselves.

## What is stored

Digests. ``scope_key`` is ``sha256(value)`` and never the value, because an email
address and an IP address are both personal data and a counter needs only
equality. The alternative — a plaintext table of every address anyone tried to
sign in as, successful or not — would be a more sensitive record than the thing
it exists to protect. See ``core.db.models.LoginAttempt``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from core.db.models import LoginAttempt
from fastapi import Request
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

#: Set by the API Gateway from the connection it actually accepted, overwriting
#: anything the caller sent. See ``gateway.main`` — Core has no public route, so
#: a header arriving here has passed through the Gateway by construction.
CLIENT_IP_HEADER = "X-Client-IP"

#: How far back a failure counts. Long enough that a slow drip is still caught,
#: short enough that a locked-out person is not locked out for their afternoon.
WINDOW = timedelta(minutes=15)

#: Failures against one address before it stops answering. Ten is well past
#: mistyping a password and well short of a wordlist.
MAX_PER_ACCOUNT = 10

#: Failures from one client before it stops being served. Higher than the
#: account ceiling because an address is shared — a household, an office, a VPN
#: exit — and the point is to stop a spray, not a family.
MAX_PER_CLIENT = 30

SCOPE_ACCOUNT = "account"
SCOPE_CLIENT = "client"

#: A stable identifier the dashboard renders, not prose (rule 17).
THROTTLED_CODE = "too_many_attempts"


def _digest(value: str) -> str:
    return hashlib.sha256(value.strip().casefold().encode("utf-8")).hexdigest()


def client_address(request: Request) -> str | None:
    """The caller's address, or ``None`` when nothing trustworthy establishes one.

    Only :data:`CLIENT_IP_HEADER` is read, and only the Gateway sets it — from
    the connection it accepted, overwriting whatever the caller supplied. Core
    deliberately does **not** parse ``X-Forwarded-For`` itself: that header is
    appended to by every hop, the leftmost entry is whatever the client typed,
    and a limiter keyed on a value the attacker chooses is not a limiter. It is
    worse than none, because it reads as coverage.

    ``None`` rather than a placeholder when the header is absent. Falling back to
    a constant would put every such request in one bucket, and the first caller
    to exhaust it would lock out all the others — the per-account ceiling still
    applies in that case, which is the one that does not depend on the network.
    """
    value = (request.headers.get(CLIENT_IP_HEADER) or "").strip()
    return value or None


@dataclass(frozen=True)
class ThrottleDecision:
    """Whether to answer this attempt, and when to try again if not."""

    allowed: bool
    retry_after_seconds: int = 0


def _keys(email: str, client_ip: str | None) -> list[tuple[str, str, int]]:
    """The (scope, hashed key, ceiling) triples this attempt counts against.

    The client bucket is skipped entirely when no address could be established,
    rather than lumping every such request under one shared key — that would let
    one caller with no forwarded address lock out every other.
    """
    buckets = [(SCOPE_ACCOUNT, _digest(email), MAX_PER_ACCOUNT)]
    if client_ip:
        buckets.append((SCOPE_CLIENT, _digest(client_ip), MAX_PER_CLIENT))
    return buckets


async def check(
    session: AsyncSession, *, email: str, client_ip: str | None, now: datetime | None = None
) -> ThrottleDecision:
    """Whether this sign-in may be attempted at all.

    Called **before** the password is verified, so a throttled caller does not
    get to spend our bcrypt either — otherwise the endpoint stays a way to burn
    CPU even once it has stopped being a way to guess passwords.
    """
    moment = now or datetime.now(timezone.utc)
    cutoff = moment - WINDOW

    # One indexed sweep of everything expired, not just this caller's rows.
    # Bounded work on a bounded table, and it means an attacker rotating keys
    # cannot grow the table by abandoning them.
    await session.execute(delete(LoginAttempt).where(LoginAttempt.attempted_at < cutoff))

    buckets = _keys(email, client_ip)
    counts = dict(
        (
            await session.execute(
                select(LoginAttempt.scope, func.count())
                .where(
                    LoginAttempt.attempted_at >= cutoff,
                    or_(
                        *[
                            (LoginAttempt.scope == scope) & (LoginAttempt.scope_key == key)
                            for scope, key, _ in buckets
                        ]
                    ),
                )
                .group_by(LoginAttempt.scope)
            )
        ).all()
    )

    for scope, _key, ceiling in buckets:
        if counts.get(scope, 0) >= ceiling:
            # The oldest failure in the window is what has to age out before
            # there is room again, so that is the honest retry time.
            oldest = (
                await session.execute(
                    select(func.min(LoginAttempt.attempted_at)).where(
                        LoginAttempt.scope == scope,
                        LoginAttempt.scope_key == _key,
                        LoginAttempt.attempted_at >= cutoff,
                    )
                )
            ).scalar_one_or_none()
            retry = WINDOW - (moment - oldest) if oldest else WINDOW
            return ThrottleDecision(
                allowed=False, retry_after_seconds=max(1, int(retry.total_seconds()))
            )

    return ThrottleDecision(allowed=True)


async def record_failure(
    session: AsyncSession, *, email: str, client_ip: str | None, now: datetime | None = None
) -> None:
    """Count one rejected sign-in against every bucket it belongs to."""
    moment = now or datetime.now(timezone.utc)
    for scope, key, _ceiling in _keys(email, client_ip):
        session.add(LoginAttempt(scope=scope, scope_key=key, attempted_at=moment))


async def clear_account(session: AsyncSession, *, email: str) -> None:
    """Forget an address's failures, because it just proved it knows the password.

    Only the account bucket. The client bucket survives on purpose: one correct
    sign-in among a hundred wrong ones is what a successful stuffing run looks
    like, and clearing the address's count on that success would hand the
    attacker a reset.
    """
    await session.execute(
        delete(LoginAttempt).where(
            LoginAttempt.scope == SCOPE_ACCOUNT,
            LoginAttempt.scope_key == _digest(email),
        )
    )
