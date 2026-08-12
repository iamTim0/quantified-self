"""Published secrets must stop a production start, not merely be logged about.

Roadmap item 23 sat open for four passes as "a deployment action, not a code
change". That was half right: rotating the values is the operator's job, but
*nothing in the code required it*. The deployment compose file read
``${JWT_SECRET:-dev-secret-key-quantified-self-2026}``, so a deployment that
never set it ran on a secret printed in this repository and said nothing.

Maps to Fizzbee Invariants:
- UnauthenticatedRequestsBlocked
"""

import logging

import pytest
from core.security.secret_audit import (
    PUBLISHED_DEFAULTS,
    InsecureConfiguration,
    audit_secrets,
)

GOOD = "MZ3q7Xk9vJ2wR8tLpN5cQaB1dY6sHfUg"


def audit(**overrides):
    kwargs = {
        "environment": "production",
        "jwt_secret": GOOD,
        "encryption_key": GOOD,
        "internal_secret": GOOD,
        "service": "core",
    }
    kwargs.update(overrides)
    return audit_secrets(**kwargs)


def test_real_secrets_pass():
    audit()  # must not raise


@pytest.mark.parametrize("published", sorted(PUBLISHED_DEFAULTS))
def test_every_published_value_is_refused_wherever_it_appears(published):
    """The check is on the *value*, not on which variable it arrived in.

    Someone pasting the encryption default into JWT_SECRET has still published
    their signing key.
    """
    with pytest.raises(InsecureConfiguration):
        audit(jwt_secret=published)


def test_an_unset_secret_is_refused():
    with pytest.raises(InsecureConfiguration):
        audit(jwt_secret="")


def test_an_unset_internal_secret_is_refused():
    """Empty means it falls back to a derivation from JWT_SECRET.
    However, Importers don't know the JWT_SECRET, so they would derive it from their own
    hardcoded default, causing a mismatch. Therefore, it must be explicitly set.
    """
    with pytest.raises(InsecureConfiguration):
        audit(internal_secret="")


def test_a_published_internal_secret_is_refused():
    with pytest.raises(InsecureConfiguration):
        audit(internal_secret="dev-secret-key-quantified-self-2026")


def test_the_message_names_every_problem_at_once():
    """One deploy, one list. Fixing them one restart at a time is miserable."""
    with pytest.raises(InsecureConfiguration) as exc:
        audit(jwt_secret="", encryption_key="", internal_secret=next(iter(PUBLISHED_DEFAULTS)))
    message = str(exc.value)
    assert "JWT_SECRET" in message
    assert "ENCRYPTION_KEY" in message
    assert "INTERNAL_SERVICE_SECRET" in message


def test_the_encryption_message_points_at_the_rotation_tool():
    """Setting a new ENCRYPTION_KEY without re-encrypting destroys every stored
    credential. An error that says "set this" and stops there would cause that."""
    with pytest.raises(InsecureConfiguration) as exc:
        audit(encryption_key="")
    assert "rotate_encryption_key" in str(exc.value)


@pytest.mark.parametrize("environment", ["production", "PROD", " Staging "])
def test_production_like_environments_refuse(environment):
    with pytest.raises(InsecureConfiguration):
        audit(environment=environment, jwt_secret="")


@pytest.mark.parametrize("environment", ["development", "dev", "test", "local"])
def test_other_environments_warn_and_carry_on(environment, caplog):
    """A laptop and CI must keep working, or the check gets deleted."""
    with caplog.at_level(logging.WARNING):
        audit(environment=environment, jwt_secret="")
    assert any("JWT_SECRET" in record.getMessage() for record in caplog.records)
