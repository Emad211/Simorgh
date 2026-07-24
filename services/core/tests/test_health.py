from fastapi.testclient import TestClient

from simorgh_core.app import app


def test_health_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"] == "0.1.0"
    assert payload["environment"] in {"development", "test", "production"}
    assert isinstance(payload["model_gateway_configured"], bool)
