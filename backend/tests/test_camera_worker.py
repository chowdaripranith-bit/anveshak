"""
Tests for the camera worker pipeline.

These tests do NOT require a physical camera. They use:
- A synthetic NumPy frame (solid-color image) to simulate camera output.
- Mocked YOLO results to simulate detections.
- Mocked asyncio event-loop to verify coroutine dispatch.
"""

import asyncio
import threading
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import numpy as np
import pytest

# Patch cv2 before importing camera_worker (so tests work without a camera)
import sys

# Minimal cv2 stub if not installed
try:
    import cv2
except ImportError:
    cv2_stub = MagicMock()
    cv2_stub.VideoCapture.return_value.isOpened.return_value = False
    sys.modules["cv2"] = cv2_stub


from app.services.detection.camera_worker import (
    CameraWorker,
    _resolve_camera_source,
    _save_snapshot,
    SECURITY_OBJECTS,
)


# ---------------------------------------------------------------------------
# Unit tests - pure logic
# ---------------------------------------------------------------------------

class TestResolveSource:
    def test_integer_string_returns_int(self):
        assert _resolve_camera_source("0") == 0
        assert _resolve_camera_source("2") == 2

    def test_url_string_returned_as_is(self):
        url = "rtsp://192.168.1.10/stream"
        assert _resolve_camera_source(url) == url

    def test_empty_string_returned_as_is(self):
        assert _resolve_camera_source("") == ""


class TestSecurityObjects:
    def test_known_weapons_in_set(self):
        for weapon in ("knife", "gun", "pistol", "rifle"):
            assert weapon in SECURITY_OBJECTS

    def test_person_not_in_security_objects(self):
        assert "person" not in SECURITY_OBJECTS


# ---------------------------------------------------------------------------
# Integration-style tests using mocked YOLO
# ---------------------------------------------------------------------------

def make_fake_frame(h=480, w=640) -> np.ndarray:
    """Create a synthetic BGR frame for testing."""
    return np.zeros((h, w, 3), dtype=np.uint8)


def make_yolo_result(label: str, confidence: float, cls_id: int = 0):
    """Build a minimal mock that looks like a YOLO Results object."""
    box = MagicMock()
    box.cls = [cls_id]
    box.conf = [confidence]

    result = MagicMock()
    result.boxes = [box]

    return result, {cls_id: label}


class TestCameraWorkerInferDispatch:
    """Test _infer_and_dispatch without a real camera or model."""

    def _make_worker(self):
        loop = asyncio.new_event_loop()
        worker = CameraWorker(camera_id="test_cam", loop=loop)
        return worker, loop

    def test_security_object_dispatches_event(self):
        worker, loop = self._make_worker()

        # Build fake YOLO model
        yolo_result, names = make_yolo_result("knife", 0.92, cls_id=0)
        mock_model = MagicMock()
        mock_model.return_value = [yolo_result]
        mock_model.names = names
        worker._model = mock_model

        dispatched = []

        def fake_dispatch(**kwargs):
            dispatched.append(kwargs)

        worker._dispatch_event = lambda **kw: dispatched.append(kw)

        frame = make_fake_frame()
        with patch("app.services.detection.camera_worker._save_snapshot", return_value="/tmp/snap.jpg"):
            worker._infer_and_dispatch(frame)

        assert len(dispatched) == 1
        assert dispatched[0]["detected_object"] == "knife"
        assert dispatched[0]["incident_type"] == "weapon_detected"
        assert dispatched[0]["confidence"] == pytest.approx(0.92, abs=0.01)

    def test_person_detection_not_dispatched(self):
        worker, loop = self._make_worker()

        yolo_result, names = make_yolo_result("person", 0.85, cls_id=1)
        mock_model = MagicMock()
        mock_model.return_value = [yolo_result]
        mock_model.names = names
        worker._model = mock_model

        dispatched = []
        worker._dispatch_event = lambda **kw: dispatched.append(kw)

        frame = make_fake_frame()
        worker._infer_and_dispatch(frame)

        assert len(dispatched) == 0, "Person-only detections should not be dispatched"

    def test_multiple_detections_only_weapon_dispatched(self):
        worker, loop = self._make_worker()

        box_person = MagicMock()
        box_person.cls = [0]
        box_person.conf = [0.80]

        box_knife = MagicMock()
        box_knife.cls = [1]
        box_knife.conf = [0.75]

        result = MagicMock()
        result.boxes = [box_person, box_knife]

        mock_model = MagicMock()
        mock_model.return_value = [result]
        mock_model.names = {0: "person", 1: "knife"}
        worker._model = mock_model

        dispatched = []
        worker._dispatch_event = lambda **kw: dispatched.append(kw)

        frame = make_fake_frame()
        with patch("app.services.detection.camera_worker._save_snapshot", return_value=None):
            worker._infer_and_dispatch(frame)

        assert len(dispatched) == 1
        assert dispatched[0]["detected_object"] == "knife"


class TestCameraWorkerLifecycle:
    """Test start/stop lifecycle without opening a real camera."""

    def test_start_sets_running(self):
        loop = asyncio.new_event_loop()
        worker = CameraWorker(camera_id="lifecycle_test", loop=loop)

        stop_event_captured = {}

        def fake_run(self_ref=worker):
            stop_event_captured["event"] = self_ref._stop_event
            self_ref._stop_event.wait(timeout=2)

        with patch.object(worker, "_run", fake_run):
            worker.start()
            time.sleep(0.2)
            assert worker.is_running
            worker.stop()
            time.sleep(0.3)
            assert not worker.is_running

    def test_double_start_is_safe(self):
        loop = asyncio.new_event_loop()
        worker = CameraWorker(camera_id="double_start", loop=loop)

        def fake_run():
            worker._stop_event.wait(timeout=3)

        with patch.object(worker, "_run", fake_run):
            worker.start()
            time.sleep(0.1)
            worker.start()  # second call should be a no-op
            time.sleep(0.1)
            assert worker.is_running
            worker.stop()
