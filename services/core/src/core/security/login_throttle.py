"""Refusing the next guess, once there have been too many.

Nothing rate-limited the sign-in endpoint. No attempt counter, no lockout, no
backoff — and nothing at the edge either: the only Traefik middleware defined
anywhere in ``docker-compose.prod.yml`` is a path-strip for the docs. bcrypt made
each guess cost something, which is the only reason a credential-stuffing run was
slow rather than instant, and "slow" is not a control.

## One bucket, per account

Ten failures against one address in fifteen minutes and it stops answering. That
is well past mistyping a password and well short of a wordlist.

There is deliberately **no per-client bucket**, and the reasoning is worth
writing down because the omission looks like one. A per-client limit exists to
stop *spraying* — one common password tried against many addresses, where each
account only ever sees a single failure so an account bucket never trips. That
attack needs many real accounts to be worth anything. This platform ships with
``ALLOW_REGISTRATION`` off and one owner account created by
``python -m core.create_owner``; against a single account, spraying collapses
into exactly the attack the account bucket already stops.

What a per-client bucket would have cost is not the counting — it is knowing who
the client is. Behind a proxy the socket peer is the proxy, and ``X-Forwarded-For``
is append-only with nothing authenticating it, so its leftmost entry is whatever
the caller typed. Reading that would have produced a limit bypassed by sending
one header, which is worse than no limit because it reads as coverage. Doing it
properly means a configured count of trusted hops — a setting whose wrong value
degrades silently, for an attack this deployment does not face. If the workspace
ever gains a real user base, this is the thing to add back.

## The bucket keys on what was *submitted*

Not on the account that was found — and this is the part that is easy to get
wrong in a way that undoes the other fix in this commit. If a throttle only
engaged for addresses that exist, then a ``429`` would mean "this account is
real" and a ``401`` would mean "it is not", which is the enumeration oracle
:func:`core.main.login` just stopped leaking through timing. Hashing the
submitted string and counting that means both answers look identical from
outside.

## Only failures are counted, and success clears them

A successful sign-in deletes that address's failures. Otherwise somebody who
signs in on six devices a day would eventually lock themselves out of their own
workspace, which is a denial of service we would have written ourselves.

## What is stored

A digest. ``email_hash`` is ``sha256(address)`` and never the address, because an
email address is personal data and a counter needs only equality. The
alternative — a plaintext table of every address anyone tried to sign in as,
successful or not — would be a more sensitive record than the thing it exists to
protect. See ``core.db.models.LoginAttempt``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from core.db.models import LoginAttempt
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

#: How far back a failure counts. Long enough that a slow drip is still caught,
#: short enough that a locked-out person is not locked out for their afternoon.
WINDOW = timedelta(minutes=15)

#: Failures against one address before it stops answering.
MAX_PER_ACCOUNT = 10

#: A stable identifier the dashboard renders, not prose (rule 17).
THROTTLED_CODE = "too_many_attempts"


def _digest(value: str) -> str:
    return hashlib.sha256(value.strip().casefold().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ThrottleDecision:
    """Whether to answer this attempt, and when to try again if not."""

    allowed: bool
    retry_after_seconds: int = 0


async def check(
    session: AsyncSession, *, email: str, now: datetime | None = None
) -> ThrottleDecision:
    """Whether this sign-in may be attempted at all.

    Called **before** the password is verified, so a throttled caller does not
    get to spend our bcrypt either — otherwise the endpoint stops being a way to
    guess passwords and stays a way to burn CPU.
    """
    moment = now or datetime.now(timezone.utc)
    cutoff = moment - WINDOW
    key = _digest(email)

    # One indexed sweep of everything expired, not just this caller's rows.
    # Bounded work on a bounded table, and it means an attacker working through
    # addresses cannot grow the table by abandoning them.
    await session.execute(delete(LoginAttempt).where(LoginAttempt.attempted_at < cutoff))

    failures = int(
        (
            await session.execute(
                select(func.count()).where(
                    LoginAttempt.email_hash == key,
                    LoginAttempt.attempted_at >= cutoff,
                )
            )
        ).scalar_one()
        or 0
    )
    if failures < MAX_PER_ACCOUNT:
        return ThrottleDecision(allowed=True)

    # The oldest failure in the window is what has to age out before there is
    # room again, so that is the honest retry time.
    oldest = (
        await session.execute(
            select(func.min(LoginAttempt.attempted_at)).where(
                LoginAttempt.email_hash == key,
                LoginAttempt.attempted_at >= cutoff,
            )
        )
    ).scalar_one_or_none()
    retry = WINDOW - (moment - oldest) if oldest else WINDOW
    return ThrottleDecision(
        allowed=False, retry_after_seconds=max(1, int(retry.total_seconds()))
    )


async def record_failure(
    session: AsyncSession, *, email: str, now: datetime | None = None
) -> None:
    """Count one rejected sign-in against the address it was attempted for."""
    session.add(
        LoginAttempt(
            email_hash=_digest(email),
            attempted_at=now or datetime.now(timezone.utc),
        )
    )


async def clear_account(session: AsyncSession, *, email: str) -> None:
    """Forget an address's failures, because it just proved it knows the password."""
    await session.execute(
        delete(LoginAttempt).where(LoginAttempt.email_hash == _digest(email))
    )
