"""
core/overlay.py  –  v5
───────────────────────
HUD renderer with voice-mode badge and mic status indicator.

New in v5
──────────
• Voice mode badge (top-right): shows active lock — VOLUME / BRIGHTNESS / FREE
  Green  = volume locked
  Yellow = brightness locked
  Grey   = free mode (no lock)
• Mic indicator (top-right corner): pulsing dot when listening, dim when idle
• Last heard text: shows transcript of last recognised speech phrase
• Guide updated with voice commands
"""

from __future__ import annotations

import math
import threading
import time
import cv2
import numpy as np
from typing import List, Optional

from gestures.recognizer import Gesture, GestureResult
from actions.dispatcher  import ActionResult
from core.hand_detector  import HandData
from utils.logger        import get_logger
import config.settings as cfg

# Import VoiceMode once at module level — NOT inside render() every frame
try:
    from voice.listener import VoiceMode as _VM
    _VM_NONE       = _VM.NONE
    _VM_VOLUME     = _VM.VOLUME
    _VM_BRIGHTNESS = _VM.BRIGHTNESS
except ImportError:
    _VM = _VM_NONE = _VM_VOLUME = _VM_BRIGHTNESS = None

log = get_logger(__name__)

# ── Colours (BGR) ────────────────────────────────────────────────────────────
C_WHITE  = (255, 255, 255)
C_BLACK  = (0,   0,   0)
C_ACCENT = (0,   200, 255)
C_GREEN  = (50,  220, 80)
C_RED    = (50,  50,  220)
C_BLUE   = (220, 120, 50)
C_DARK   = (20,  20,  20)
C_PANEL  = (35,  35,  35)
C_YELLOW = (0,   220, 220)
C_PURPLE = (200, 80,  200)
C_PINK   = (180, 100, 255)
C_ORANGE = (0,   140, 255)
C_GREY   = (130, 130, 130)

FONT  = cv2.FONT_HERSHEY_SIMPLEX
FONTD = cv2.FONT_HERSHEY_DUPLEX

GESTURE_LABELS = {
    Gesture.NONE:               ("·",                    C_WHITE),
    Gesture.VOLUME_UP:          ("VOL  UP",              C_GREEN),
    Gesture.VOLUME_DOWN:        ("VOL  DOWN",            C_GREEN),
    Gesture.BRIGHTNESS_UP:      ("BRI  UP",              C_YELLOW),
    Gesture.BRIGHTNESS_DOWN:    ("BRI  DOWN",            C_YELLOW),
    Gesture.TASK_SWITCH_OPEN:   ("TASK SWITCH",          C_ACCENT),
    Gesture.TASK_SWITCH_NEXT:   ("TASK → NEXT",          C_ACCENT),
    Gesture.TASK_SWITCH_PREV:   ("TASK ← PREV",          C_ACCENT),
    Gesture.TASK_SWITCH_COMMIT: ("TASK ✓ SELECT",        C_GREEN),
    Gesture.CURSOR_MOVE:        ("CURSOR CONTROL",       C_ORANGE),
    Gesture.CURSOR_CLICK:       ("CURSOR  CLICK!",       C_ORANGE),
    Gesture.SCROLL_UP:          ("SCROLL  UP",           C_BLUE),
    Gesture.SCROLL_DOWN:        ("SCROLL  DOWN",         C_BLUE),
    Gesture.SWIPE_LEFT:         ("SWIPE  LEFT",          C_ACCENT),
    Gesture.SWIPE_RIGHT:        ("SWIPE  RIGHT",         C_ACCENT),
    Gesture.MINIMIZE:           ("MINIMIZE",             C_RED),
    Gesture.SHOW_DESKTOP:       ("SHOW  DESKTOP",        C_ACCENT),
    Gesture.SCREENSHOT:         ("SCREENSHOT",           C_PURPLE),
    Gesture.THUMBS_UP:          ("PLAY/PAUSE",           C_GREEN),
    Gesture.OPEN_PALM:          ("·",                    C_WHITE),   # right hand, no action
}

PINCH_GESTURES = {
    Gesture.VOLUME_UP, Gesture.VOLUME_DOWN,
    Gesture.BRIGHTNESS_UP, Gesture.BRIGHTNESS_DOWN,
}

TASK_GESTURES = {
    Gesture.TASK_SWITCH_OPEN, Gesture.TASK_SWITCH_NEXT,
    Gesture.TASK_SWITCH_PREV, Gesture.TASK_SWITCH_COMMIT,
}

CURSOR_GESTURES = {
    Gesture.CURSOR_MOVE, Gesture.CURSOR_CLICK,
}


class Overlay:
    def __init__(self, w: int, h: int):
        self.w = w
        self.h = h
        self._act_label:  str   = ""
        self._act_value:  str   = ""
        self._act_colour        = C_WHITE
        self._act_expire: float = 0.0
        self._show_guide: bool  = True
        self._vol:  int   = 50
        self._bri:  int   = 50
        self._frame_n: int = 0

        # Pre-allocate blend buffer to exact frame size — no per-frame alloc
        self._blend_buf = np.empty((h, w, 3), dtype=np.uint8)

        # Background thread syncs OS volume/brightness every 3 s
        # so _sync_levels() never blocks the main loop
        self._levels_lock = threading.Lock()
        self._sync_t = threading.Thread(
            target=self._level_sync_loop, daemon=True
        )
        self._sync_t.start()

        log.debug("Overlay ready.")

    # ── Public ────────────────────────────────────────────────────────────────

    def toggle_guide(self):
        self._show_guide = not self._show_guide

    def set_action(self, r: ActionResult):
        if not r:
            return
        self._act_label  = r.label
        self._act_value  = r.value
        self._act_expire = time.time() + cfg.FEEDBACK_DURATION_SEC
        lo = r.label.lower()
        if "volume" in lo or "vol" in lo:
            self._act_colour = C_GREEN
            try: self._vol = int(r.value.replace("%", ""))
            except: pass
        elif "brightness" in lo or "bri" in lo:
            self._act_colour = C_YELLOW
            try: self._bri = int(r.value.replace("%", ""))
            except: pass
        elif "swipe" in lo:   self._act_colour = C_ACCENT
        elif "scroll" in lo:  self._act_colour = C_BLUE
        elif "mini"   in lo:  self._act_colour = C_RED
        elif "screen" in lo:  self._act_colour = C_PURPLE
        elif "mute"   in lo:  self._act_colour = C_RED
        else:                 self._act_colour = C_WHITE

    def render(
        self,
        frame:       np.ndarray,
        gesture:     GestureResult,
        hands:       List[HandData],
        fps:         float,
        voice_state=None,
    ) -> np.ndarray:
        self._frame_n += 1

        # Update bars from gesture meta using module-level VoiceMode constants
        # (no import inside this hot path)
        if gesture.gesture in PINCH_GESTURES:
            t = gesture.meta.get("target")
            if t is not None and voice_state is not None:
                mode = voice_state.mode
                if mode is _VM_VOLUME:
                    self._vol = int(t)
                elif mode is _VM_BRIGHTNESS:
                    self._bri = int(t)

        # Draw layers
        self._draw_pinch_visual(frame, hands, gesture, voice_state)
        self._draw_header(frame)
        self._draw_fps(frame, fps)
        self._draw_gesture_name(frame, gesture)
        self._draw_voice_badge(frame, voice_state)
        self._draw_action_banner(frame)
        self._draw_bars(frame)
        if self._show_guide:
            self._draw_guide(frame)

        return frame

    # ── Background level sync — never called from main loop ──────────────────

    def _level_sync_loop(self):
        """Daemon thread: reads OS vol/bri every 3 s."""
        while True:
            time.sleep(3.0)
            try:
                from actions.volume import get_volume
                v = get_volume()
                if 0 <= v <= 100:
                    with self._levels_lock:
                        self._vol = v
            except Exception:
                pass
            try:
                from actions.brightness import get_brightness
                b = get_brightness()
                if 0 <= b <= 100:
                    with self._levels_lock:
                        self._bri = b
            except Exception:
                pass

    # ── Pinch visual + task-switch visual + cursor visual ────────────────────

    def _draw_pinch_visual(self, frame, hands, gesture, voice_state):
        # Use module-level _VM_* constants — VoiceMode not imported here
        mode = voice_state.mode if voice_state else _VM_NONE

        is_task   = gesture.gesture in TASK_GESTURES
        is_cursor = gesture.gesture in CURSOR_GESTURES

        for hand in hands:
            wx, wy = hand.lm_px(0)

            # Wrist label
            if is_cursor:
                label = f"{hand.handedness.upper()}  [CURSOR MODE]"
                lc    = C_ORANGE
            elif is_task:
                label = f"{hand.handedness.upper()}  [TASK SWITCH]"
                lc    = C_ACCENT
            elif mode is _VM_VOLUME:
                label = f"{hand.handedness.upper()}  [VOICE: VOLUME ONLY]"
                lc    = C_GREEN
            elif mode is _VM_BRIGHTNESS:
                label = f"{hand.handedness.upper()}  [VOICE: BRIGHTNESS ONLY]"
                lc    = C_YELLOW
            else:
                label = f"{hand.handedness.upper()}  [PINCH LOCKED]"
                lc    = C_RED

            cv2.putText(frame, label, (wx - 70, wy + 30),
                        FONT, 0.50, C_BLACK, 4, cv2.LINE_AA)
            cv2.putText(frame, label, (wx - 70, wy + 30),
                        FONT, 0.50, lc, 1, cv2.LINE_AA)

            # ── Cursor visual: thumb + MIDDLE midpoint ─────────────────────────
            if is_cursor:
                x1, y1 = hand.lm_px(4)    # thumb tip
                x3, y3 = hand.lm_px(12)   # middle tip (landmark 12)
                cx, cy = (x1 + x3) // 2, (y1 + y3) // 2
                cv2.circle(frame, (x1, y1), 9, C_ORANGE, cv2.FILLED)
                cv2.circle(frame, (x3, y3), 9, C_ORANGE, cv2.FILLED)
                cv2.line(frame, (x1, y1), (x3, y3), C_ORANGE, 2)
                cv2.circle(frame, (cx, cy), 12, C_ORANGE, 2, cv2.LINE_AA)
                cv2.line(frame, (cx - 8, cy), (cx + 8, cy), C_ORANGE, 1)
                cv2.line(frame, (cx, cy - 8), (cx, cy + 8), C_ORANGE, 1)
                if gesture.gesture == Gesture.CURSOR_CLICK:
                    cv2.circle(frame, (cx, cy), 20, C_WHITE, 3, cv2.LINE_AA)
                continue

            # ── Task-switch visual ─────────────────────────────────────────────
            x1, y1 = hand.lm_px(4)
            x2, y2 = hand.lm_px(8)
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

            if is_task:
                if gesture.gesture == Gesture.TASK_SWITCH_COMMIT:
                    cv2.circle(frame, (cx, cy), 18, C_GREEN, 3, cv2.LINE_AA)
                else:
                    cv2.circle(frame, (cx, cy), 14, C_ACCENT, 2, cv2.LINE_AA)
                cv2.circle(frame, (x1, y1), 8, C_ACCENT, cv2.FILLED)
                cv2.circle(frame, (x2, y2), 8, C_ACCENT, cv2.FILLED)
                cv2.line(frame, (x1, y1), (x2, y2), C_ACCENT, 2)
                continue

            # ── Vol/bri pinch visual ───────────────────────────────────────────
            if gesture.gesture not in PINCH_GESTURES:
                continue
            if mode is _VM_NONE or mode is None:
                continue   # pinch disabled — no visual

            cv2.circle(frame, (x1, y1), 10, C_PINK, cv2.FILLED)
            cv2.circle(frame, (x2, y2), 10, C_PINK, cv2.FILLED)
            cv2.line(frame, (x1, y1), (x2, y2), C_PINK, 2)

            dist = gesture.meta.get("dist", 60)
            dot_colour = C_GREEN if dist < cfg.PINCH_MIN_PX + 8 else C_PINK
            cv2.circle(frame, (cx, cy), 10, dot_colour, cv2.FILLED)

    # ── Header ────────────────────────────────────────────────────────────────

    def _draw_header(self, frame):
        cv2.rectangle(frame, (0, 0), (self.w, 35), C_DARK, -1)
        cv2.putText(frame,
                    "GestureFlow  |  Q=quit  G=guide  P=pause  S=shot",
                    (10, 23), FONT, 0.47, C_WHITE, 1, cv2.LINE_AA)

    # ── FPS ───────────────────────────────────────────────────────────────────

    def _draw_fps(self, frame, fps):
        txt = f"FPS: {int(fps)}"
        cv2.putText(frame, txt, (8, 58), FONT, 0.65, C_BLACK, 4, cv2.LINE_AA)
        cv2.putText(frame, txt, (8, 58), FONT, 0.65, C_ACCENT, 1, cv2.LINE_AA)

    # ── Gesture name ──────────────────────────────────────────────────────────

    def _draw_gesture_name(self, frame, gesture):
        label, colour = GESTURE_LABELS.get(gesture.gesture, ("?", C_WHITE))
        if label == "·":
            return

        x, y = self.w // 2, 70
        (tw, th), _ = cv2.getTextSize(label, FONTD, 0.85, 2)
        pad = 12
        cv2.rectangle(frame,
                      (x - tw//2 - pad, y - th - 6),
                      (x + tw//2 + pad, y + 8), C_DARK, -1)
        cv2.putText(frame, label, (x - tw//2, y),
                    FONTD, 0.85, colour, 2, cv2.LINE_AA)

        if gesture.confidence > 0.05:
            bw   = tw + pad * 2
            bx   = x - bw // 2
            by   = y + 12
            fill = int(bw * min(1.0, gesture.confidence))
            cv2.rectangle(frame, (bx, by), (bx + bw, by + 5), C_PANEL, -1)
            cv2.rectangle(frame, (bx, by), (bx + fill, by + 5), colour, -1)

    # ── Voice mode badge ──────────────────────────────────────────────────────

    def _draw_voice_badge(self, frame, voice_state):
        """
        Top-right area: voice mode badge + mic dot + last heard phrase.
        Shows nothing when voice_state is None (voice disabled/unavailable).
        """
        if voice_state is None:
            # Voice not available — show a static grey "NO VOICE" badge
            badge_txt = "  NO VOICE  "
            (tw, th), _ = cv2.getTextSize(badge_txt, FONT, 0.48, 1)
            bx = self.w - tw - 20
            by = 42
            cv2.rectangle(frame, (bx, by), (bx + tw + 8, by + th + 10), C_DARK, -1)
            cv2.rectangle(frame, (bx, by), (bx + tw + 8, by + th + 10), C_GREY, 1)
            cv2.putText(frame, badge_txt, (bx + 4, by + th + 4),
                        FONT, 0.48, C_GREY, 1, cv2.LINE_AA)
            return

        # Use module-level _VM_* constants — no import here
        mode      = voice_state.mode
        listening = voice_state.listening
        heard     = voice_state.last_heard
        error     = voice_state.error

        bx = self.w - 215
        by = 42

        if mode is _VM_VOLUME:
            badge_txt  = "  VOLUME MODE  "
            badge_col  = C_GREEN
            border_col = C_GREEN
        elif mode is _VM_BRIGHTNESS:
            badge_txt  = "  BRIGHTNESS MODE  "
            badge_col  = C_YELLOW
            border_col = C_YELLOW
        else:
            badge_txt  = "  PINCH DISABLED  "
            badge_col  = C_RED
            border_col = C_RED

        (tw, th), _ = cv2.getTextSize(badge_txt, FONT, 0.52, 1)
        rx1, ry1 = bx, by
        rx2, ry2 = bx + tw + 8, by + th + 10

        cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), C_DARK, -1)
        cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), border_col, 2)
        cv2.putText(frame, badge_txt, (rx1 + 4, ry2 - 4),
                    FONT, 0.52, badge_col, 1, cv2.LINE_AA)

        dot_x = rx2 + 14
        dot_y = (ry1 + ry2) // 2
        if listening:
            pulse = int(6 + 4 * abs(math.sin(self._frame_n * 0.15)))
            cv2.circle(frame, (dot_x, dot_y), pulse, C_RED, -1, cv2.LINE_AA)
            cv2.putText(frame, "MIC", (dot_x + 14, dot_y + 5),
                        FONT, 0.38, C_RED, 1, cv2.LINE_AA)
        else:
            cv2.circle(frame, (dot_x, dot_y), 6, C_GREY, -1, cv2.LINE_AA)

        if heard:
            heard_short = heard[:30] + "…" if len(heard) > 30 else heard
            cv2.putText(frame, f'"{heard_short}"',
                        (bx, ry2 + 18), FONT, 0.40, C_GREY, 1, cv2.LINE_AA)

        if error:
            cv2.putText(frame, f"! {error[:35]}",
                        (bx, ry2 + 34), FONT, 0.38, C_ORANGE, 1, cv2.LINE_AA)

    # ── Action feedback banner ────────────────────────────────────────────────

    def _draw_action_banner(self, frame):
        if time.time() > self._act_expire:
            return
        remaining = self._act_expire - time.time()
        alpha = min(1.0, remaining / max(0.1, cfg.FEEDBACK_DURATION_SEC * 0.35))

        bh, bw = 62, 400
        bx = self.w // 2 - bw // 2
        by = self.h - bh - 14

        roi = frame[by:by+bh, bx:bx+bw]
        if roi.shape[0] > 0 and roi.shape[1] > 0:
            bg = np.zeros_like(roi)
            cv2.addWeighted(bg, alpha * 0.82, roi, 1 - alpha * 0.82, 0, roi)

        cv2.putText(frame, self._act_label,
                    (bx + 14, by + 24), FONT, 0.65, self._act_colour, 2, cv2.LINE_AA)
        cv2.putText(frame, self._act_value,
                    (bx + 14, by + 52), FONTD, 0.90, C_WHITE, 2, cv2.LINE_AA)

    # ── Level bars ────────────────────────────────────────────────────────────

    def _draw_bars(self, frame):
        bw, bh = 22, int(self.h * 0.45)
        y_top  = self.h // 2 - bh // 2
        x_vol  = self.w - 54
        x_bri  = self.w - 26

        for x, pct, letter, colour in [
            (x_vol, self._vol, "V", C_GREEN),
            (x_bri, self._bri, "B", C_YELLOW),
        ]:
            pct = max(0, min(100, pct))
            cv2.rectangle(frame, (x, y_top), (x+bw, y_top+bh), C_PANEL, -1)
            fh = int(bh * pct / 100)
            if fh > 0:
                cv2.rectangle(frame,
                              (x, y_top+bh-fh), (x+bw, y_top+bh), colour, -1)
            cv2.rectangle(frame, (x, y_top), (x+bw, y_top+bh), C_WHITE, 1)
            cv2.putText(frame, letter, (x+5, y_top-6),
                        FONT, 0.48, colour, 1, cv2.LINE_AA)
            cv2.putText(frame, f"{pct}%", (x-2, y_top+bh+16),
                        FONT, 0.42, colour, 1, cv2.LINE_AA)

    # ── Guide panel ───────────────────────────────────────────────────────────

    def _draw_guide(self, frame):
        lines = [
            ("── GESTURE GUIDE ──",              C_ACCENT),
            ("Swipe Right = Next Window",        C_ACCENT),
            ("Swipe Left  = Prev Window",        C_ACCENT),
            ("2 fingers up+move = Scroll",       C_BLUE),
            ("R fist hold = Minimize",           C_RED),
            ("L fist hold = Show Desktop",       C_ACCENT),
            ("L open palm = Screenshot",         C_PURPLE),
            ("Thumbs Up   = Play/Pause",         C_GREEN),
            ("── TASK SWITCH ──",                C_ACCENT),
            ("Pinch(idx) tight → Alt+Tab",       C_ACCENT),
            ("Drag RIGHT → next window",         C_ACCENT),
            ("Drag LEFT  → prev window",         C_ACCENT),
            ("Open pinch → confirm select",      C_GREEN),
            ("── CURSOR CONTROL ──",             C_ORANGE),
            ("Pinch THUMB+MIDDLE → cursor",      C_ORANGE),
            ("Move hand → cursor follows",       C_ORANGE),
            ("Double pinch → left click",        C_ORANGE),
            ("── VOICE PINCH ──",                C_ORANGE),
            ("Default: index pinch LOCKED",      C_RED),
            ('Say "volume"     → VOL mode',      C_GREEN),
            ('Say "brightness" → BRI mode',      C_YELLOW),
            ('Say "lock"  → disable pinch',      C_RED),
            ('Say "mute"  → instant mute',       C_RED),
            ("[G] guide  [P] pause  [Q] quit",   C_WHITE),
        ]

        lh  = 15
        pad = 5
        pw  = 272
        ph  = len(lines) * lh + pad * 2
        px  = 6
        py  = self.h - ph - 6

        roi = frame[py:py+ph, px:px+pw]
        if roi.shape[0] > 0 and roi.shape[1] > 0:
            bg = np.full_like(roi, 18)
            cv2.addWeighted(bg, 0.82, roi, 0.18, 0, roi)

        header_rows = {0, 8, 13, 17}  # "GESTURE GUIDE", "TASK SWITCH", "CURSOR CONTROL", "VOICE PINCH"
        for i, (text, colour) in enumerate(lines):
            ty     = py + pad + i * lh + 11
            is_hdr = i in header_rows
            scale  = 0.45 if is_hdr else 0.41
            weight = 2 if is_hdr else 1
            cv2.putText(frame, text, (px+6, ty),
                        FONT, scale, colour, weight, cv2.LINE_AA)
