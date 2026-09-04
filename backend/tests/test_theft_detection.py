import asyncio
import os
import time
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from app.config import settings
from app.services.activity.suspicious_detector import SuspiciousActivityDetector
from app.services.detection.camera_worker import _save_snapshot
from app.services.detection.processor import DetectionProcessor, is_security_event
from app.services.featherless import FeatherlessService
from app.services.theft.state_machine import TheftState, TheftStateMachine
from app.services.theft.theft_detector import TheftDetector
from app.services.theft.zone import RackZone
from app.services.tracking.person_tracker import PersonTracker, TrackedPerson


# 1. Rack Zone Geometry Tests
def test_rack_zone_geometry():
    zone = RackZone(id="test_zone", name="Test Rack", x1=0.3, y1=0.3, x2=0.7, y2=0.7)
    # Inside point
    assert zone.contains_point(0.5, 0.5) is True
    # Outside point
    assert zone.contains_point(0.1, 0.1) is False
    # Margin test (point at 0.28 with margin 0.05 is inside)
    assert zone.contains_point(0.28, 0.5, margin=0.05) is True

    # Distance calculation
    assert zone.distance_to((0.5, 0.5)) == 0.0
    dist_outside = zone.distance_to((0.1, 0.5))
    assert pytest.approx(dist_outside, 0.01) == 0.2


# 2. Person Tracker Tests
def test_person_tracker_lifecycle():
    tracker = PersonTracker(iou_threshold=0.3, max_lost_frames=5)

    # Frame 1: Person appears
    det_f1 = [(0.4, 0.4, 0.6, 0.8, 0.90)]
    t1 = tracker.update(det_f1, timestamp=100.0)
    assert len(t1) == 1
    assert t1[0].track_id == 1
    assert t1[0].centroid == pytest.approx((0.5, 0.6), 0.01)

    # Frame 2: Person moves slightly
    det_f2 = [(0.42, 0.4, 0.62, 0.8, 0.92)]
    t2 = tracker.update(det_f2, timestamp=101.0)
    assert len(t2) == 1
    assert t2[0].track_id == 1  # Track ID persisted
    assert len(t2[0].movement_history) == 2

    # Frame 3: Person lost for multiple frames
    for f in range(6):
        tracker.update([], timestamp=102.0 + f)
    assert len(tracker.active_tracks) == 0  # Pruned after max_lost_frames


# 3. Rack Entry and Dwell
def test_theft_state_machine_rack_entry():
    zone = RackZone(id="rack1", name="Rack 1", x1=0.3, y1=0.3, x2=0.7, y2=0.7)
    sm = TheftStateMachine(track_id=1, zone=zone, min_interaction_seconds=2.0)

    p = TrackedPerson(
        track_id=1,
        bbox=(0.4, 0.4, 0.6, 0.6),
        centroid=(0.5, 0.5),  # Inside zone
        confidence=0.9,
        timestamp=100.0,
        time_created=100.0,
        last_seen=100.0,
    )

    state, is_theft = sm.update(p, timestamp=100.0)
    assert state == TheftState.INTERACTING_WITH_RACK
    assert is_theft is False


# 4. Normal Shopping Does NOT Trigger Theft
def test_normal_shopping_does_not_trigger_theft():
    """Verify that a customer inspecting items and walking away does NOT trigger theft."""
    zone = RackZone(id="rack1", name="Rack 1", x1=0.3, y1=0.3, x2=0.7, y2=0.7)
    sm = TheftStateMachine(track_id=1, zone=zone, min_interaction_seconds=2.0)

    # Step 1: Customer enters rack zone
    p_inside = TrackedPerson(1, (0.4, 0.4, 0.6, 0.6), (0.5, 0.5), 0.9, 100.0, 100.0, 100.0)
    state, is_theft = sm.update(p_inside, timestamp=100.0)
    assert state == TheftState.INTERACTING_WITH_RACK
    assert is_theft is False

    # Step 2: Customer browses for 5 seconds
    p_inside.centroid = (0.52, 0.5)
    state, is_theft = sm.update(p_inside, timestamp=105.0)
    assert state == TheftState.INTERACTING_WITH_RACK
    assert is_theft is False

    # Step 3: Customer walks away without concealing anything
    p_outside = TrackedPerson(1, (0.05, 0.05, 0.15, 0.15), (0.1, 0.1), 0.9, 108.0, 100.0, 108.0)
    state, is_theft = sm.update(p_outside, timestamp=108.0)

    # Must transition back to NORMAL shopping, NOT theft!
    assert state == TheftState.NORMAL
    assert is_theft is False


# 5. Full Potential Theft Sequence Triggers Event
def test_potential_theft_sequence():
    """Verify sequence: NORMAL -> INTERACTING -> ITEM_TAKEN -> CONCEALMENT -> LEFT_RACK -> POTENTIAL_THEFT."""
    zone = RackZone(id="rack1", name="Rack 1", x1=0.3, y1=0.3, x2=0.7, y2=0.7)
    sm = TheftStateMachine(track_id=1, zone=zone, min_interaction_seconds=2.0)

    # 1. Enters rack
    p1 = TrackedPerson(1, (0.4, 0.4, 0.6, 0.6), (0.5, 0.5), 0.9, 100.0, 100.0, 100.0)
    state, _ = sm.update(p1, timestamp=100.0)
    assert state == TheftState.INTERACTING_WITH_RACK

    # 2. Item interaction occurs
    state, _ = sm.update(p1, timestamp=103.0, item_taken_cue=True)
    assert state == TheftState.ITEM_TAKEN

    # 3. Concealment cue observed
    state, _ = sm.update(
        p1,
        timestamp=104.0,
        concealment_cue=True,
        concealment_evidence_detail="Item placed into coat inner pocket",
    )
    assert state == TheftState.POSSIBLE_CONCEALMENT

    # 4. Departs rack zone
    p_departed = TrackedPerson(1, (0.05, 0.05, 0.15, 0.15), (0.1, 0.1), 0.9, 107.0, 100.0, 107.0)
    state, is_theft = sm.update(p_departed, timestamp=107.0)

    assert state == TheftState.POTENTIAL_THEFT
    assert is_theft is True


# 6. Theft Cooldown Prevents Duplicate Floods
def test_theft_cooldown():
    zone = RackZone(id="rack1", name="Rack 1", x1=0.3, y1=0.3, x2=0.7, y2=0.7)
    detector = TheftDetector(rack_zone=zone, theft_cooldown_seconds=15.0)

    p = TrackedPerson(1, (0.1, 0.1, 0.2, 0.2), (0.15, 0.15), 0.9, 100.0, 100.0, 100.0)

    # Advance track 1 to theft
    cues_theft = {1: {"item_taken": True, "concealment": True, "concealment_detail": "Bag concealment"}}

    # Frame 1: Approach
    p.centroid = (0.5, 0.5)
    detector.evaluate_tracks([p], timestamp=100.0)

    # Frame 2: Interact & Conceal
    detector.evaluate_tracks([p], timestamp=103.0, cues_by_track=cues_theft)

    # Frame 3: Depart -> Event emitted
    p.centroid = (0.1, 0.1)
    events1 = detector.evaluate_tracks([p], timestamp=106.0)
    assert len(events1) == 1
    assert events1[0].track_id == 1

    # Immediate next frame should be blocked by cooldown
    events2 = detector.evaluate_tracks([p], timestamp=107.0)
    assert len(events2) == 0


# 7. Snapshot and Evidence Directory Creation
def test_evidence_snapshot_generation(tmp_path):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    snapshot_path = _save_snapshot(
        frame=frame,
        label="theft",
        camera_id="cam_test",
        category="theft",
        track_id=42,
    )
    assert snapshot_path is not None
    assert os.path.exists(snapshot_path)
    assert "cam_test_theft_track_42" in snapshot_path
    assert os.path.getsize(snapshot_path) > 0


# 8. Featherless Theft Event Processing
@pytest.mark.asyncio
async def test_featherless_theft_event_processing():
    """Verify that theft events are recognized as security events and sent to AI with fallback."""
    assert is_security_event(incident_type="theft", detected_object="person_theft_behavior") is True

    # Use simulated fallback AI service
    dummy_ai = FeatherlessService(api_key="", timeout=1.0)
    processor = DetectionProcessor(featherless_service=dummy_ai)

    result = await processor.process_event(
        detected_object="person_theft_behavior",
        confidence=0.88,
        incident_type="theft",
        camera_id=1,
        other_info={
            "track_id": 5,
            "rack_zone": "Main_Display_Rack_1",
            "interaction_duration": 4.5,
        },
        broadcast_alert=False,
    )

    assert result["status"] == "success"
    assert result["security_event"] is True
    assert result["alert"] is not None
    assert result["alert"]["incident_type"] == "theft"
    assert result["alert"]["track_id"] == 5


# 9. WebSocket Alert Broadcast
@pytest.mark.asyncio
async def test_websocket_alert_broadcast():
    with patch("app.services.detection.processor.ws_manager.broadcast", new_callable=AsyncMock) as mock_ws:
        dummy_ai = FeatherlessService(api_key="", timeout=1.0)
        processor = DetectionProcessor(featherless_service=dummy_ai)

        await processor.process_event(
            detected_object="person_theft_behavior",
            confidence=0.92,
            incident_type="theft",
            camera_id=1,
            other_info={"track_id": 9, "snapshot": "evidence/theft/cam1_theft.jpg"},
            broadcast_alert=True,
        )

        mock_ws.assert_called_once()
        sent_payload = mock_ws.call_args[0][0]
        assert sent_payload["type"] == "NEW_ALERT"
        assert sent_payload["data"]["incident_type"] == "theft"
        assert sent_payload["data"]["track_id"] == 9
        assert sent_payload["data"]["snapshot"] == "evidence/theft/cam1_theft.jpg"


# 10. Suspicious Activity (Loitering & Prolonged Presence)
def test_suspicious_activity_detector():
    detector = SuspiciousActivityDetector(
        loitering_threshold_seconds=5.0,
        prolonged_presence_seconds=10.0,
    )

    # Person loitering in confined spot
    p = TrackedPerson(
        track_id=3,
        bbox=(0.4, 0.4, 0.5, 0.5),
        centroid=(0.45, 0.45),
        confidence=0.85,
        timestamp=100.0,
        time_created=90.0,  # 10 seconds total presence
        last_seen=100.0,
    )
    # Fill stationary movement history
    for i in range(15):
        p.movement_history.append((0.45 + 0.001 * i, 0.45, 90.0 + i))

    events = detector.evaluate_person(p, timestamp=100.0)
    assert len(events) >= 1
    types = [e.activity_type for e in events]
    assert "LOITERING" in types or "PROLONGED_PRESENCE" in types
