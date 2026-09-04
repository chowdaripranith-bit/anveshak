import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from app.config import settings
from app.services.tracking.person_tracker import TrackedPerson

logger = logging.getLogger(__name__)


@dataclass
class SuspiciousActivityEvent:
    """Represents an observable behavioral pattern requiring attention."""

    track_id: int
    activity_type: str  # "LOITERING", "PROLONGED_PRESENCE", "ABNORMAL_MOVEMENT", "RESTRICTED_AREA_ENTRY"
    timestamp: str
    confidence: float
    duration_seconds: float
    details: str


class SuspiciousActivityDetector:
    """Rule-based behavior analysis using observable temporal and spatial patterns.

    Uses neutral, objective classifications (LOITERING, PROLONGED_PRESENCE, etc.)
    and never claims criminal intent.
    """

    def __init__(
        self,
        loitering_threshold_seconds: Optional[float] = None,
        prolonged_presence_seconds: Optional[float] = None,
        cooldown_seconds: float = 30.0,
    ):
        self.loitering_threshold_seconds = (
            loitering_threshold_seconds
            if loitering_threshold_seconds is not None
            else settings.LOITERING_THRESHOLD_SECONDS
        )
        self.prolonged_presence_seconds = (
            prolonged_presence_seconds
            if prolonged_presence_seconds is not None
            else settings.PROLONGED_PRESENCE_SECONDS
        )
        self.cooldown_seconds = cooldown_seconds

        # Map of (track_id, activity_type) -> last_alert_time
        self.last_alerts: Dict[Tuple[int, str], float] = {}

    def _can_alert(self, track_id: int, activity_type: str, now: float) -> bool:
        key = (track_id, activity_type)
        last_time = self.last_alerts.get(key, 0.0)
        return (now - last_time) >= self.cooldown_seconds

    def _record_alert(self, track_id: int, activity_type: str, now: float):
        self.last_alerts[(track_id, activity_type)] = now

    def evaluate_person(
        self,
        person: TrackedPerson,
        timestamp: Optional[float] = None,
    ) -> List[SuspiciousActivityEvent]:
        """Evaluate a tracked person's movement history and dwell time."""
        now = time.time() if timestamp is None else float(timestamp)
        events: List[SuspiciousActivityEvent] = []

        dwell = person.total_dwell_seconds

        # 1. Check for LOITERING (staying within small spatial variance for > threshold)
        if dwell >= self.loitering_threshold_seconds and len(person.movement_history) >= 10:
            recent_points = person.movement_history[-20:]
            xs = [p[0] for p in recent_points]
            ys = [p[1] for p in recent_points]
            spread = max(max(xs) - min(xs), max(ys) - min(ys))

            # If spread is small (confined area)
            if spread < 0.15:  # Normalized coordinates
                if self._can_alert(person.track_id, "LOITERING", now):
                    self._record_alert(person.track_id, "LOITERING", now)
                    events.append(
                        SuspiciousActivityEvent(
                            track_id=person.track_id,
                            activity_type="LOITERING",
                            timestamp=datetime.utcfromtimestamp(now).isoformat(),
                            confidence=person.confidence,
                            duration_seconds=dwell,
                            details=(
                                f"Person #{person.track_id} stationary in designated area "
                                f"for {dwell:.1f}s (spread: {spread:.2f})."
                            ),
                        )
                    )

        # 2. Check for PROLONGED_PRESENCE
        if dwell >= self.prolonged_presence_seconds:
            if self._can_alert(person.track_id, "PROLONGED_PRESENCE", now):
                self._record_alert(person.track_id, "PROLONGED_PRESENCE", now)
                events.append(
                    SuspiciousActivityEvent(
                        track_id=person.track_id,
                        activity_type="PROLONGED_PRESENCE",
                        timestamp=datetime.utcfromtimestamp(now).isoformat(),
                        confidence=person.confidence,
                        duration_seconds=dwell,
                        details=(
                            f"Person #{person.track_id} continuous presence observed "
                            f"for {dwell:.1f}s in monitored view."
                        ),
                    )
                )

        return events
