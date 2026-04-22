"""
actions/brightness.py  –  v4
──────────────────────────────
Cross-platform brightness control.
Mirrors the volume approach: set_brightness(target) called each frame.

Windows : screen_brightness_control (WMI)  →  PowerShell WMI
macOS   : screen_brightness_control        →  keyboard keys
Linux   : screen_brightness_control        →  brightnessctl  →  xrandr
"""

from __future__ import annotations
import platform
import subprocess
from utils.logger import get_logger

log     = get_logger(__name__)
_SYSTEM = platform.system()

_sbc      = None
_sbc_done = False

def _get_sbc():
    global _sbc, _sbc_done
    if _sbc_done:
        return _sbc
    _sbc_done = True
    try:
        import screen_brightness_control as sbc
        sbc.get_brightness()   # probe
        _sbc = sbc
        log.info("screen_brightness_control ready.")
    except Exception as e:
        log.warning(f"screen_brightness_control unavailable ({e}).")
    return _sbc

def get_brightness() -> int:
    sbc = _get_sbc()
    if sbc:
        try:
            val = sbc.get_brightness()
            return int(val[0]) if isinstance(val, (list, tuple)) else int(val)
        except Exception:
            pass
    return 50

def set_brightness(percent: int) -> int:
    """Set brightness to absolute *percent* (5–100). Called every frame."""
    percent = max(5, min(100, int(percent)))

    sbc = _get_sbc()
    if sbc:
        try:
            sbc.set_brightness(percent)
            return percent
        except Exception as e:
            log.debug(f"sbc.set_brightness failed: {e}")

    if _SYSTEM == "Windows":
        ps = (f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
              f".WmiSetBrightness(1,{percent})")
        subprocess.call(
            ["powershell", "-NoProfile", "-Command", ps],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return percent

    elif _SYSTEM == "Linux":
        for cmd in [
            ["brightnessctl", "set", f"{percent}%"],
            ["light", "-S", str(percent)],
        ]:
            try:
                if subprocess.call(cmd, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL) == 0:
                    return percent
            except FileNotFoundError:
                continue
        # xrandr gamma approach
        gamma = percent / 100.0
        for disp in ["eDP-1", "eDP1", "LVDS-1", "LVDS1"]:
            if subprocess.call(
                ["xrandr", "--output", disp, "--brightness", f"{gamma:.2f}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            ) == 0:
                return percent

    elif _SYSTEM == "Darwin":
        # macOS keyboard brightness keys (~5% per press)
        current = get_brightness()
        delta   = percent - current
        if abs(delta) >= 5:
            try:
                import pyautogui
                pyautogui.PAUSE = 0
                key    = "brightnessup" if delta > 0 else "brightnessdown"
                presses = max(1, abs(delta) // 5)
                for _ in range(presses):
                    pyautogui.press(key)
            except Exception:
                pass

    return percent
