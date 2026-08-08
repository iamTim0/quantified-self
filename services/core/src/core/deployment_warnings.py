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
            title="Dieses Passwort ist öffentlich bekannt",
            detail=(
                "Der Hash dieses Passworts stand in einer veröffentlichten Quelle "
                "— es war der Entwicklungs-Zugang, den frühere Versionen dieses "
                "Projekts mitgeliefert haben. bcrypt verzögert einen Angriff, es "
                "verhindert ihn nicht. Wer den Hash hat, kann das Passwort offline "
                "durchprobieren, so lange er möchte."
            ),
            action=(
                "Passwort jetzt ändern — und falls es anderswo verwendet wird, "
                "dort ebenfalls."
            ),
            docs="/docs/features/authentication/",
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
                title="JWT_SECRET ist ein veröffentlichter Standardwert",
                detail=(
                    "Sitzungen werden mit einem Schlüssel signiert, der im "
                    "Quellcode dieses Projekts steht. Wer ihn kennt, kann sich "
                    "ein Token für jedes Konto und jeden Arbeitsbereich "
                    "ausstellen."
                ),
                action=f"Einen eigenen Wert setzen: {_GENERATE}",
                docs="/docs/operations/#erforderliche-konfiguration",
            )
        )

    if not encryption_key or encryption_key in PUBLISHED_DEFAULTS:
        warnings.append(
            Warning_(
                code="insecure_encryption_key",
                severity="critical",
                title="ENCRYPTION_KEY ist ein veröffentlichter Standardwert",
                detail=(
                    "Die hinterlegten Connector-Zugangsdaten sind damit für "
                    "jeden entschlüsselbar, der diesen Schlüssel kennt — und er "
                    "steht im Quellcode."
                ),
                action=(
                    "Erst umschlüsseln, dann umstellen: "
                    "python -m core.rotate_encryption_key --old … --new … "
                    "Ein Wechsel ohne diesen Schritt macht alle gespeicherten "
                    "Tokens dauerhaft unlesbar."
                ),
                docs="/docs/operations/#encryption_key-wechseln",
            )
        )

    # Empty is legitimate: core.security.tokens derives a value from JWT_SECRET,
    # and that derivation is only as weak as JWT_SECRET, which is covered above.
    if internal_secret in PUBLISHED_DEFAULTS:
        warnings.append(
            Warning_(
                code="insecure_internal_secret",
                severity="critical",
                title="INTERNAL_SERVICE_SECRET ist ein veröffentlichter Standardwert",
                detail=(
                    "Damit kann sich jeder als interner Dienst ausweisen und "
                    "entschlüsselte Connector-Zugangsdaten abrufen."
                ),
                action=f"Einen eigenen Wert setzen: {_GENERATE}",
                docs="/docs/operations/#erforderliche-konfiguration",
            )
        )

    if allow_registration:
        warnings.append(
            Warning_(
                code="registration_open",
                severity="warning",
                title="Selbstregistrierung ist offen",
                detail=(
                    "Jede Person, die diese Adresse kennt, kann sich ein Konto "
                    "und einen eigenen Arbeitsbereich anlegen."
                ),
                action=(
                    "ALLOW_REGISTRATION=false setzen. Das erste Konto legt "
                    "python -m core.create_owner an."
                ),
                docs="/docs/operations/#das-erste-konto-anlegen",
            )
        )

    if not cookie_secure:
        warnings.append(
            Warning_(
                code="cookies_not_secure",
                severity="warning",
                title="Sitzungs-Cookies ohne Secure-Flag",
                detail=(
                    "Die Cookies werden auch über unverschlüsselte Verbindungen "
                    "gesendet und sind dort mitlesbar."
                ),
                action=(
                    "COOKIE_SECURE=true setzen. Für lokale Entwicklung ist das "
                    "unproblematisch: Browser behandeln localhost und 127.0.0.1 "
                    "als vertrauenswürdig und akzeptieren Secure-Cookies dort."
                ),
                docs="/docs/features/authentication/",
            )
        )

    # Said last so it reads as context for the entries above rather than as a
    # problem of its own.
    if is_dev and warnings:
        warnings.append(
            Warning_(
                code="development_environment",
                severity="info",
                title=f"ENVIRONMENT ist „{environment}“",
                detail=(
                    "Deshalb starten die Dienste trotz der obigen Punkte. Mit "
                    "einem produktiven ENVIRONMENT verweigern Core und Gateway "
                    "den Start, solange ein Wert ein veröffentlichter Standard "
                    "ist."
                ),
                action="Für ein echtes Deployment ENVIRONMENT=production setzen.",
                docs="/docs/operations/#erforderliche-konfiguration",
            )
        )

    return warnings
