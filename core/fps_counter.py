"""
core/fps_counter.py
────────────────────
Smooth FPS counter using a rolling average.
"""

import time
from collections import deque


class FPSCounter:
    """Compute frames-per-second over a rolling window."""

    def __init__(self, window: int = 30):
        self._times: deque = deque(maxlen=window)
        self._last  = time.perf_counter()

    def tick(self) -> float:
        """Call once per frame. Returns current smoothed FPS."""
        now = time.perf_counter()
        self._times.append(now - self._last)
        self._last = now
        if not self._times:
            return 0.0
        return len(self._times) / sum(self._times)

    @property
    def fps(self) -> float:
        if not self._times:
            return 0.0
        return len(self._times) / sum(self._times)
