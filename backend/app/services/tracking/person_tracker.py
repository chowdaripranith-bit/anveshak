import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union


def compute_iou(boxA: Tuple[float, float, float, float], boxB: Tuple[float, float, float, float]) -> float:
    """Compute Intersection over Union (IoU) between two bounding boxes [x1, y1, x2, y2]."""
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])

    inter_width = max(0.0, xB - xA)
    inter_height = max(0.0, yB - yA)
    inter_area = inter_width * inter_height

    boxA_area = max(0.0, boxA[2] - boxA[0]) * max(0.0, boxA[3] - boxA[1])
    boxB_area = max(0.0, boxB[2] - boxB[0]) * max(0.0, boxB[3] - boxB[1])

    union_area = boxA_area + boxB_area - inter_area
    if union_area <= 0:
        return 0.0
    return inter_area / union_area


def compute_centroid(box: Tuple[float, float, float, float]) -> Tuple[float, float]:
    """Calculate the centroid (cx, cy) of a bounding box [x1, y1, x2, y2]."""
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def euclidean_distance(pt1: Tuple[float, float], pt2: Tuple[float, float]) -> float:
    """Euclidean distance between two 2D points."""
    return ((pt1[0] - pt2[0]) ** 2 + (pt1[1] - pt2[1]) ** 2) ** 0.5


@dataclass
class TrackedPerson:
    """Represents a tracked person across video frames."""

    track_id: int
    bbox: Tuple[float, float, float, float]
    centroid: Tuple[float, float]
    confidence: float
    timestamp: float
    time_created: float
    last_seen: float
    movement_history: List[Tuple[float, float, float]] = field(default_factory=list)  # [(cx, cy, ts)]
    velocity: Tuple[float, float] = (0.0, 0.0)  # (vx, vy)
    lost_frame_count: int = 0

    def update(self, bbox: Tuple[float, float, float, float], confidence: float, timestamp: float):
        """Update track with new frame detection."""
        old_centroid = self.centroid
        old_ts = self.timestamp

        self.bbox = bbox
        self.centroid = compute_centroid(bbox)
        self.confidence = confidence
        self.timestamp = timestamp
        self.last_seen = timestamp
        self.lost_frame_count = 0

        self.movement_history.append((self.centroid[0], self.centroid[1], timestamp))
        if len(self.movement_history) > 120:  # Keep past 120 observations
            self.movement_history.pop(0)

        dt = timestamp - old_ts
        if dt > 0:
            vx = (self.centroid[0] - old_centroid[0]) / dt
            vy = (self.centroid[1] - old_centroid[1]) / dt
            self.velocity = (vx, vy)

    @property
    def label(self) -> str:
        return f"Person #{self.track_id}"

    @property
    def total_dwell_seconds(self) -> float:
        return max(0.0, self.last_seen - self.time_created)


class PersonTracker:
    """Lightweight, deterministic multi-object person tracker using IoU and centroid distance."""

    def __init__(
        self,
        iou_threshold: float = 0.25,
        centroid_distance_threshold: float = 120.0,
        max_lost_frames: int = 30,
    ):
        self.iou_threshold = iou_threshold
        self.centroid_distance_threshold = centroid_distance_threshold
        self.max_lost_frames = max_lost_frames
        self.next_track_id: int = 1
        self.active_tracks: Dict[int, TrackedPerson] = {}

    def update(
        self,
        detections: List[Union[Tuple[float, float, float, float, float], Dict[str, Any]]],
        timestamp: Optional[float] = None,
    ) -> List[TrackedPerson]:
        """Update tracker with detections from current frame.

        Parameters
        ----------
        detections : list
            List of detections: either (x1, y1, x2, y2, confidence) or dicts with "bbox" and "confidence".
        timestamp : float, optional
            Current frame timestamp in seconds (default is time.time()).

        Returns
        -------
        List[TrackedPerson]
            Currently active and visible tracked persons.
        """
        now = time.time() if timestamp is None else float(timestamp)

        parsed_detections: List[Tuple[Tuple[float, float, float, float], float]] = []
        for det in detections:
            if isinstance(det, (tuple, list)) and len(det) >= 5:
                parsed_detections.append(((float(det[0]), float(det[1]), float(det[2]), float(det[3])), float(det[4])))
            elif isinstance(det, dict) and "bbox" in det:
                b = det["bbox"]
                c = float(det.get("confidence", 1.0))
                parsed_detections.append(((float(b[0]), float(b[1]), float(b[2]), float(b[3])), c))

        matched_track_ids = set()
        matched_det_indices = set()

        # Step 1: Match existing tracks with detections by IoU
        if self.active_tracks and parsed_detections:
            candidates = []
            for track_id, track in self.active_tracks.items():
                for det_idx, (bbox, conf) in enumerate(parsed_detections):
                    iou = compute_iou(track.bbox, bbox)
                    if iou >= self.iou_threshold:
                        candidates.append((iou, track_id, det_idx))

            # Greedy sort by highest IoU
            candidates.sort(key=lambda x: x[0], reverse=True)
            for iou, track_id, det_idx in candidates:
                if track_id not in matched_track_ids and det_idx not in matched_det_indices:
                    bbox, conf = parsed_detections[det_idx]
                    self.active_tracks[track_id].update(bbox, conf, now)
                    matched_track_ids.add(track_id)
                    matched_det_indices.add(det_idx)

        # Step 2: For unmatched detections, try matching by centroid distance
        if self.active_tracks and len(matched_det_indices) < len(parsed_detections):
            unmatched_tracks = [t for tid, t in self.active_tracks.items() if tid not in matched_track_ids]
            dist_candidates = []
            for track in unmatched_tracks:
                for det_idx, (bbox, conf) in enumerate(parsed_detections):
                    if det_idx in matched_det_indices:
                        continue
                    c_det = compute_centroid(bbox)
                    dist = euclidean_distance(track.centroid, c_det)
                    if dist <= self.centroid_distance_threshold:
                        dist_candidates.append((dist, track.track_id, det_idx))

            dist_candidates.sort(key=lambda x: x[0])  # Shortest distance first
            for dist, track_id, det_idx in dist_candidates:
                if track_id not in matched_track_ids and det_idx not in matched_det_indices:
                    bbox, conf = parsed_detections[det_idx]
                    self.active_tracks[track_id].update(bbox, conf, now)
                    matched_track_ids.add(track_id)
                    matched_det_indices.add(det_idx)

        # Step 3: Increment lost frames for unmatched active tracks
        to_delete = []
        for track_id, track in self.active_tracks.items():
            if track_id not in matched_track_ids:
                track.lost_frame_count += 1
                if track.lost_frame_count > self.max_lost_frames:
                    to_delete.append(track_id)

        for track_id in to_delete:
            del self.active_tracks[track_id]

        # Step 4: Create new tracks for unmatched detections
        for det_idx, (bbox, conf) in enumerate(parsed_detections):
            if det_idx not in matched_det_indices:
                new_id = self.next_track_id
                self.next_track_id += 1
                centroid = compute_centroid(bbox)
                new_track = TrackedPerson(
                    track_id=new_id,
                    bbox=bbox,
                    centroid=centroid,
                    confidence=conf,
                    timestamp=now,
                    time_created=now,
                    last_seen=now,
                    movement_history=[(centroid[0], centroid[1], now)],
                    velocity=(0.0, 0.0),
                    lost_frame_count=0,
                )
                self.active_tracks[new_id] = new_track

        # Return tracks currently active in this frame (lost_frame_count == 0)
        return [t for t in self.active_tracks.values() if t.lost_frame_count == 0]

    def get_track(self, track_id: int) -> Optional[TrackedPerson]:
        return self.active_tracks.get(track_id)

    def reset(self):
        """Reset all tracking states."""
        self.active_tracks.clear()
        self.next_track_id = 1
