"""
actions/volume.py  –  v6
─────────────────────────
Windows volume via direct ctypes COM — no pycaw version dependency.

Root cause of warning
──────────────────────
Different pycaw versions return different types from GetSpeakers():
  Old pycaw : IMMDevice  → needs .Activate(iid, ctx, None)
  New pycaw : AudioDevice wrapper → no .Activate(), needs different path

Fix: bypass pycaw's high-level wrappers entirely.
Use ctypes + comtypes to call IMMDeviceEnumerator directly,
which works identically on all Windows 10/11 versions.

Fallback chain
───────────────
  1. ctypes/comtypes direct COM  (zero subprocess, fastest, always correct)
  2. pycaw high-level (kept as safety net)
  3. pyautogui keyboard media keys (approximate but guaranteed)
"""

from __future__ import annotations
import platform
import subprocess
from utils.logger import get_logger

log     = get_logger(__name__)
_SYSTEM = platform.system()

_iface      = None   # IAudioEndpointVolume COM interface
_iface_done = False  # only try once


def _init_windows_volume():
    """
    Initialise Windows Core Audio volume interface via direct COM.
    This approach works regardless of pycaw version.
    """
    global _iface, _iface_done
    if _iface_done:
        return _iface
    _iface_done = True

    if _SYSTEM != "Windows":
        return None

    # ── Approach 1: direct ctypes COM (no pycaw wrapper) ─────────────────────
    try:
        import ctypes
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from comtypes.client import CreateObject
        from pycaw.pycaw import IAudioEndpointVolume

        # Use comtypes.client.CreateObject to get the device enumerator
        # This bypasses AudioUtilities.GetSpeakers() entirely
        from pycaw.pycaw import IMMDeviceEnumerator, EDataFlow, ERole
        from comtypes import CoCreateInstance, GUID

        CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
        enumerator = CoCreateInstance(
            CLSID_MMDeviceEnumerator,
            IMMDeviceEnumerator,
            CLSCTX_ALL
        )
        # eRender=0, eMultimedia=1
        device = enumerator.GetDefaultAudioEndpoint(0, 1)
        interface = device.Activate(
            IAudioEndpointVolume._iid_, CLSCTX_ALL, None
        )
        _iface = cast(interface, POINTER(IAudioEndpointVolume))
        log.info("Windows volume: COM direct interface ready.")
        return _iface
    except Exception as e:
        log.debug(f"COM direct approach failed: {e}")

    # ── Approach 2: pycaw high-level with both .Activate() and QueryInterface ─
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        speakers = AudioUtilities.GetSpeakers()

        # Try .Activate() — works on IMMDevice objects
        try:
            iface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            _iface = cast(iface, POINTER(IAudioEndpointVolume))
            log.info("Windows volume: pycaw Activate() ready.")
            return _iface
        except AttributeError:
            pass

        # Try QueryInterface — works on AudioDevice wrapper objects
        try:
            _iface = speakers.QueryInterface(IAudioEndpointVolume)
            log.info("Windows volume: pycaw QueryInterface() ready.")
            return _iface
        except Exception:
            pass

    except Exception as e:
        log.debug(f"pycaw approaches failed: {e}")

    log.warning(
        "Windows volume API unavailable — keyboard media keys will be used.\n"
        "  To fix: pip install pycaw comtypes  (or reinstall pycaw)"
    )
    return None


def _keyboard_volume(direction: str, presses: int = 1):
    try:
        import pyautogui
        pyautogui.PAUSE = 0
        key = "volumeup" if direction == "up" else "volumedown"
        for _ in range(presses):
            pyautogui.press(key)
        return True
    except Exception:
        return False


def _run(cmd: list) -> str:
    try:
        return subprocess.check_output(
            cmd, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""


# ── Public API ────────────────────────────────────────────────────────────────

def get_volume() -> int:
    """Return current master volume 0–100."""
    try:
        if _SYSTEM == "Windows":
            v = _init_windows_volume()
            if v:
                return int(v.GetMasterVolumeLevelScalar() * 100)
        elif _SYSTEM == "Darwin":
            out = _run(["osascript", "-e",
                        "output volume of (get volume settings)"])
            if out.isdigit():
                return int(out)
        elif _SYSTEM == "Linux":
            out = _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
            if out:
                import re
                m = re.search(r"(\d+)%", out)
                if m:
                    return int(m.group(1))
            out = _run(["amixer", "get", "Master"])
            if out:
                import re
                m = re.search(r"\[(\d+)%\]", out)
                if m:
                    return int(m.group(1))
    except Exception:
        pass
    return 50


def set_volume(percent: int) -> int:
    """Set master volume to *percent* (0–100). Returns resulting level."""
    percent = max(0, min(100, int(percent)))
    try:
        if _SYSTEM == "Windows":
            v = _init_windows_volume()
            if v:
                v.SetMasterVolumeLevelScalar(percent / 100.0, None)
                return percent

        elif _SYSTEM == "Darwin":
            subprocess.call(
                ["osascript", "-e", f"set volume output volume {percent}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return percent

        elif _SYSTEM == "Linux":
            ret = subprocess.call(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            if ret == 0:
                return percent
            subprocess.call(
                ["amixer", "-q", "sset", "Master", f"{percent}%"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return percent

    except Exception as e:
        log.debug(f"set_volume({percent}%): {e}")

    # Keyboard fallback
    current = get_volume()
    delta   = percent - current
    if abs(delta) >= 2:
        _keyboard_volume("up" if delta > 0 else "down", max(1, abs(delta) // 2))
    return get_volume()
