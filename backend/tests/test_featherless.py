import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_featherless_test_endpoint():
    response = client.get("/api/featherless/test")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "incident_classification" in data
    assert "severity" in data
    assert "short_explanation" in data
    assert "recommended_action" in data
    assert "FEATHERLESS_API_KEY" not in str(data)
