"""
Camera worker - captures frames from a camera source and runs
YOLO-based object detection. Security-sensitive detections are forwarded
to DetectionProcessor which calls Featherless AI and dispatches alerts.

The worker runs inside a daemon thread so it never blocks the FastAPI
event-loop. Asyncio tasks are submitted back to the running event-loop
via asyncio.run_coroutine_threadsafe().
"""

import asyncio
import logging
import os
import platform
import threading
from datetime import datetime
from typing import Optional, Tuple

import cv2
import numpy as np

from app.config import settings
from app.services.activity.suspicious_detector import SuspiciousActivityDetector
from app.services.theft.theft_detector import TheftDetector
from app.services.threat.weapon_detector import WeaponDetector
from app.services.tracking.person_tracker import PersonTracker

logger = logging.getLogger(__name__)

# Use DirectShow on Windows - MSMF (default) fails with error -1072875772
_CV_BACKEND = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY


SECURITY_OBJECTS = {
    "knife", "gun", "pistol", "rifle", "weapon",
    "firearm", "blade", "crowbar", "scissors",
}

PERSON_LABEL = "person"


def _resolve_camera_source(raw: str):
    try:
        return int(raw)
    except (ValueError, TypeError):
        return raw


def _save_snapshot(
    frame: np.ndarray,
    label: str,
    camera_id: str,
    category: Optional[str] = None,
    track_id: Optional[int] = None,
) -> Optional[str]:
    try:
        cam_str = str(camera_id).lower()
        if cam_str in ("camera_0", "0", "1", "camera0", "cam0", "cam1"):
            cam_str = "cam01"
        elif not cam_str.startswith("cam"):
            cam_str = f"cam_{cam_str}"

        label_clean = label.lower().strip().replace(" ", "_").replace("-", "_")

        if category is None:
            if any(w in label_clean for w in ("knife", "gun", "weapon", "pistol", "rifle", "firearm", "blade")):
                category = "weapons"
            elif "theft" in label_clean:
                category = "theft"
            else:
                category = "suspicious"

        folder = os.path.join(settings.EVIDENCE_FOLDER, category)
        os.makedirs(folder, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        track_part = f"_track_{track_id}" if track_id is not None else ""
        filename = f"{cam_str}_{label_clean}{track_part}_{ts}.jpg"
        path = os.path.join(folder, filename)
        cv2.imwrite(path, frame)
        logger.info("Snapshot saved: %s", path)
        return path
    except Exception as exc:
        logger.warning("Failed to save snapshot: %s", exc)
        return None


class CameraWorker:
    """
    Captures frames from a single camera source and runs YOLO inference
    in a background daemon thread.

    Parameters
    ----------
    camera_id : str
        Human-readable identifier forwarded with every detection event.
    loop : asyncio.AbstractEventLoop
        The running asyncio loop for submitting coroutines from the thread.
    """

    def __init__(
        self,
        camera_id: str = "camera_0",
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self.camera_id = camera_id
        self.loop = loop or asyncio.get_event_loop()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._source = _resolve_camera_source(settings.CAMERA_SOURCE)
        self._frame_skip: int = max(1, settings.CAMERA_FRAME_SKIP)
        self._confidence: float = settings.CAMERA_DETECTION_CONFIDENCE
        self._model = None

        # Thread-safe latest JPEG frame for MJPEG streaming and raw frame for snapshots
        self._latest_frame: Optional[bytes] = None
        self._latest_raw_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()

        # Tracking and behavioral detectors
        self.person_tracker = PersonTracker()
        self.theft_detector = TheftDetector()
        self.suspicious_detector = SuspiciousActivityDetector()
        self.weapon_detector = WeaponDetector()

    def get_latest_raw_frame(self) -> Optional[np.ndarray]:
        """Return a copy of the latest captured BGR video frame."""
        with self._frame_lock:
            if self._latest_raw_frame is not None:
                return self._latest_raw_frame.copy()
            return None

    # Public lifecycle API

    def start(self):
        """Spawn the background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("CameraWorker is already running.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"camera-worker-{self.camera_id}",
        )
        self._thread.start()
        logger.info(
            "CameraWorker started | source=%s | frame_skip=%d | conf=%.2f",
            self._source, self._frame_skip, self._confidence,
        )

    def stop(self):
        """Signal the worker to stop and wait for the thread to finish."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=6)
            self._thread = None
        with self._frame_lock:
            self._latest_frame = None
            self._latest_raw_frame = None
        logger.info("CameraWorker stopped.")

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def get_latest_frame(self) -> Optional[bytes]:
        """Return the most recently captured JPEG frame (thread-safe)."""
        with self._frame_lock:
            return self._latest_frame

    # Private - thread body

    def _load_model(self):
        """Load YOLO model once inside the worker thread."""
        from ultralytics import YOLO  # type: ignore
        model_path = settings.YOLO_MODEL_PATH
        if not os.path.exists(model_path):
            logger.info(
                "YOLO model not found at %s - downloading yolov8n.pt as fallback.",
                model_path,
            )
            model_path = "yolov8n.pt"
        self._model = YOLO(model_path)
        logger.info("YOLO model loaded: %s", model_path)

        # Attempt loading specialized weapon model if available
        self.weapon_detector.load_model()

    def _run(self):
        """Main capture-and-inference loop (runs in daemon thread)."""
        try:
            self._load_model()
        except Exception as exc:
            logger.error("Failed to load YOLO model: %s", exc)
            return

        cap = None
        frame_index = 0
        reconnect_delay = 5

        while not self._stop_event.is_set():
            if cap is None or not cap.isOpened():
                logger.info("Opening camera source: %s (backend=%s)", self._source, "CAP_DSHOW" if _CV_BACKEND == cv2.CAP_DSHOW else "default")
                cap = cv2.VideoCapture(self._source, _CV_BACKEND)
                if not cap.isOpened():
                    logger.warning(
                        "Cannot open camera source %s - retrying in %ds.",
                        self._source, reconnect_delay,
                    )
                    self._stop_event.wait(reconnect_delay)
                    cap = None
                    continue

                # Drain warm-up frames: DirectShow/MSMF on Windows return
                # pure-black frames for the first ~20-40 reads while the
                # image sensor starts up.  Discard them now so the MJPEG
                # stream is never seeded with black data.
                logger.info("Draining camera warm-up frames ...")
                for _ in range(30):
                    cap.read()
                logger.info("Camera warm-up complete.")

            ret, frame = cap.read()
            if not ret or frame is None:
                logger.warning("Lost camera feed - attempting reconnect.")
                cap.release()
                cap = None
                self._stop_event.wait(reconnect_delay)
                continue

            # Skip pure-black warm-up frames (DirectShow/MSMF send black
            # frames for ~0.5-2s while the image sensor initialises).
            # np.mean on a uint8 frame with no light is 0.0.
            frame_mean = float(np.mean(frame))
            is_black = frame_mean < 2.0

            # Always encode and store the latest GOOD frame for MJPEG streaming
            if not is_black:
                try:
                    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                    if ok:
                        with self._frame_lock:
                            self._latest_frame = buf.tobytes()
                            self._latest_raw_frame = frame.copy()
                except Exception:
                    pass

            frame_index += 1
            if frame_index % self._frame_skip != 0:
                continue

            try:
                self._infer_and_dispatch(frame)
            except Exception as exc:
                logger.error("Inference error: %s", exc)

        if cap:
            cap.release()
            cap = None
        with self._frame_lock:
            self._latest_frame = None
            self._latest_raw_frame = None
        logger.info("Camera capture loop exited for source: %s", self._source)

    def _infer_and_dispatch(self, frame: np.ndarray):
        """Run YOLO on a single frame, track people, and dispatch any security events."""
        results = self._model(frame, conf=self._confidence, verbose=False)
        timestamp = datetime.utcnow()
        now_ts = timestamp.timestamp()
        h, w = frame.shape[:2]

        person_detections = []

        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                cls_id = int(box.cls[0])
                confidence = float(box.conf[0])
                label = self._model.names.get(cls_id, str(cls_id)).lower()

                logger.debug(
                    "[%s] Detected: %s (conf=%.2f)", self.camera_id, label, confidence
                )

                if label in SECURITY_OBJECTS:
                    snapshot_path = _save_snapshot(frame, label, self.camera_id, category="weapons")
                    self._dispatch_event(
                        detected_object=label,
                        confidence=confidence,
                        incident_type="weapon_detected",
                        timestamp=timestamp,
                        other_info={
                            "snapshot": snapshot_path,
                            "evidence_path": snapshot_path,
                            "label": label,
                            "yolo_class_id": cls_id,
                        },
                    )
                elif PERSON_LABEL in label:
                    xyxy = box.xyxy[0].tolist()
                    norm_bbox = (
                        max(0.0, float(xyxy[0]) / w),
                        max(0.0, float(xyxy[1]) / h),
                        min(1.0, float(xyxy[2]) / w),
                        min(1.0, float(xyxy[3]) / h),
                    )
                    person_detections.append((norm_bbox[0], norm_bbox[1], norm_bbox[2], norm_bbox[3], confidence))

        # Check specialized weapon detector if active
        if self.weapon_detector.is_loaded:
            extra_weapons = self.weapon_detector.detect_weapons(frame)
            for w_det in extra_weapons:
                snapshot_path = _save_snapshot(frame, w_det.label, self.camera_id, category="weapons")
                self._dispatch_event(
                    detected_object=w_det.label,
                    confidence=w_det.confidence,
                    incident_type="weapon_detected",
                    timestamp=timestamp,
                    other_info={
                        "snapshot": snapshot_path,
                        "evidence_path": snapshot_path,
                        "label": w_det.label,
                        "yolo_class_id": w_det.class_id,
                    },
                )

        # 1. Update Person Tracker
        active_tracks = self.person_tracker.update(person_detections, timestamp=now_ts)

        # 2. Evaluate Shopping / Theft State Machine
        theft_events = self.theft_detector.evaluate_tracks(
            active_tracks,
            timestamp=now_ts,
            frame=frame,
        )
        for theft_event in theft_events:
            snapshot_path = _save_snapshot(
                frame,
                "theft",
                self.camera_id,
                category="theft",
                track_id=theft_event.track_id,
            )
            theft_event.snapshot_path = snapshot_path
            self._dispatch_event(
                detected_object="person_theft_behavior",
                confidence=theft_event.confidence,
                incident_type="theft",
                timestamp=timestamp,
                other_info={
                    "snapshot": snapshot_path,
                    "evidence_path": snapshot_path,
                    "track_id": theft_event.track_id,
                    "rack_zone_id": theft_event.rack_zone_id,
                    "rack_zone_name": theft_event.rack_zone_name,
                    "interaction_duration": theft_event.interaction_duration,
                    "states_traversed": theft_event.states_traversed,
                    "movement_history": theft_event.movement_history[-10:] if theft_event.movement_history else [],
                    "details": theft_event.details,
                },
            )

        # 3. Evaluate Suspicious Activity (Loitering / Prolonged Presence)
        for person in active_tracks:
            activity_events = self.suspicious_detector.evaluate_person(person, timestamp=now_ts)
            for act_event in activity_events:
                snapshot_path = _save_snapshot(
                    frame,
                    act_event.activity_type.lower(),
                    self.camera_id,
                    category="suspicious",
                    track_id=act_event.track_id,
                )
                self._dispatch_event(
                    detected_object=act_event.activity_type.lower(),
                    confidence=act_event.confidence,
                    incident_type="suspicious_activity",
                    timestamp=timestamp,
                    other_info={
                        "snapshot": snapshot_path,
                        "evidence_path": snapshot_path,
                        "track_id": act_event.track_id,
                        "activity_type": act_event.activity_type,
                        "duration_seconds": act_event.duration_seconds,
                        "details": act_event.details,
                    },
                )

    def _dispatch_event(
        self,
        detected_object: str,
        confidence: float,
        incident_type: str,
        timestamp: datetime,
        other_info: dict,
    ):
        """Submit the async detection processing coroutine to the event-loop."""
        from app.services.detection.processor import process_detection_event

        coro = process_detection_event(
            detected_object=detected_object,
            confidence=confidence,
            incident_type=incident_type,
            camera_id=None,
            timestamp=timestamp,
            other_info={"camera_id": self.camera_id, **other_info},
            db=None,
            broadcast_alert=True,
        )
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
            future.add_done_callback(self._on_dispatch_done)
        except Exception as exc:
            logger.error("Failed to dispatch detection event: %s", exc)

    @staticmethod
    def _on_dispatch_done(future):
        """Callback when the dispatched coroutine completes."""
        try:
            future.result()
        except Exception as exc:
            logger.error("Detection processing error: %s", exc)
