from dataclasses import dataclass
from typing import Tuple, Union


@dataclass
class RackZone:
    """Configurable rack or merchandise interaction zone using normalized coordinates (0.0 to 1.0)."""

    id: str
    name: str
    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self):
        # Ensure ordered bounding box
        self.x1, self.x2 = min(self.x1, self.x2), max(self.x1, self.x2)
        self.y1, self.y2 = min(self.y1, self.y2), max(self.y1, self.y2)

    def contains_point(self, x: float, y: float, margin: float = 0.0) -> bool:
        """Check if a normalized point (x, y) falls inside the rack zone (with optional margin)."""
        return (
            (self.x1 - margin) <= x <= (self.x2 + margin)
            and (self.y1 - margin) <= y <= (self.y2 + margin)
        )

    def overlaps_bbox(
        self,
        bbox: Tuple[float, float, float, float],
        margin: float = 0.0,
    ) -> bool:
        """Check if a normalized bounding box [bx1, by1, bx2, by2] intersects this zone."""
        bx1, by1, bx2, by2 = bbox[0], bbox[1], bbox[2], bbox[3]
        return not (
            bx2 < (self.x1 - margin)
            or bx1 > (self.x2 + margin)
            or by2 < (self.y1 - margin)
            or by1 > (self.y2 + margin)
        )

    def distance_to(self, point_or_bbox: Union[Tuple[float, float], Tuple[float, float, float, float]]) -> float:
        """Calculate minimum Euclidean distance from a normalized point or box centroid to the zone boundary."""
        if len(point_or_bbox) == 4:
            px = (point_or_bbox[0] + point_or_bbox[2]) / 2.0
            py = (point_or_bbox[1] + point_or_bbox[3]) / 2.0
        else:
            px, py = point_or_bbox[0], point_or_bbox[1]

        # Calculate distance to clamped point on rectangle
        cx = max(self.x1, min(px, self.x2))
        cy = max(self.y1, min(py, self.y2))
        return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5

    def to_absolute(self, frame_width: int, frame_height: int) -> Tuple[int, int, int, int]:
        """Convert normalized coordinates to integer pixel box (px1, py1, px2, py2)."""
        return (
            int(self.x1 * frame_width),
            int(self.y1 * frame_height),
            int(self.x2 * frame_width),
            int(self.y2 * frame_height),
        )
