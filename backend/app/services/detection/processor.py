import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from app.config import settings
from app.services.featherless import FeatherlessService
from app.websocket.alerts import manager as ws_manager

logger = logging.getLogger(__name__)

# Keywords identifying security-sensitive or suspicious events
SECURITY_EVENT_KEYWORDS = {
    "weapon",
    "weapon_detected",
    "weapons",
    "theft",
    "potential_theft",
    "suspicious",
    "suspicious_activity",
    "loitering",
    "prolonged_presence",
    "restricted_area_entry",
    "abnormal_movement",
    "unauthorized",
    "unauthorized_entry",
    "intrusion",
    "break_in",
    "assault",
    "fight",
    "danger",
    "critical",
}

SECURITY_OBJECT_KEYWORDS = {
    "knife",
    "gun",
    "pistol",
    "rifle",
    "weapon",
    "firearm",
    "blade",
    "crowbar",
    "scissors",
    "mask",
    "lockpick",
    "person_theft_behavior",
}


def is_security_event(
    incident_type: Optional[str] = None,
    detected_object: Optional[str] = None,
    confidence: Optional[float] = None,
    threat_level: Optional[str] = None,
) -> bool:
    """Determine whether a detection is a security-related / suspicious event.
    
    Routine detections (e.g. normal person detections without suspicious flags)
    are NOT sent to AI. Only suspicious/security-related events are analyzed.
    """
    if threat_level and threat_level.upper() in {"HIGH", "CRITICAL"}:
        return True

    inc_lower = (incident_type or "").lower().replace("-", "_").strip()
    for kw in SECURITY_EVENT_KEYWORDS:
        if kw in inc_lower:
            return True

    obj_lower = (detected_object or "").lower().replace("-", "_").strip()
    for kw in SECURITY_OBJECT_KEYWORDS:
        if kw in obj_lower:
            return True

    return False


class DetectionProcessor:
    """Processes computer-vision detection events and connects security-sensitive
    events to Featherless AI for incident analysis and alert dispatch.
    """

    def __init__(self, featherless_service: Optional[FeatherlessService] = None):
        self.ai_service = featherless_service or FeatherlessService()

    async def process_event(
        self,
        detected_object: str,
        confidence: float,
        incident_type: str,
        camera_id: Optional[int] = 1,
        timestamp: Optional[Union[datetime, str]] = None,
        other_info: Optional[Dict[str, Any]] = None,
        db: Optional[Any] = None,
        broadcast_alert: bool = True,
    ) -> Dict[str, Any]:
        """Process a detected event. If security-sensitive, calls Featherless AI
        and dispatches to the alert system.
        """
        ts_str = (
            timestamp.isoformat()
            if isinstance(timestamp, datetime)
            else (timestamp or datetime.utcnow().isoformat())
        )

        event_payload = {
            "camera_id": camera_id or 1,
            "detected_object": detected_object,
            "confidence": float(confidence),
            "incident_type": incident_type,
            "timestamp": ts_str,
            "other_info": other_info or {},
        }

        # Check if this detection requires AI security analysis
        security_flag = is_security_event(
            incident_type=incident_type,
            detected_object=detected_object,
            confidence=confidence,
        )

        ai_analysis: Optional[Dict[str, Any]] = None
        alert_payload: Optional[Dict[str, Any]] = None

        if security_flag:
            logger.info(
                "Security event detected (%s: %s, conf: %.2f). Sending to Featherless AI.",
                incident_type,
                detected_object,
                confidence,
            )

            # Featherless AI analysis with safe error handling
            try:
                ai_analysis = await asyncio.to_thread(
                    self.ai_service.analyze_incident,
                    detected_object=detected_object,
                    confidence=confidence,
                    incident_type=incident_type,
                    timestamp=ts_str,
                    other_info={
                        "camera_id": camera_id,
                        **(other_info or {}),
                    },
                )
            except Exception as e:
                logger.error("Featherless analysis error (fallback used): %s", str(e))
                ai_analysis = {
                    "status": "fallback",
                    "incident_classification": incident_type.upper(),
                    "severity": "HIGH",
                    "short_explanation": f"Security detection of {detected_object} (confidence: {confidence:.2f}).",
                    "recommended_action": "Verify camera feed and alert security staff.",
                    "model": self.ai_service.model,
                }

            # Prepare alert using AI results
            severity = ai_analysis.get("severity", "HIGH")
            classification = ai_analysis.get("incident_classification", incident_type.upper())
            explanation = ai_analysis.get("short_explanation", "")
            action = ai_analysis.get("recommended_action", "")

            alert_message = f"[{severity}] {classification}: {explanation}"
            if action:
                alert_message += f" Action: {action}"

            # Ensure an actual evidence snapshot exists on disk for this confirmed security event
            evidence_path = (other_info or {}).get("evidence_path") or (other_info or {}).get("snapshot")
            if not evidence_path or not os.path.exists(evidence_path):
                from app.workers.camera import camera_manager
                from app.services.detection.camera_worker import _save_snapshot

                # Capture from live camera worker first (the actual current frame)
                frame = camera_manager.capture_current_frame()
                if frame is None:
                    try:
                        import cv2
                        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                        if cap.isOpened():
                            ret, f = cap.read()
                            if ret and f is not None:
                                frame = f
                        cap.release()
                    except Exception:
                        frame = None

                if frame is not None:
                    cam_id = f"cam{int(camera_id):02d}" if isinstance(camera_id, (int, str)) and str(camera_id).isdigit() else str(camera_id or "cam01")
                    obj_clean = detected_object.lower()
                    cat = "weapons" if any(k in obj_clean for k in ("knife", "gun", "pistol", "rifle", "weapon", "firearm", "blade")) else "theft" if "theft" in incident_type else "suspicious"
                    track_id = (other_info or {}).get("track_id")
                    evidence_path = _save_snapshot(
                        frame=frame,
                        label=detected_object,
                        camera_id=cam_id,
                        category=cat,
                        track_id=track_id,
                    )
                    if other_info is None:
                        other_info = {}
                    other_info["evidence_path"] = evidence_path
                    other_info["snapshot"] = evidence_path

            evidence_url = None
            if evidence_path:
                norm = evidence_path.replace("\\", "/")
                fname = os.path.basename(norm)
                if "evidence/" in norm:
                    sub = norm[norm.index("evidence/"):]
                    evidence_url = f"/{sub}"
                else:
                    evidence_url = f"/evidence/{fname}"

            alert_payload = {
                "camera_id": camera_id or 1,
                "threat_level": severity,
                "message": alert_message,
                "timestamp": ts_str,
                "is_read": False,
                "classification": classification,
                "recommended_action": action,
                "incident_type": incident_type,
                "track_id": (other_info or {}).get("track_id"),
                "evidence_path": evidence_path,
                "evidence_url": evidence_url,
                "snapshot": evidence_url or evidence_path,
            }

            # Broadcast alert to real-time WebSocket clients
            if broadcast_alert:
                try:
                    await ws_manager.broadcast({
                        "type": "NEW_ALERT",
                        "data": alert_payload,
                    })
                except Exception as ws_err:
                    logger.error("Failed to broadcast alert via WebSocket: %s", str(ws_err))

        else:
            logger.debug(
                "Routine event (%s: %s). Skipping AI analysis.",
                incident_type,
                detected_object,
            )

        # Database persistence if active DB session provided
        saved_to_db = False
        if db is not None:
            try:
                from app.models.domain import DetectionEvent, Alert

                db_event = DetectionEvent(
                    camera_id=camera_id or 1,
                    event_type=incident_type,
                    object_type=detected_object,
                    confidence=float(confidence),
                    threat_level=ai_analysis.get("severity") if ai_analysis else "LOW",
                    description=alert_payload["message"] if alert_payload else f"Detected {detected_object}",
                    status="ALERT_TRIGGERED" if alert_payload else "LOGGED",
                )
                db.add(db_event)
                await db.commit()
                await db.refresh(db_event)

                if alert_payload:
                    db_alert = Alert(
                        event_id=db_event.id,
                        camera_id=camera_id or 1,
                        threat_level=alert_payload["threat_level"],
                        message=alert_payload["message"],
                        is_read=False,
                    )
                    db.add(db_alert)
                    await db.commit()
                    await db.refresh(db_alert)
                    alert_payload["id"] = db_alert.id
                    alert_payload["event_id"] = db_event.id

                saved_to_db = True
            except Exception as db_err:
                logger.warning("Database persistence skipped or failed (service continues): %s", str(db_err))

        return {
            "status": "success",
            "security_event": security_flag,
            "saved_to_db": saved_to_db,
            "event": event_payload,
            "ai_analysis": ai_analysis,
            "alert": alert_payload,
        }


async def process_detection_event(
    detected_object: str,
    confidence: float,
    incident_type: str,
    camera_id: Optional[int] = 1,
    timestamp: Optional[Union[datetime, str]] = None,
    other_info: Optional[Dict[str, Any]] = None,
    db: Optional[Any] = None,
    broadcast_alert: bool = True,
) -> Dict[str, Any]:
    """Convenience helper to process a detection event through default processor."""
    processor = DetectionProcessor()
    return await processor.process_event(
        detected_object=detected_object,
        confidence=confidence,
        incident_type=incident_type,
        camera_id=camera_id,
        timestamp=timestamp,
        other_info=other_info,
        db=db,
        broadcast_alert=broadcast_alert,
    )
