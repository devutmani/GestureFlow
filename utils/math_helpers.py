"""
utils/math_helpers.py
─────────────────────
Pure-math helpers used across the gesture pipeline.
All coordinates are assumed to be normalised (0.0–1.0) unless noted.
"""

import math
from typing import Tuple


Point2D = Tuple[float, float]


def euclidean(p1: Point2D, p2: Point2D) -> float:
    """Euclidean distance between two 2-D points."""
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


def midpoint(p1: Point2D, p2: Point2D) -> Point2D:
    """Return the midpoint of a line segment."""
    return ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)


def angle_degrees(p1: Point2D, p2: Point2D) -> float:
    """
    Angle (in degrees) of the vector from p1 → p2,
    measured counter-clockwise from the positive x-axis.
    """
    return math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))


def clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to the closed interval [lo, hi]."""
    return max(lo, min(hi, value))


def normalise_to_pixel(
    norm_x: float, norm_y: float, frame_w: int, frame_h: int
) -> Tuple[int, int]:
    """Convert normalised (0–1) landmark coordinates to pixel coordinates."""
    return int(norm_x * frame_w), int(norm_y * frame_h)


def smoothstep(value: float) -> float:
    """
    Smooth-step easing (Ken Perlin's version).
    Maps value in [0,1] → [0,1] with ease-in/ease-out.
    Useful for mapping pinch distance to volume levels.
    """
    v = clamp(value, 0.0, 1.0)
    return v * v * (3 - 2 * v)


def map_range(
    value: float, in_lo: float, in_hi: float, out_lo: float, out_hi: float
) -> float:
    """
    Linear map from [in_lo, in_hi] → [out_lo, out_hi].
    Clamps the result to [out_lo, out_hi].
    """
    if in_hi == in_lo:
        return out_lo
    ratio = (value - in_lo) / (in_hi - in_lo)
    return clamp(out_lo + ratio * (out_hi - out_lo), out_lo, out_hi)
