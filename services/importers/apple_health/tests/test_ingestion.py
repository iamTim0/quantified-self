"""Integration/unit tests for Apple Health Importer FastAPI ingestion service."""

from unittest.mock import patch
from fastapi.testclient import TestClient

from apple_health_importer.main import app

app.state.testing = True
client = TestClient(app)


def test_health_check_endpoint():
    """Verifies GET /health endpoint response."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "qs-importer-apple-health"


@patch("apple_health_importer.main.get_connector_credentials_from_core")
def test_ingest_endpoint(mock_get_creds):
    """Verifies POST /ingest endpoint transforms payload and responds with 200 OK."""
    mock_get_creds.return_value = (None, "apple_health_src_123", {})

    payload = {
        "data": {
            "metrics": [
                {
                    "name": "step_count",
                    "units": "count",
                    "data": [
                        {
                            "qty": 500,
                            "date": "2026-08-03T10:00:00Z",
                        }
                    ],
                }
            ]
        }
    }

    headers = {
        "X-Tenant-ID": "00000000-0000-0000-0000-000000000001",
        "X-Request-ID": "test_req_001",
    }

    response = client.post("/ingest", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["tenant_id"] == "00000000-0000-0000-0000-000000000001"
    assert data["total_transformed"] == 1


@patch("apple_health_importer.main.get_connector_credentials_from_core")
def test_ingest_unauthorized_api_key(mock_get_creds):
    """Verifies 401 Unauthorized when X-Api-Key does not match expected token."""
    mock_get_creds.return_value = ("secret-key-123", "apple_health_src_123", {})

    payload = {"data": {"metrics": []}}
    headers = {
        "X-Tenant-ID": "00000000-0000-0000-0000-000000000001",
        "X-Api-Key": "wrong-key",
    }

    response = client.post("/ingest", json=payload, headers=headers)
    assert response.status_code == 401
    assert "Invalid API Key" in response.json()["detail"]


@patch("apple_health_importer.main.get_connector_credentials_from_core")
def test_ingest_valid_api_key(mock_get_creds):
    """Verifies 200 OK when X-Api-Key matches expected token."""
    mock_get_creds.return_value = ("secret-key-123", "apple_health_src_123", {})

    payload = {"data": {"metrics": []}}
    headers = {
        "X-Tenant-ID": "00000000-0000-0000-0000-000000000001",
        "X-Api-Key": "secret-key-123",
    }

    response = client.post("/ingest", json=payload, headers=headers)
    assert response.status_code == 200
