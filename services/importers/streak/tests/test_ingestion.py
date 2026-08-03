"""Integration/unit tests for Streak Importer FastAPI server."""

from unittest.mock import patch
from fastapi.testclient import TestClient

from streak_importer.main import app

app.state.testing = True
client = TestClient(app)


def test_health_check_endpoint():
    """Verifies GET /health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "qs-importer-streak"


def test_head_and_get_ingest_server_checks():
    """Verifies HEAD and GET server check endpoints used by Streak 2.0 app."""
    head_res = client.head("/ingest")
    assert head_res.status_code == 200

    get_res = client.get("/ingest")
    assert get_res.status_code == 200
    assert get_res.json()["ok"] is True


@patch("streak_importer.main.get_connector_credentials_from_core")
def test_post_ingest_endpoint(mock_get_creds):
    """Verifies POST /ingest exports workouts and returns Streak 2.0 compatible response."""
    mock_get_creds.return_value = (None, "streak_src_123", {})

    payload = {
        "workouts": [
            {
                "id": 1,
                "title": "Push",
                "createdAt": "2026-08-03T18:00:00Z",
                "sets": [
                    {
                        "id": 101,
                        "weight": 60.0,
                        "reps": 12,
                        "createdAt": "2026-08-03T18:05:00Z",
                    }
                ],
            }
        ]
    }

    headers = {
        "X-Tenant-ID": "00000000-0000-0000-0000-000000000001",
    }

    response = client.post("/ingest", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["workoutCount"] == 1
    assert data["published_count"] > 0


@patch("streak_importer.main.get_connector_credentials_from_core")
def test_post_ingest_unauthorized_api_key(mock_get_creds):
    """Verifies 401 Unauthorized when invalid X-Api-Key is provided."""
    mock_get_creds.return_value = ("secret-streak-key", "streak_src_123", {})

    payload = {"workouts": []}
    headers = {
        "X-Tenant-ID": "00000000-0000-0000-0000-000000000001",
        "X-Api-Key": "wrong-key",
    }

    response = client.post("/ingest", json=payload, headers=headers)
    assert response.status_code == 401
