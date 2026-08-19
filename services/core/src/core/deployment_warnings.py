"""Configuration and credential problems, phrased for the person running this.

Everything here was previously only visible to whoever read the startup logs, a
commit message or the operations manual — which in practice means nobody. A
platform that is misconfigured in a way that matters should say so where its
operator is actually looking.

Two kinds of warning, and they differ in who may see them:

* **Deployment** warnings describe how the installation is configured. They name
  which secret is weak, which is a small disclosure in itself, so they are shown
  to owners and administrators only.
* **Account** warnings are about the calling user's own credentials and go to
  that user whatever their role. Withholding "your password is public" from
  somebody because they are only a member would be absurd.

On the published-password check
-------------------------------
``infra/db/init.sql`` used to seed an owner account with a bcrypt hash committed
next to it. Anyone with a copy of the repository had that hash and the address it
opens, and bcrypt is only a delay, not a wall. The account was removed and the
history rewritten, but neither of those makes a password unseen — so an account
still *using* one of those passwords is warned, every time it signs in, until it
changes.

The known hashes are stored as SHA-256 digests rather than as themselves. Putting
a real bcrypt hash back into a tracked file to detect a leaked bcrypt hash would
re-commit the very thing being warned about, and ``check_private_info.py`` would
rightly refuse it.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Literal

from core.security.secret_audit import PUBLISHED_DEFAULTS

Severity = Literal["critical", "warning", "info"]


@dataclass(frozen=True)
class Warning_:
    """One problem, and what to do about it.

    ``action`` is deliberately a command or a concrete setting rather than advice.
    "Consider rotating your secrets" is what a warning nobody acts on looks like.
    """

    code: str
    severity: Severity
    title: str
    detail: str
    action: str
    docs: str | None = None
    #: Values the dashboard substitutes into its own translation of this warning.
    #: Only needed where the wording contains one; see ``development_environment``.
    params: dict[str, str] | None = None

    def as_dict(self) -> dict:
        return asdict(self)


# SHA-256 of password hashes that have appeared in a published source. Currently
# one: the owner account `infra/db/init.sql` seeded, whose bcrypt hash was
# committed alongside it.
PUBLISHED_PASSWORD_HASH_DIGESTS = frozenset(
    {"1257daee61c92c846afec43374e371718940e6416fed96047054726e39188be6"}
)

_GENERATE = 'python -c "import secrets; print(secrets.token_urlsafe(48))"'


def password_hash_is_published(password_hash: str | None) -> bool:
    """Whether this stored hash is one that has appeared in a published source."""
    if not password_hash:
        return False
    digest = hashlib.sha256(password_hash.encode("utf-8")).hexdigest()
    return digest in PUBLISHED_PASSWORD_HASH_DIGESTS


def account_warnings(*, password_hash: str | None) -> list[Warning_]:
    """Warnings about the calling user's own credentials."""
    if not password_hash_is_published(password_hash):
        return []
    return [
        Warning_(
            code="password_published",
            severity="critical",
            title="This password is publicly known",
            detail=(
                "The hash of this password appeared in a published source — it "
                "was the development account earlier versions of this project "
                "shipped. bcrypt delays an attack, it does not prevent one: "
                "whoever holds the hash can try passwords offline for as long "
                "as they like."
            ),
            action="Change the password now — and anywhere else it is used.",
            docs="/docs/features/authentication.html#how-password_published-knows-what-is-public",
        )
    ]


def deployment_warnings(
    *,
    environment: str,
    jwt_secret: str,
    encryption_key: str,
    internal_secret: str,
    allow_registration: bool,
    cookie_secure: bool,
) -> list[Warning_]:
    """Warnings about how this installation is configured.

    Owner and administrator only: naming which secret is a published default is
    itself a small disclosure.
    """
    warnings: list[Warning_] = []
    is_dev = environment.strip().lower() not in {"production", "prod", "staging"}

    # The three secrets. Core and the Gateway already refuse to *start* on these
    # in production, so reaching this code means either a development
    # environment or an installation that has declared itself not to be
    # production while serving real data — which is worth saying out loud.
    if not jwt_secret or jwt_secret in PUBLISHED_DEFAULTS:
        warnings.append(
            Warning_(
                code="insecure_jwt_secret",
                severity="critical",
                title="JWT_SECRET is a published default",
                detail=(
                    "Sessions are signed with a key that is printed in this "
                    "project's own source. Anyone who knows it can issue a "
                    "token for any account and any workspace."
                ),
                action=f"Set a value of your own: {_GENERATE}",
                docs="/docs/operations.html#required-configuration",
            )
        )

    if not encryption_key or encryption_key in PUBLISHED_DEFAULTS:
        warnings.append(
            Warning_(
                code="insecure_encryption_key",
                severity="critical",
                title="ENCRYPTION_KEY is a published default",
                detail=(
                    "Every stored connector credential can be decrypted by "
                    "anyone who knows this key — and it is in the source."
                ),
                action=(
                    "Re-encrypt first, then switch: "
                    "python -m core.rotate_encryption_key --old … --new … "
                    "Changing it without that step makes every stored token "
                    "permanently unreadable."
                ),
                docs="/docs/operations.html#rotating-encryption_key",
            )
        )

    # Empty is legitimate: core.security.tokens derives a value from JWT_SECRET,
    # and that derivation is only as weak as JWT_SECRET, which is covered above.
    if internal_secret in PUBLISHED_DEFAULTS:
        warnings.append(
            Warning_(
                code="insecure_internal_secret",
                severity="critical",
                title="INTERNAL_SERVICE_SECRET is a published default",
                detail=(
                    "With it, anyone can present themselves as an internal "
                    "service and fetch decrypted connector credentials."
                ),
                action=f"Set a value of your own: {_GENERATE}",
                docs="/docs/operations.html#required-configuration",
            )
        )

    if allow_registration:
        warnings.append(
            Warning_(
                code="registration_open",
                severity="warning",
                title="Self-service sign-up is open",
                detail=(
                    "Anyone who knows this address can create an account and "
                    "a workspace of their own."
                ),
                action=(
                    "Set ALLOW_REGISTRATION=false. The first account is "
                    "created with python -m core.create_owner."
                ),
                docs="/docs/operations.html#creating-the-first-account",
            )
        )

    if not cookie_secure:
        warnings.append(
            Warning_(
                code="cookies_not_secure",
                severity="warning",
                title="Session cookies without the Secure flag",
                detail=(
                    "The cookies are sent over unencrypted connections too, "
                    "where anyone on the path can read them."
                ),
                action=(
                    "Set COOKIE_SECURE=true. Harmless for local development: "
                    "browsers treat localhost and 127.0.0.1 as trustworthy "
                    "and accept Secure cookies there."
                ),
                docs="/docs/features/authentication.html#sessions-lifetimes-and-renewal",
            )
        )

    # Said last so it reads as context for the entries above rather than as a
    # problem of its own.
    if is_dev and warnings:
        warnings.append(
            Warning_(
                code="development_environment",
                severity="info",
                title=f"ENVIRONMENT is “{environment}”",
                detail=(
                    "That is why the services start despite the points above. "
                    "With a production-like ENVIRONMENT, Core and the Gateway "
                    "refuse to start while any value is a published default."
                ),
                action="Set ENVIRONMENT=production for a real deployment.",
                docs="/docs/operations.html#required-configuration",
                params={"environment": environment},
            )
        )

    return warnings
