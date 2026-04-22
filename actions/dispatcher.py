"""
actions/dispatcher.py  –  v7
──────────────────────────────
Maps GestureResult → OS action.

State machine (complete)
────────────────────────
┌─────────────────────────────────────────────────────────────────┐
│  VoiceMode.NONE  (DEFAULT — pinch disabled)                     │
│    Pinch gestures  → BLOCKED (None returned, zero side effects) │
│    Task switch     → ACTIVE (only in this mode)                 │
│    Scroll/swipe/minimize/media/screenshot → always work         │
│    Transition → say "volume" or "brightness"                    │
├─────────────────────────────────────────────────────────────────┤
│  VoiceMode.VOLUME                                               │
│    Pinch → volume.set_volume(target)  ONLY                      │
│    Brightness pinch → also routed to volume (no crossover)      │
│    Task switch → BLOCKED (can't vol-adjust AND task-switch)     │
│    All other gestures → work normally                           │
│    Transition → say "lock"  → back to NONE                      │
├─────────────────────────────────────────────────────────────────┤
│  VoiceMode.BRIGHTNESS                                           │
│    Pinch → brightness.set_brightness(target)  ONLY             │
│    Volume pinch → also routed to brightness (no crossover)      │
│    Task switch → BLOCKED                                        │
│    All other gestures → work normally                           │
│    Transition → say "lock"  → back to NONE                      │
└─────────────────────────────────────────────────────────────────┘

Task-switch lifecycle (only in VoiceMode.NONE)
───────────────────────────────────────────────
  TASK_SWITCH_OPEN   → keyDown("alt"), press("tab")  [once]
  TASK_SWITCH_NEXT   → press("tab")        [while alt held]
  TASK_SWITCH_PREV   → keyDown("shift"), press("tab"), keyUp("shift")
  TASK_SWITCH_COMMIT → keyUp("alt")        [pinch released]

Lock command verification
──────────────────────────
  The lock path is:  voice says "lock"
    → VoiceListener._handle() calls state._set_mode(VoiceMode.NONE, raw)
    → VoiceState._mode = VoiceMode.NONE
    → next frame: dispatcher._dispatch_pinch() reads mode == NONE
    → returns None immediately — no vol or bri API called
  This is guaranteed because _dispatch_pinch() has a hard early-return
  for NONE with no fallthrough and no else branch.
"""

from __future__ import annotations

from typing import Optional

from gestures.recognizer import Gesture, GestureResult
from actions import volume, brightness, window_manager
from utils.cooldown import CooldownTimer
from utils.logger import get_logger
import config.settings as cfg

# Import VoiceMode at module level with safe fallback when voice not installed
try:
    from voice.listener import VoiceMode as _VM
    _VM_NONE       = _VM.NONE
    _VM_VOLUME     = _VM.VOLUME
    _VM_BRIGHTNESS = _VM.BRIGHTNESS
except ImportError:
    _VM = _VM_NONE = _VM_VOLUME = _VM_BRIGHTNESS = None

log = get_logger(__name__)

# Pinch gesture set
_PINCH_GESTURES = frozenset({
    Gesture.VOLUME_UP, Gesture.VOLUME_DOWN,
    Gesture.BRIGHTNESS_UP, Gesture.BRIGHTNESS_DOWN,
})

# Task-switch gesture set
_TASK_GESTURES = frozenset({
    Gesture.TASK_SWITCH_OPEN,
    Gesture.TASK_SWITCH_NEXT,
    Gesture.TASK_SWITCH_PREV,
    Gesture.TASK_SWITCH_COMMIT,
})

# Cursor gesture set — always active in all modes (own independent channel)
_CURSOR_GESTURES = frozenset({
    Gesture.CURSOR_MOVE,
    Gesture.CURSOR_CLICK,
})


class ActionResult:
    def __init__(self, label: str = "", value: str = ""):
        self.label = label
        self.value = value

    def __bool__(self):
        return bool(self.label)

    def __repr__(self):
        return f"ActionResult({self.label!r}: {self.value!r})"


class ActionDispatcher:

    def __init__(self):
        self._cd = {
            "swipe":      CooldownTimer(cfg.SWIPE_COOLDOWN),
            "minimize":   CooldownTimer(cfg.MINIMIZE_COOLDOWN),
            "screenshot": CooldownTimer(cfg.SCREENSHOT_COOLDOWN),
            "scroll":     CooldownTimer(cfg.SCROLL_COOLDOWN),
            "media":      CooldownTimer(cfg.MEDIA_COOLDOWN),
            "desktop":    CooldownTimer(cfg.DESKTOP_COOLDOWN),
            "task_nav":   CooldownTimer(cfg.TASK_NAV_COOLDOWN),
        }
        self._probe_apis()
        log.info("ActionDispatcher v7 ready.")
        log.info("  Pinch: DISABLED  |  say 'volume' or 'brightness' to enable")
        log.info("  Task switch: pinch closed + drag left/right (NONE mode only)")

    # ── API probe ─────────────────────────────────────────────────────────────

    def _probe_apis(self):
        import platform
        log.info(f"OS: {platform.system()} — probing APIs …")
        try:
            v = volume.get_volume()
            log.info(f"  Volume     OK  → current {v}%")
        except Exception as e:
            log.warning(f"  Volume     FAIL: {e}")
        try:
            b = brightness.get_brightness()
            log.info(f"  Brightness OK  → current {b}%")
        except Exception as e:
            log.warning(f"  Brightness FAIL: {e}")

    # ── Main entry point ──────────────────────────────────────────────────────

    def dispatch(
        self,
        result:      GestureResult,
        voice_state=None,
    ) -> Optional[ActionResult]:
        """
        Execute action for *result*.  Returns ActionResult for UI or None.
        voice_state: VoiceState (or None → effective mode is NONE).
        """
        # ── Voice one-shot commands — always checked regardless of mode ────────
        if voice_state is not None:
            if voice_state.consume_mute():
                volume.set_volume(0)
                log.info("[VOICE] mute triggered")
                return ActionResult("🎤 Mute", "Volume → 0%")
            if voice_state.consume_media():
                window_manager.media_play_pause()
                return ActionResult("🎤 Media", "Play / Pause")

        g = result.gesture
        if g == Gesture.NONE:
            return None

        # Resolve current voice mode using module-level constants
        # When voice_state is None (voice disabled), treat as NONE mode
        mode = voice_state.mode if voice_state is not None else _VM_NONE

        # ── Pinch → strictly gated by voice mode ──────────────────────────────
        if g in _PINCH_GESTURES:
            return self._dispatch_pinch(g, result, mode)

        # ── Cursor control — active in ALL modes ──────────────────────────────
        if g in _CURSOR_GESTURES:
            return self._dispatch_cursor(g, result)

        # ── Task switch → only in NONE mode ───────────────────────────────────
        if g in _TASK_GESTURES:
            if mode is _VM_NONE or mode is None:
                return self._dispatch_task_switch(g, result)
            else:
                return None

        # ── General gestures — active in ALL modes ────────────────────────────
        return self._dispatch_general(g, result)

    # ── Pinch gate ────────────────────────────────────────────────────────────

    def _dispatch_pinch(
        self,
        g:      Gesture,
        result: GestureResult,
        mode,
    ) -> Optional[ActionResult]:
        """
        Hard three-way gate — no fallthrough, zero crossover.
        Uses module-level _VM_* constants — no import in hot path.
        """
        # NONE / voice unavailable: pinch fully disabled
        if mode is _VM_NONE or mode is None:
            return None

        target = result.meta.get("target")
        if target is None:
            return None
        target = int(target)

        if mode is _VM_VOLUME:
            volume.set_volume(target)
            direction = "▲" if g in (Gesture.VOLUME_UP, Gesture.BRIGHTNESS_UP) else "▼"
            log.debug(f"[VOLUME MODE] set_volume({target}%)")
            return ActionResult(f"🎤 {direction} Volume", f"{target}%")

        if mode is _VM_BRIGHTNESS:
            brightness.set_brightness(target)
            direction = "▲" if g in (Gesture.VOLUME_UP, Gesture.BRIGHTNESS_UP) else "▼"
            log.debug(f"[BRIGHTNESS MODE] set_brightness({target}%)")
            return ActionResult(f"🎤 {direction} Brightness", f"{target}%")

        return None

    # ── Cursor dispatch ───────────────────────────────────────────────────────

    def _dispatch_cursor(
        self,
        g:      Gesture,
        result: GestureResult,
    ) -> Optional[ActionResult]:
        """
        Cursor control — active in all voice modes (own independent channel).
        CURSOR_MOVE fires every frame (no cooldown needed — pyautogui moveTo
        is non-blocking and fast).
        CURSOR_CLICK fires once per double-pinch (recogniser debounces it).
        """
        if g == Gesture.CURSOR_MOVE:
            sx = result.meta.get("sx")
            sy = result.meta.get("sy")
            if sx is not None and sy is not None:
                window_manager.cursor_move(int(sx), int(sy))
                # No ActionResult returned — cursor moves silently (no banner spam)
            return None

        if g == Gesture.CURSOR_CLICK:
            window_manager.cursor_click()
            return ActionResult("🖱 Cursor", "Click!")

        return None

    # ── Task-switch handler ───────────────────────────────────────────────────

    def _dispatch_task_switch(
        self,
        g:      Gesture,
        result: GestureResult,
    ) -> Optional[ActionResult]:
        """
        Translate task-switch gesture signals into Alt+Tab key sequences.

        TASK_SWITCH_OPEN   → hold Alt + press Tab  (shows task switcher)
        TASK_SWITCH_NEXT   → press Tab  (advance in switcher)
        TASK_SWITCH_PREV   → press Shift+Tab  (go back)
        TASK_SWITCH_COMMIT → release Alt  (select highlighted window)
        """
        if g == Gesture.TASK_SWITCH_OPEN:
            window_manager.task_switch_open()
            return ActionResult("⊞ Task Switch", "Opened")

        if g == Gesture.TASK_SWITCH_NEXT:
            if self._cd["task_nav"].reset_if_ready():
                window_manager.task_switch_next()
                return ActionResult("⊞ Task Switch", "→ Next")

        if g == Gesture.TASK_SWITCH_PREV:
            if self._cd["task_nav"].reset_if_ready():
                window_manager.task_switch_prev()
                return ActionResult("⊞ Task Switch", "← Prev")

        if g == Gesture.TASK_SWITCH_COMMIT:
            window_manager.task_switch_commit()
            return ActionResult("⊞ Task Switch", "Selected ✓")

        return None

    # ── General gestures — mode-independent ──────────────────────────────────

    def _dispatch_general(
        self,
        g:      Gesture,
        result: GestureResult,
    ) -> Optional[ActionResult]:
        """
        Non-pinch, non-task-switch gestures.
        These work identically in NONE, VOLUME, and BRIGHTNESS modes.
        """

        if g == Gesture.SCROLL_UP and self._cd["scroll"].reset_if_ready():
            dy     = abs(result.meta.get("dy", cfg.SCROLL_THRESHOLD_PX))
            clicks = max(2, min(8, int(dy / cfg.SCROLL_THRESHOLD_PX * 2)))
            window_manager.scroll_up(clicks)
            return ActionResult("⬆  Scroll", "Up")

        if g == Gesture.SCROLL_DOWN and self._cd["scroll"].reset_if_ready():
            dy     = abs(result.meta.get("dy", cfg.SCROLL_THRESHOLD_PX))
            clicks = max(2, min(8, int(dy / cfg.SCROLL_THRESHOLD_PX * 2)))
            window_manager.scroll_down(clicks)
            return ActionResult("⬇  Scroll", "Down")

        if g == Gesture.SWIPE_LEFT and self._cd["swipe"].reset_if_ready():
            window_manager.prev_window()
            return ActionResult("← Swipe", "Previous Window")

        if g == Gesture.SWIPE_RIGHT and self._cd["swipe"].reset_if_ready():
            window_manager.next_window()
            return ActionResult("→ Swipe", "Next Window")

        # Right hand fist hold → minimize window
        if g == Gesture.MINIMIZE and self._cd["minimize"].reset_if_ready():
            window_manager.minimize_window()
            return ActionResult("▼ Minimize", "Window minimised")

        # Left hand fist hold → show desktop  (CHANGED from open-palm)
        if g == Gesture.SHOW_DESKTOP and self._cd["desktop"].reset_if_ready():
            window_manager.show_desktop()
            return ActionResult("⊞ Desktop", "Showing desktop")

        # Left hand open palm → screenshot  (CHANGED from peace sign)
        if g == Gesture.SCREENSHOT and self._cd["screenshot"].reset_if_ready():
            window_manager.take_screenshot()
            return ActionResult("◉ Screenshot", "Saved to Desktop")

        # Right hand open palm → no action (silently ignored)
        if g == Gesture.OPEN_PALM:
            return None

        if g == Gesture.THUMBS_UP and self._cd["media"].reset_if_ready():
            window_manager.media_play_pause()
            return ActionResult("▶  Media", "Play / Pause")

        return None
