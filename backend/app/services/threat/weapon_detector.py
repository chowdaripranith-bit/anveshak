import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings

logger = logging.getLogger(__name__)

THREAT_CLASSES = {
    "knife", "gun", "pistol", "rifle", "firearm", "weapon", "blade",
}

IGNORED_CLASSES = {
    "explosive", "grenade", "explosion", "bomb",
}


@dataclass
class WeaponDetection:
    label: str
    confidence: float
    bbox: Tuple[float, float, float, float]
    class_id: int


class WeaponDetector:
    """Specialized threat and weapon detector.

    Supports custom threat models (e.g. Subh775/Threat-Detection-YOLOv8n)
    while cleanly falling back to primary YOLO classes (knife, etc.)
    if the external weights are not yet present locally.
    """

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or settings.WEAPON_MODEL_PATH
        self._model = None
        self._is_loaded = False

    def load_model(self):
        """Attempt to load specialized weapon weights if available."""
        if self._is_loaded:
            return

        if os.path.exists(self.model_path):
            try:
                from ultralytics import YOLO
                self._model = YOLO(self.model_path)
                self._is_loaded = True
                logger.info("Specialized weapon model loaded: %s", self.model_path)
            except Exception as exc:
                logger.warning("Could not load weapon model (%s): %s", self.model_path, exc)
                self._model = None
        else:
            logger.info(
                "Specialized weapon model not found at %s. Relying on primary YOLO threat classes.",
                self.model_path,
            )

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded and self._model is not None

    def detect_weapons(self, frame: Any, confidence_threshold: Optional[float] = None) -> List[WeaponDetection]:
        """Run weapon inference on frame if specialized model is loaded."""
        if not self.is_loaded:
            return []

        conf = confidence_threshold if confidence_threshold is not None else settings.WEAPON_CONFIDENCE_THRESHOLD
        results = self._model(frame, conf=conf, verbose=False)
        detections: List[WeaponDetection] = []

        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                cls_id = int(box.cls[0])
                c = float(box.conf[0])
                label = self._model.names.get(cls_id, str(cls_id)).lower()

                # Explicitly ignore grenade and explosive detections
                if any(ign in label for ign in IGNORED_CLASSES):
                    continue

                if label in THREAT_CLASSES or any(kw in label for kw in ("gun", "knife", "pistol", "rifle", "firearm", "blade")):
                    xyxy = box.xyxy[0].tolist()
                    detections.append(
                        WeaponDetection(
                            label=label,
                            confidence=c,
                            bbox=(float(xyxy[0]), float(xyxy[1]), float(xyxy[2]), float(xyxy[3])),
                            class_id=cls_id,
                        )
                    )

        return detections
