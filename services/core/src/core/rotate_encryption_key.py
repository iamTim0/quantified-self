"""Re-encrypt stored credentials from one ``ENCRYPTION_KEY`` to another.

``ENCRYPTION_KEY`` is the hardest of the published secrets to rotate, and the
reason it stayed unrotated: it is not a signing key that new tokens simply start
using, it decrypts data already sitting in the database. Change it without doing
anything else and every connector token and OIDC client secret becomes
permanently unreadable — the importers go quiet, the UI reports credentials that
cannot be decrypted, and there is nothing to fall back to.

So the rotation is: run this against the old and new keys, *then* set the new key
and restart. Both steps are in the runbook (docs/operations.md).

    python -m core.rotate_encryption_key --old "$CURRENT" --new "$NEW" --dry-run
    python -m core.rotate_encryption_key --old "$CURRENT" --new "$NEW"

What it touches, which is every column holding ciphertext:

* ``oidc_providers.encrypted_client_secret``
* ``data_sources.config`` — the ``encrypted_token``, ``encrypted_refresh_token``
  and ``encrypted_client_secret`` keys

Deliberately *not* tenant-scoped, and the only thing in this repository that is
allowed not to be: it is an operator tool run against the whole database with the
keys in hand, not a request handler. AGENTS.md rule 2 governs queries made on
behalf of a caller; there is no caller here.

Safety properties worth knowing before running it:

* One transaction. A crash halfway leaves the database on the old key, not on a
  mixture of both.
* Idempotent in the useful direction: a value that already decrypts under the new
  key is left alone and counted separately, so a re-run after a partial failure
  does not corrupt anything.
* A value that decrypts under neither key aborts the run rather than being
  skipped. Silently leaving a row behind would produce exactly the mixed state
  this tool exists to avoid.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import sys
from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

# Keys inside data_sources.config that hold ciphertext.
ENCRYPTED_CONFIG_KEYS = (
    "encrypted_token",
    "encrypted_refresh_token",
    "encrypted_client_secret",
)


def fernet_for(key_str: str) -> Fernet:
    """Build the Fernet instance for a raw key string.

    Mirrors core.security.crypto._get_fernet_instance exactly. Duplicated rather
    than imported because that module builds a module-level singleton from
    ``settings`` at first use, and this tool needs two different keys at once.
    """
    if len(key_str) < 16:
        raise ValueError("An ENCRYPTION_KEY must be at least 16 characters")
    digest = hashlib.sha256(key_str.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


@dataclass
class Report:
    reencrypted: int = 0
    already_new: int = 0
    empty: int = 0
    failures: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"  re-encrypted:            {self.reencrypted}",
            f"  already on the new key:  {self.already_new}",
            f"  empty / nothing to do:   {self.empty}",
        ]
        if self.failures:
            lines.append(f"  UNREADABLE:              {len(self.failures)}")
            lines.extend(f"    - {f}" for f in self.failures)
        return "\n".join(lines)


def _translate(value: str, old: Fernet, new: Fernet, label: str, report: Report) -> str:
    """Return the value encrypted under ``new``, or raise if it reads under neither."""
    if not value:
        report.empty += 1
        return value

    raw = value.encode("utf-8")
    try:
        plaintext = old.decrypt(raw)
    except InvalidToken:
        try:
            new.decrypt(raw)
        except InvalidToken:
            # Neither key opens it. Continuing would leave the database split
            # across two keys with no record of which rows are on which.
            report.failures.append(label)
            return value
        report.already_new += 1
        return value

    report.reencrypted += 1
    return new.encrypt(plaintext).decode("utf-8")


async def rotate(*, old_key: str, new_key: str, dry_run: bool) -> Report:
    """Re-encrypt every stored secret. Returns what was done (or would be)."""
    # Imported here so that --help works without a database URL configured.
    from core.db.models import DataSource, OidcProvider
    from core.db.session import async_session_maker

    old = fernet_for(old_key)
    new = fernet_for(new_key)
    report = Report()

    async with async_session_maker() as session:
        providers = (await session.execute(select(OidcProvider))).scalars().all()
        for provider in providers:
            if not provider.encrypted_client_secret:
                continue
            provider.encrypted_client_secret = _translate(
                provider.encrypted_client_secret,
                old,
                new,
                f"oidc_providers[{provider.slug}].encrypted_client_secret",
                report,
            )

        sources = (await session.execute(select(DataSource))).scalars().all()
        for source in sources:
            config = dict(source.config or {})
            changed = False
            for key in ENCRYPTED_CONFIG_KEYS:
                current = config.get(key)
                if not isinstance(current, str) or not current:
                    continue
                translated = _translate(
                    current,
                    old,
                    new,
                    f"data_sources[{source.id}].config.{key}",
                    report,
                )
                if translated != current:
                    config[key] = translated
                    changed = True
            if changed:
                # Reassign rather than mutate: SQLAlchemy does not track in-place
                # changes to a JSON column, so an in-place edit would be silently
                # dropped at commit — a rotation that reports success and writes
                # nothing.
                source.config = config

        if report.failures:
            await session.rollback()
            return report

        if dry_run:
            await session.rollback()
        else:
            await session.commit()

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--old", required=True, help="The ENCRYPTION_KEY currently in use")
    parser.add_argument("--new", required=True, help="The ENCRYPTION_KEY to move to")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change and roll back",
    )
    args = parser.parse_args(argv)

    if args.old == args.new:
        print("The old and new keys are identical; nothing to do.", file=sys.stderr)
        return 2

    try:
        report = asyncio.run(rotate(old_key=args.old, new_key=args.new, dry_run=args.dry_run))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Plain ASCII and an explicit flush. An em dash here rendered as a
    # replacement character on a Windows console, and unflushed stdout let the
    # stderr note below print *above* the summary it refers to.
    print("Dry run - nothing written." if args.dry_run else "Rotation committed.")
    print(report.summary(), flush=True)

    if report.failures:
        print(
            "\nAborted: the values listed above decrypt under neither key. Nothing "
            "was written. Check that --old is really the key currently in use.",
            file=sys.stderr,
        )
        return 1

    if not args.dry_run and report.reencrypted:
        print(
            "\nNow set ENCRYPTION_KEY to the new value and restart Core. Until you "
            "do, it is still reading with the old key and will fail to decrypt."
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
