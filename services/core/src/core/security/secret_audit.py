"""Refuse to run in production on the secrets that are printed in this repository.

Every default here is in git, in `.env.example`, and in both compose files. That
is fine for `docker compose up` on a laptop and fatal anywhere else, and the gap
between the two was one unset environment variable: the deployment compose file
read ``${JWT_SECRET:-dev-secret-key-quantified-self-2026}``, so forgetting to set
it did not fail — it silently signed real sessions with a value anyone can read
here.

Two layers now close that. The compose file uses ``${VAR:?message}``, so an unset
variable stops the deploy before a container starts. This module is the second
layer, for every other way a process gets launched: it refuses to start when
``ENVIRONMENT`` is production-like and any secret is still a published default,
and warns loudly otherwise so a developer can see what is not real yet.

Note the ordering trap on ``ENCRYPTION_KEY``: it decrypts stored connector
credentials, so setting a new one without re-encrypting first makes every stored
token unreadable. ``python -m core.rotate_encryption_key`` exists for that, and
the error message below points at it.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Values that appear in this repository. Anything matching one of these is public
# knowledge, whatever variable it arrives in.
PUBLISHED_DEFAULTS: frozenset[str] = frozenset(
    {
        "dev-secret-key-quantified-self-2026",
        "dev-secret-shared-encryption-key-qs-2026",
        "dev-encryption-key-quantified-self-2026",
        # The development stack sets this explicitly on Core and on every importer.
        # It has to be one shared literal rather than something derived: Core derives
        # its fallback from the configured JWT_SECRET, while the importers derive
        # theirs from a hardcoded copy of the *default* JWT_SECRET, so the two agreed
        # only until somebody set a JWT_SECRET of their own -- after which every
        # credential fetch was rejected and the importers sat idle with nothing said.
        # Declared here so `insecure_internal_secret` still fires on it.
        "dev-internal-service-secret-quantified-self-2026",
    }
)

# ENVIRONMENT values that mean "this is not somebody's laptop".
PRODUCTION_ENVIRONMENTS: frozenset[str] = frozenset({"production", "prod", "staging"})

_GENERATE = 'python -c "import secrets; print(secrets.token_urlsafe(48))"'


class InsecureConfiguration(RuntimeError):
    """Raised when a production process is configured with a published secret."""


def _findings(*, jwt_secret: str, encryption_key: str, internal_secret: str) -> list[str]:
    problems: list[str] = []

    if not jwt_secret or jwt_secret in PUBLISHED_DEFAULTS:
        problems.append(
            f"JWT_SECRET is unset or a published default. Generate one with: {_GENERATE}"
        )
    if not encryption_key or encryption_key in PUBLISHED_DEFAULTS:
        problems.append(
            "ENCRYPTION_KEY is unset or a published default. Re-encrypt stored "
            "credentials *before* changing it: python -m core.rotate_encryption_key "
            "--old <current> --new <new>"
        )
    if not internal_secret or internal_secret in PUBLISHED_DEFAULTS:
        problems.append(
            f"INTERNAL_SERVICE_SECRET is unset or a published default. Generate one with: {_GENERATE}"
        )
    return problems


def audit_secrets(
    *,
    environment: str,
    jwt_secret: str,
    encryption_key: str,
    internal_secret: str,
    service: str,
) -> None:
    """Check the configured secrets; raise in production, warn elsewhere.

    Raises:
        InsecureConfiguration: if ``environment`` is production-like and any
            secret is unset or a value published in this repository.
    """
    problems = _findings(
        jwt_secret=jwt_secret,
        encryption_key=encryption_key,
        internal_secret=internal_secret,
    )
    if not problems:
        return

    if environment.strip().lower() in PRODUCTION_ENVIRONMENTS:
        raise InsecureConfiguration(
            f"{service} refuses to start with published secrets in "
            f"ENVIRONMENT={environment}:\n  - " + "\n  - ".join(problems)
        )

    for problem in problems:
        logger.warning("[%s] insecure default in use: %s", service, problem)
