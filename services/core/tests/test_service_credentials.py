"""Tests for service-scoped internal credentials."""

import pytest
from core.security import tokens


def test_service_token_must_match_declared_identity(monkeypatch):
    """A credential minted for one mesh peer cannot authenticate another peer."""
    monkeypatch.setattr(
        tokens.settings,
        "INTERNAL_SERVICE_SECRETS",
        '{"analysis":"analysis-secret-012345678901234567890123","whoop":"whoop-secret-012345678901234567890123"}',
    )
    token = tokens.jwt.encode(
        {
            "sub": "analysis",
            "iss": tokens.ISSUER,
            "aud": tokens.AUDIENCE_INTERNAL,
            "token_type": tokens.TOKEN_TYPE_SERVICE,
            "iat": tokens.datetime.now(tokens.timezone.utc),
            "exp": tokens.datetime.now(tokens.timezone.utc) + tokens.timedelta(minutes=5),
        },
        "analysis-secret-012345678901234567890123",
        algorithm=tokens.settings.JWT_ALGORITHM,
    )

    assert tokens.verify_service_credential(token, service_name="analysis")["sub"] == "analysis"
    with pytest.raises(tokens.TokenError, match="credential"):
        tokens.verify_service_credential(token, service_name="whoop")


def test_service_identity_is_required_when_dedicated_secrets_are_configured(monkeypatch):
    """A valid dedicated credential is not accepted without its service identity."""
    monkeypatch.setattr(
        tokens.settings,
        "INTERNAL_SERVICE_SECRETS",
        '{"analysis":"analysis-secret-012345678901234567890123"}',
    )
    with pytest.raises(tokens.TokenError, match="identity"):
        tokens.verify_service_credential("analysis-secret-012345678901234567890123")
