"""Create the first account, when self-registration is off.

``ALLOW_REGISTRATION`` now defaults to ``False``: this is a personal analytics
platform, and a deployment that accepts strangers should be a decision somebody
makes rather than what happens if they configure nothing. That leaves a gap —
with signup refused there is no way in — and this closes it.

Deliberately a command and not a startup step. AGENTS.md rule 9 forbids services
seeding data on boot, and the reason is on display in this repository's own
history: ``infra/db/init.sql`` used to insert an owner account with a bcrypt hash
committed alongside it, so every clone carried the same credentials for the same
address. An account created here has a password only the person who ran it has
seen.

    python -m core.create_owner --email you@example.com --workspace "My Data"

The password is read from a prompt, or from ``QS_OWNER_PASSWORD`` for automated
setups. Never from an argument: command lines end up in shell history, in `ps`
output, and in CI logs.

Idempotent in the way that matters — it refuses rather than overwrites. Resetting
a password is ``--reset-password`` on an existing address, which is an explicit
request, not a side effect of running the command twice.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import re
import sys
import uuid

from sqlalchemy import func, select

MIN_PASSWORD_LENGTH = 12

# Deliberately loose. Address validation is a swamp, and the only thing that
# matters here is catching a typo like a missing @ before a row is written.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class BootstrapError(Exception):
    """Something about the request is wrong; the message is for a human."""


def read_password(*, confirm: bool) -> str:
    """Take the password from the environment or a prompt, never from argv."""
    from_env = os.environ.get("QS_OWNER_PASSWORD")
    if from_env:
        password = from_env
    else:
        password = getpass.getpass("Password: ")
        if confirm and password != getpass.getpass("Repeat password: "):
            raise BootstrapError("The passwords do not match.")

    if len(password) < MIN_PASSWORD_LENGTH:
        raise BootstrapError(
            f"The password must be at least {MIN_PASSWORD_LENGTH} characters. "
            "This account is the whole way in; the signup form's six-character "
            "minimum is not the right bar for it."
        )
    return password


async def create_owner(
    *, email: str, name: str, workspace: str, password: str, reset: bool
) -> str:
    """Create the workspace and its owner, or reset an existing owner's password.

    Returns a line describing what happened, for the caller to print.
    """
    from core.db.models import Tenant, User
    from core.db.session import async_session_maker
    from core.main import pwd_context

    if not _EMAIL.match(email):
        raise BootstrapError(f"{email!r} does not look like an email address.")

    async with async_session_maker() as session:
        existing = (
            await session.execute(
                # Case-insensitive: signing up as Me@example.com and then being
                # told the account does not exist is a miserable ten minutes.
                select(User).where(func.lower(User.email) == email.lower())
            )
        ).scalars().first()

        if existing is not None:
            if not reset:
                raise BootstrapError(
                    f"An account already exists for {email}. Use --reset-password "
                    "to set a new password for it, which is a separate decision "
                    "from creating one."
                )
            existing.password_hash = pwd_context.hash(password)
            # Ends every session for that account -- the same cutoff a password
            # change through the API applies. Resetting a password and leaving
            # the old sessions working would defeat the point of resetting it.
            existing.sessions_valid_from = func.now()
            await session.commit()
            return f"Password reset for {email} (tenant {existing.tenant_id}). All sessions ended."

        if reset:
            raise BootstrapError(f"No account exists for {email}; nothing to reset.")

        tenant_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        session.add(Tenant(id=tenant_id, name=workspace))
        # Flushed before the user row: users carries a foreign key to tenants and
        # the unit of work does not otherwise guarantee the order.
        await session.flush()
        session.add(
            User(
                id=user_id,
                tenant_id=tenant_id,
                email=email,
                password_hash=pwd_context.hash(password),
                name=name,
                role="owner",
            )
        )
        await session.commit()

    return f"Created owner {email} in workspace {workspace!r} (tenant {tenant_id})."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--email", required=True, help="Sign-in address for the account")
    parser.add_argument("--name", default=None, help="Display name (defaults to the local part of the email)")
    parser.add_argument("--workspace", default=None, help="Workspace name (defaults to \"<name>'s Workspace\")")
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Set a new password on an existing account instead of creating one",
    )
    args = parser.parse_args(argv)

    name = args.name or args.email.split("@")[0]
    workspace = args.workspace or f"{name}'s Workspace"

    try:
        password = read_password(confirm=not os.environ.get("QS_OWNER_PASSWORD"))
        message = asyncio.run(
            create_owner(
                email=args.email,
                name=name,
                workspace=workspace,
                password=password,
                reset=args.reset_password,
            )
        )
    except BootstrapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\naborted", file=sys.stderr)
        return 130

    print(message)
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
