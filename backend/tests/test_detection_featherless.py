import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.detection.processor import DetectionProcessor, is_security_event
from app.services.featherless import FeatherlessService

client = TestClient(app)


def test_is_security_event_filtering():
    """Verify security event filtering logic: routine vs suspicious."""
    # Routine events -> False
    assert is_security_event("human_detected", "person", 0.75) is False
    assert is_security_event("routine_patrol", "chair", 0.90) is False

    # Security events -> True
    assert is_security_event("weapon_detected", "knife", 0.91) is True
    assert is_security_event("suspicious_activity", "person", 0.85) is True
    assert is_security_event("theft", "backpack", 0.88) is True
    assert is_security_event("detection", "gun", 0.95) is True


def test_simulated_security_event_endpoint():
    """Test the harmless simulated event (knife, 0.91, weapon_detected)."""
    payload = {
        "object_detected": "knife",
        "confidence": 0.91,
        "incident_type": "weapon_detected",
        "camera_id": 1,
    }
    response = client.post("/api/events/simulate", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "success"
    assert data["security_event"] is True

    # AI Analysis checks
    ai = data["ai_analysis"]
    assert ai is not None
    assert "incident_classification" in ai
    assert ai["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert "short_explanation" in ai
    assert "recommended_action" in ai

    # Alert checks
    alert = data["alert"]
    assert alert is not None
    assert alert["threat_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert alert["message"] != ""
    assert "FEATHERLESS_API_KEY" not in str(data)


def test_routine_event_not_sent_to_ai():
    """Verify that routine/normal detections are not sent to Featherless AI."""
    payload = {
        "object_detected": "person",
        "confidence": 0.75,
        "incident_type": "human_detected",
        "camera_id": 1,
    }
    response = client.post("/api/events/simulate", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "success"
    assert data["security_event"] is False
    assert data["ai_analysis"] is None
    assert data["alert"] is None


def test_detection_processor_graceful_fallback():
    """Verify that if Featherless AI encounters an error, detection continues working."""
    import asyncio

    bad_service = FeatherlessService(api_key="invalid_dummy_key", timeout=1.0)
    processor = DetectionProcessor(featherless_service=bad_service)

    result = asyncio.run(
        processor.process_event(
            detected_object="knife",
            confidence=0.91,
            incident_type="weapon_detected",
            camera_id=1,
            broadcast_alert=False,
        )
    )

    assert result["status"] == "success"
    assert result["security_event"] is True
    assert result["alert"] is not None
    assert "FEATHERLESS_API_KEY" not in str(result)
