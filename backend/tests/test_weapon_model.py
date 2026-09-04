import os
import cv2
import numpy as np
import pytest
from app.config import settings
from app.services.threat.weapon_detector import WeaponDetector


def test_weapon_model_file_exists():
    assert os.path.exists("models/weapons/weapon_model.pt")
    size = os.path.getsize("models/weapons/weapon_model.pt")
    assert size > 5_000_000  # ~6.2MB


def test_weapon_detector_loads_classes():
    detector = WeaponDetector(model_path="models/weapons/weapon_model.pt")
    detector.load_model()
    assert detector.is_loaded is True

    # Check model classes contain Gun, knife, grenade, explosion
    classes = detector._model.names
    names_lower = [name.lower() for name in classes.values()]
    assert "gun" in names_lower
    assert "knife" in names_lower
    assert "grenade" in names_lower


def test_weapon_detector_inference_on_synthetic_frame():
    detector = WeaponDetector(model_path="models/weapons/weapon_model.pt")
    detector.load_model()

    # Blank frame should produce 0 false positives
    blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    results = detector.detect_weapons(blank_frame, confidence_threshold=0.5)
    assert len(results) == 0


def test_weapon_detector_inference_on_threat_image():
    if os.path.exists("test_threat_sample.png"):
        img = cv2.imread("test_threat_sample.png")
        detector = WeaponDetector(model_path="models/weapons/weapon_model.pt")
        detector.load_model()
        detections = detector.detect_weapons(img, confidence_threshold=0.3)
        assert len(detections) > 0
        labels = [d.label.lower() for d in detections]
        assert "gun" in labels
        assert "grenade" not in labels
        assert "explosive" not in labels
