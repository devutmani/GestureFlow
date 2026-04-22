"""
actions/window_manager.py
─────────────────────────
Window / desktop management actions via pyautogui keyboard shortcuts.

Each action maps to a keyboard shortcut that works on the target OS.

  Action              Windows            macOS               Linux (GNOME)
  ──────────────────  ─────────────────  ──────────────────  ──────────────────
  minimize            Win+Down           Cmd+M               Super+H
  show_desktop        Win+D              Mission Control key  Super+D
  next_window         Alt+Tab            Cmd+Tab             Alt+Tab
  prev_window         Alt+Shift+Tab      Cmd+Shift+Tab       Alt+Shift+Tab
  next_workspace      Ctrl+Win+Right     Ctrl+Right          Ctrl+Alt+Right
  prev_workspace      Ctrl+Win+Left      Ctrl+Left           Ctrl+Alt+Left

NOTE: pyautogui is imported lazily (inside each function) so this module
can be imported in headless / no-display test environments without crashing.
"""

from __future__ import annotations

import platform
from utils.logger import get_logger

log = get_logger(__name__)
_SYSTEM = platform.system()


def _pyautogui():
    """Lazy import of pyautogui — avoids DISPLAY errors at module load time."""
    import pyautogui as _pg
    _pg.PAUSE = 0.0
    return _pg


def minimize_window():
    """Minimise the currently focused window."""
    log.info("Action: minimize_window")
    pg = _pyautogui()
    if _SYSTEM == "Windows":
        pg.hotkey("win", "down")
    elif _SYSTEM == "Darwin":
        pg.hotkey("command", "m")
    else:
        pg.hotkey("super", "h")


def show_desktop():
    """Minimise all windows / show desktop."""
    log.info("Action: show_desktop")
    pg = _pyautogui()
    if _SYSTEM == "Windows":
        pg.hotkey("win", "d")
    elif _SYSTEM == "Darwin":
        pg.keyDown("f3")
        pg.keyUp("f3")
    else:
        pg.hotkey("super", "d")


def next_window():
    """Switch to the next open window (Alt+Tab)."""
    log.info("Action: next_window")
    _pyautogui().hotkey("alt", "tab")


def prev_window():
    """Switch to the previous open window."""
    log.info("Action: prev_window")
    _pyautogui().hotkey("alt", "shift", "tab")


def next_workspace():
    """Move to the next virtual desktop / workspace."""
    log.info("Action: next_workspace")
    pg = _pyautogui()
    if _SYSTEM == "Windows":
        pg.hotkey("ctrl", "win", "right")
    elif _SYSTEM == "Darwin":
        pg.hotkey("ctrl", "right")
    else:
        pg.hotkey("ctrl", "alt", "right")


def prev_workspace():
    """Move to the previous virtual desktop / workspace."""
    log.info("Action: prev_workspace")
    pg = _pyautogui()
    if _SYSTEM == "Windows":
        pg.hotkey("ctrl", "win", "left")
    elif _SYSTEM == "Darwin":
        pg.hotkey("ctrl", "left")
    else:
        pg.hotkey("ctrl", "alt", "left")


def scroll_up(clicks: int = 4):
    """Scroll up at the current mouse position."""
    _pyautogui().scroll(clicks)


def scroll_down(clicks: int = 4):
    """Scroll down at the current mouse position."""
    _pyautogui().scroll(-clicks)


def next_tab():
    """Switch to the next browser/editor tab (Ctrl+Tab)."""
    log.info("Action: next_tab")
    pg = _pyautogui()
    if _SYSTEM == "Darwin":
        pg.hotkey("command", "option", "right")
    else:
        pg.hotkey("ctrl", "tab")


def prev_tab():
    """Switch to the previous browser/editor tab (Ctrl+Shift+Tab)."""
    log.info("Action: prev_tab")
    pg = _pyautogui()
    if _SYSTEM == "Darwin":
        pg.hotkey("command", "option", "left")
    else:
        pg.hotkey("ctrl", "shift", "tab")


def media_play_pause():
    """Toggle media play/pause."""
    log.info("Action: media_play_pause")
    _pyautogui().press("playpause")


# ── Cursor control ────────────────────────────────────────────────────────────

def cursor_move(sx: int, sy: int):
    """Move the mouse cursor to absolute screen coordinates (sx, sy)."""
    try:
        import pyautogui
        pyautogui.PAUSE = 0
        pyautogui.moveTo(sx, sy, duration=0, _pause=False)
    except Exception as e:
        log.debug(f"cursor_move error: {e}")


def cursor_click():
    """Perform a left mouse click at the current cursor position."""
    log.info("Action: cursor_click")
    try:
        import pyautogui
        pyautogui.PAUSE = 0
        pyautogui.click()
    except Exception as e:
        log.debug(f"cursor_click error: {e}")


# ── Task Switcher helpers ─────────────────────────────────────────────────────
# These three functions implement a stateful Alt+Tab sequence.
# Call task_switch_open() once when the pinch closes.
# Call task_switch_next() / task_switch_prev() while dragging.
# Call task_switch_commit() when the pinch opens — releases Alt.

_task_switch_active = False   # module-level flag


def task_switch_open():
    """Press and HOLD Alt, then press Tab to open the task switcher overlay."""
    global _task_switch_active
    if _task_switch_active:
        return
    log.info("Task switcher: OPEN")
    pg = _pyautogui()
    if _SYSTEM == "Darwin":
        pg.keyDown("command")
        pg.press("tab")
    else:
        pg.keyDown("alt")
        pg.press("tab")
    _task_switch_active = True


def task_switch_next():
    """Move selection one step forward (Tab while Alt is held)."""
    if not _task_switch_active:
        return
    pg = _pyautogui()
    if _SYSTEM == "Darwin":
        pg.press("tab")
    else:
        pg.press("tab")


def task_switch_prev():
    """Move selection one step backward (Shift+Tab while Alt is held)."""
    if not _task_switch_active:
        return
    pg = _pyautogui()
    pg.keyDown("shift")
    pg.press("tab")
    pg.keyUp("shift")


def task_switch_commit():
    """Release Alt to confirm the selected window."""
    global _task_switch_active
    if not _task_switch_active:
        return
    log.info("Task switcher: COMMIT (release alt)")
    pg = _pyautogui()
    if _SYSTEM == "Darwin":
        pg.keyUp("command")
    else:
        pg.keyUp("alt")
    _task_switch_active = False


def task_switch_cancel():
    """Escape out of the task switcher without switching."""
    global _task_switch_active
    if not _task_switch_active:
        return
    log.info("Task switcher: CANCEL")
    pg = _pyautogui()
    pg.press("escape")
    if _SYSTEM == "Darwin":
        pg.keyUp("command")
    else:
        pg.keyUp("alt")
    _task_switch_active = False


def take_screenshot():
    """
    Take a screenshot and save it to the best available location.

    Save order (Windows):
      1. User's Desktop (handles both OneDrive and classic Desktop)
      2. User's Pictures folder
      3. GestureFlow script directory
    Unix: ~/Desktop → ~/Pictures → script dir
    """
    import os
    import datetime
    import pathlib

    log.info("Action: screenshot")
    screenshot = _pyautogui().screenshot()
    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"GestureFlow_screenshot_{ts}.png"

    # Build candidate save directories in priority order
    candidates = []

    if _SYSTEM == "Windows":
        # Windows Desktop can be in OneDrive or classic location
        # Try USERPROFILE-based path first (most reliable on Windows)
        user_profile = os.environ.get("USERPROFILE", "")
        if user_profile:
            candidates.append(pathlib.Path(user_profile) / "Desktop")
            candidates.append(pathlib.Path(user_profile) / "OneDrive" / "Desktop")
            candidates.append(pathlib.Path(user_profile) / "Pictures")
        # Also try expanduser (works when not mixed with forward slashes)
        candidates.append(pathlib.Path.home() / "Desktop")
        candidates.append(pathlib.Path.home() / "Pictures")
    else:
        candidates.append(pathlib.Path.home() / "Desktop")
        candidates.append(pathlib.Path.home() / "Pictures")

    # Always add the GestureFlow script directory as final fallback
    candidates.append(pathlib.Path(__file__).parent.parent / "screenshots")

    # Try each candidate directory
    save_path = None
    for directory in candidates:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            test_path = directory / name
            screenshot.save(str(test_path))
            save_path = str(test_path)
            log.info(f"Screenshot saved → {save_path}")
            break
        except Exception as e:
            log.debug(f"Screenshot save failed at {directory}: {e}")
            continue

    if save_path is None:
        log.error("Screenshot: all save locations failed.")

    return save_path
