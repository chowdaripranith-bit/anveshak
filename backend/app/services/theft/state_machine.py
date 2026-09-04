import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.services.theft.zone import RackZone
from app.services.tracking.person_tracker import TrackedPerson

logger = logging.getLogger(__name__)


class TheftState(str, enum.Enum):
    NORMAL = "NORMAL"
    NEAR_RACK = "NEAR_RACK"
    INTERACTING_WITH_RACK = "INTERACTING_WITH_RACK"
    ITEM_TAKEN = "ITEM_TAKEN"
    POSSIBLE_CONCEALMENT = "POSSIBLE_CONCEALMENT"
    LEFT_RACK = "LEFT_RACK"
    POTENTIAL_THEFT = "POTENTIAL_THEFT"


@dataclass
class StateHistoryEntry:
    state: TheftState
    timestamp: float
    details: str


class TheftStateMachine:
    """Tracks shopping behavior state for a single person track ID relative to a RackZone.

    Adheres strictly to the rule that normal shopping (standing, inspecting items,
    moving away without concealment) must NEVER trigger a theft alert.
    """

    def __init__(
        self,
        track_id: int,
        zone: RackZone,
        min_interaction_seconds: float = 2.0,
        proximity_margin: float = 0.05,
        theft_cooldown_seconds: float = 15.0,
        concealment_enabled: bool = True,
    ):
        self.track_id = track_id
        self.zone = zone
        self.min_interaction_seconds = min_interaction_seconds
        self.proximity_margin = proximity_margin
        self.theft_cooldown_seconds = theft_cooldown_seconds
        self.concealment_enabled = concealment_enabled

        self.current_state: TheftState = TheftState.NORMAL
        self.interaction_start_time: Optional[float] = None
        self.last_state_change_time: float = time.time()
        self.last_theft_alert_time: float = 0.0

        # Behavioral flags
        self.item_taken_observed: bool = False
        self.concealment_observed: bool = False
        self.concealment_note: str = ""

        # History log
        self.history: List[StateHistoryEntry] = [
            StateHistoryEntry(TheftState.NORMAL, time.time(), "Initialized in NORMAL state")
        ]

    def _transition_to(self, new_state: TheftState, timestamp: float, details: str):
        if self.current_state != new_state:
            logger.info(
                "[Person #%d] State transition: %s -> %s (%s)",
                self.track_id,
                self.current_state.value,
                new_state.value,
                details,
            )
            self.current_state = new_state
            self.last_state_change_time = timestamp
            self.history.append(StateHistoryEntry(new_state, timestamp, details))

    def update(
        self,
        person: TrackedPerson,
        timestamp: Optional[float] = None,
        item_taken_cue: bool = False,
        concealment_cue: bool = False,
        concealment_evidence_detail: str = "",
    ) -> Tuple[TheftState, bool]:
        """Update the state machine for this person based on current position and visual cues.

        Parameters
        ----------
        person : TrackedPerson
            Current tracked person instance.
        timestamp : float, optional
            Current frame timestamp in seconds.
        item_taken_cue : bool, optional
            Visual cue indicating an item left the rack zone during this interaction.
        concealment_cue : bool, optional
            Visual or behavioral cue indicating possible concealment into clothing/bag.
        concealment_evidence_detail : str, optional
            Explanation of concealment evidence (e.g. from specialized model).

        Returns
        -------
        Tuple[TheftState, bool]
            (current_state, is_new_potential_theft_event)
        """
        now = time.time() if timestamp is None else float(timestamp)
        is_theft_event = False

        # Calculate normalized centroid of person
        # Note: Bounding boxes are expected in normalized coordinates (0.0 to 1.0).
        # If pixels are passed (e.g. > 1.0), we normalize or clamp safely.
        cx, cy = person.centroid
        is_inside_rack = self.zone.contains_point(cx, cy, margin=0.0)
        is_near_rack = self.zone.contains_point(cx, cy, margin=self.proximity_margin)

        if item_taken_cue:
            self.item_taken_observed = True

        if concealment_cue:
            self.concealment_observed = True
            if concealment_evidence_detail:
                self.concealment_note = concealment_evidence_detail

        # State transition logic
        if self.current_state == TheftState.NORMAL:
            if is_inside_rack:
                self.interaction_start_time = now
                self._transition_to(
                    TheftState.INTERACTING_WITH_RACK,
                    now,
                    f"Person entered rack zone '{self.zone.name}'",
                )
            elif is_near_rack:
                self.interaction_start_time = now
                self._transition_to(
                    TheftState.NEAR_RACK,
                    now,
                    f"Person approached vicinity of rack zone '{self.zone.name}'",
                )

        elif self.current_state == TheftState.NEAR_RACK:
            if is_inside_rack:
                self._transition_to(
                    TheftState.INTERACTING_WITH_RACK,
                    now,
                    f"Person moved into rack zone '{self.zone.name}'",
                )
            elif not is_near_rack:
                # Normal shopper simply walked past
                self._transition_to(
                    TheftState.NORMAL,
                    now,
                    "Person walked away from rack vicinity without interacting (Normal)",
                )
                self.interaction_start_time = None

        if self.current_state == TheftState.INTERACTING_WITH_RACK:
            duration = (now - (self.interaction_start_time or now))
            if self.item_taken_observed:
                self._transition_to(
                    TheftState.ITEM_TAKEN,
                    now,
                    f"Item interaction noted after {duration:.1f}s near rack",
                )
            elif not is_near_rack:
                # Person left the rack without taking/concealing anything -> NORMAL SHOPPING
                self._transition_to(
                    TheftState.NORMAL,
                    now,
                    f"Person browsed rack for {duration:.1f}s and walked away (Normal Shopping)",
                )
                self.interaction_start_time = None

        if self.current_state == TheftState.ITEM_TAKEN:
            if self.concealment_observed and self.concealment_enabled:
                note = self.concealment_note or "Possible concealment movement observed"
                self._transition_to(
                    TheftState.POSSIBLE_CONCEALMENT,
                    now,
                    note,
                )
            elif not is_near_rack:
                # Item was taken but NO concealment observed (e.g. holding in basket/hand normally)
                # This is normal shopping or customer carrying merchandise to checkout
                self._transition_to(
                    TheftState.NORMAL,
                    now,
                    "Person departed with item without concealment (Presumed Normal Customer)",
                )
                self.item_taken_observed = False

        if self.current_state == TheftState.POSSIBLE_CONCEALMENT:
            if not is_near_rack:
                self._transition_to(
                    TheftState.LEFT_RACK,
                    now,
                    "Person moved away from rack area following concealment behavior",
                )
                # Next evaluate potential theft
                if (now - self.last_theft_alert_time) >= self.theft_cooldown_seconds:
                    self._transition_to(
                        TheftState.POTENTIAL_THEFT,
                        now,
                        f"Sequence satisfied: RACK -> ITEM_TAKEN -> CONCEALMENT -> LEFT_RACK",
                    )
                    self.last_theft_alert_time = now
                    is_theft_event = True

        elif self.current_state in (TheftState.LEFT_RACK, TheftState.POTENTIAL_THEFT):
            # Cooldown recovery: return to normal after departure
            if (now - self.last_state_change_time) > 10.0:
                self._transition_to(
                    TheftState.NORMAL,
                    now,
                    "Reset state after departure cooldown",
                )
                self.item_taken_observed = False
                self.concealment_observed = False
                self.interaction_start_time = None

        return self.current_state, is_theft_event

    @property
    def interaction_duration(self) -> float:
        if self.interaction_start_time is None:
            return 0.0
        return max(0.0, time.time() - self.interaction_start_time)

    def get_history_summary(self) -> List[Dict[str, Any]]:
        return [
            {
                "state": h.state.value,
                "timestamp": h.timestamp,
                "details": h.details,
            }
            for h in self.history
        ]
