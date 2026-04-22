"""
utils/cooldown.py
─────────────────
Simple time-based cooldown guard.

Usage:
    cd = CooldownTimer(seconds=1.0)
    if cd.ready():
        do_action()
        cd.reset()
"""

import time


class CooldownTimer:
    """Prevents an action from firing faster than `seconds` interval."""

    def __init__(self, seconds: float):
        self.interval = seconds
        self._last_fired = 0.0

    def ready(self) -> bool:
        """Return True if enough time has passed since the last reset."""
        return (time.time() - self._last_fired) >= self.interval

    def reset(self):
        """Record the current time as the last fired moment."""
        self._last_fired = time.time()

    def reset_if_ready(self) -> bool:
        """Convenience: reset and return True only when ready."""
        if self.ready():
            self.reset()
            return True
        return False
