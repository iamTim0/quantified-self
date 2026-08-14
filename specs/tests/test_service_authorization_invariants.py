"""Executable checks for ``service_authorization.fizz``."""


def authenticate(
    service_name: str,
    presented_secret: str,
    credentials: dict[str, str],
) -> bool:
    """Accept a credential only when it belongs to the declared identity."""
    expected = credentials.get(service_name)
    return expected is not None and expected == presented_secret


def test_service_credential_is_bound_to_identity():
    """Verifies Fizzbee Invariant: CredentialBoundToIdentity."""
    credentials = {
        "qs-analysis-service": "analysis-secret",
        "qs-importer-whoop": "whoop-secret",
    }
    assert authenticate("qs-analysis-service", "analysis-secret", credentials)
    assert authenticate("qs-importer-whoop", "whoop-secret", credentials)


def test_cross_service_credential_is_rejected():
    """Verifies Fizzbee Invariant: CrossServiceCredentialRejected."""
    credentials = {
        "qs-analysis-service": "analysis-secret",
        "qs-importer-whoop": "whoop-secret",
    }
    assert not authenticate("qs-analysis-service", "whoop-secret", credentials)
    assert not authenticate("qs-importer-whoop", "analysis-secret", credentials)
