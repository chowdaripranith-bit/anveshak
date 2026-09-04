import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.services.theft.state_machine import TheftState, TheftStateMachine
from app.services.theft.zone import RackZone
from app.services.tracking.person_tracker import TrackedPerson

logger = logging.getLogger(__name__)


@dataclass
class PotentialTheftEvent:
    """Represents a validated potential theft security event."""

    track_id: int
    rack_zone_id: str
    rack_zone_name: str
    timestamp: str
    interaction_duration: float
    states_traversed: List[str]
    movement_history: List[Tuple[float, float, float]]
    confidence: float
    details: str
    snapshot_path: Optional[str] = None


class TheftDetector:
    """Orchestrates rack zones and per-person theft state machines.

    Evaluates tracking data to identify suspicious retail interaction sequences.
    Concealment detection is explicitly partitioned as a modular hook:
    [NOT YET IMPLEMENTED / REQUIRES SPECIALIZED MODEL]
    """

    def __init__(
        self,
        rack_zone: Optional[RackZone] = None,
        min_interaction_seconds: Optional[float] = None,
        proximity_margin: Optional[float] = None,
        theft_cooldown_seconds: Optional[float] = None,
        concealment_enabled: Optional[bool] = None,
    ):
        self.rack_zone = rack_zone or RackZone(
            id=settings.RACK_ZONE_ID,
            name=settings.RACK_ZONE_NAME,
            x1=settings.RACK_ZONE_X1,
            y1=settings.RACK_ZONE_Y1,
            x2=settings.RACK_ZONE_X2,
            y2=settings.RACK_ZONE_Y2,
        )
        self.min_interaction_seconds = (
            min_interaction_seconds
            if min_interaction_seconds is not None
            else settings.THEFT_MIN_INTERACTION_SECONDS
        )
        self.proximity_margin = (
            proximity_margin
            if proximity_margin is not None
            else settings.THEFT_PROXIMITY_MARGIN
        )
        self.theft_cooldown_seconds = (
            theft_cooldown_seconds
            if theft_cooldown_seconds is not None
            else settings.THEFT_COOLDOWN_SECONDS
        )
        self.concealment_enabled = (
            concealment_enabled
            if concealment_enabled is not None
            else settings.THEFT_CONCEALMENT_CHECK_ENABLED
        )

        self.state_machines: Dict[int, TheftStateMachine] = {}

    def _get_or_create_sm(self, track_id: int) -> TheftStateMachine:
        if track_id not in self.state_machines:
            self.state_machines[track_id] = TheftStateMachine(
                track_id=track_id,
                zone=self.rack_zone,
                min_interaction_seconds=self.min_interaction_seconds,
                proximity_margin=self.proximity_margin,
                theft_cooldown_seconds=self.theft_cooldown_seconds,
                concealment_enabled=self.concealment_enabled,
            )
        return self.state_machines[track_id]

    def _check_concealment_vision_model(
        self, person: TrackedPerson, frame: Optional[Any] = None
    ) -> Tuple[bool, str]:
        """Hook for future specialized pocket/bag concealment model.

        STATUS: NOT YET IMPLEMENTED / REQUIRES SPECIALIZED MODEL.
        Standard YOLOv8n object detection cannot reliably verify an item
        entering pockets or bags without temporal action recognition.
        """
        # Architectural placeholder for action-recognition / fine-tuned concealment model
        return False, "NOT YET IMPLEMENTED / REQUIRES SPECIALIZED MODEL"

    def evaluate_tracks(
        self,
        tracks: List[TrackedPerson],
        timestamp: Optional[float] = None,
        cues_by_track: Optional[Dict[int, Dict[str, Any]]] = None,
        frame: Optional[Any] = None,
    ) -> List[PotentialTheftEvent]:
        """Evaluate active tracked persons against the rack zone and state machines.

        Parameters
        ----------
        tracks : List[TrackedPerson]
            Currently active tracks in the frame.
        timestamp : float, optional
            Timestamp in seconds.
        cues_by_track : dict, optional
            Manual or vision-detected behavioral cues (e.g. {"item_taken": True, "concealment": True}).
        frame : Any, optional
            Current camera frame array for vision models.

        Returns
        -------
        List[PotentialTheftEvent]
            Any potential theft events triggered during this frame evaluation.
        """
        now = time.time() if timestamp is None else float(timestamp)
        cues = cues_by_track or {}
        events: List[PotentialTheftEvent] = []

        active_track_ids = {t.track_id for t in tracks}

        # Prune state machines for tracks that have been dead/inactive for over 60 seconds
        dead_ids = [
            tid for tid in self.state_machines
            if tid not in active_track_ids
            and (now - self.state_machines[tid].last_state_change_time) > 60.0
        ]
        for did in dead_ids:
            del self.state_machines[did]

        for person in tracks:
            sm = self._get_or_create_sm(person.track_id)
            track_cues = cues.get(person.track_id, {})

            item_taken_cue = bool(track_cues.get("item_taken", False))
            concealment_cue = bool(track_cues.get("concealment", False))
            concealment_detail = track_cues.get("concealment_detail", "")

            # If no manual cue provided, query the vision model hook
            if not concealment_cue:
                model_detected, model_detail = self._check_concealment_vision_model(person, frame)
                if model_detected:
                    concealment_cue = True
                    concealment_detail = model_detail

            current_state, is_theft = sm.update(
                person=person,
                timestamp=now,
                item_taken_cue=item_taken_cue,
                concealment_cue=concealment_cue,
                concealment_evidence_detail=concealment_detail,
            )

            if is_theft:
                history_states = [entry["state"] for entry in sm.get_history_summary()]
                event = PotentialTheftEvent(
                    track_id=person.track_id,
                    rack_zone_id=self.rack_zone.id,
                    rack_zone_name=self.rack_zone.name,
                    timestamp=datetime.utcfromtimestamp(now).isoformat(),
                    interaction_duration=sm.interaction_duration,
                    states_traversed=history_states,
                    movement_history=list(person.movement_history),
                    confidence=person.confidence,
                    details=(
                        f"Potential theft sequence detected for Person #{person.track_id} "
                        f"at rack zone '{self.rack_zone.name}'. Sequence: {' -> '.join(history_states[-4:])}."
                    ),
                )
                logger.warning(
                    "[THEFT DETECTOR] POTENTIAL THEFT EVENT EMITTED: Person #%d at %s",
                    person.track_id,
                    self.rack_zone.name,
                )
                events.append(event)

        return events
