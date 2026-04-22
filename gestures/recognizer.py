"""
gestures/recognizer.py  –  v8
───────────────────────────────

Gesture catalogue
─────────────────
  VOLUME_UP / DOWN         thumb+index spread/close, right hand
  BRIGHTNESS_UP / DOWN     thumb+index spread/close, left hand
  TASK_SWITCH_OPEN         thumb+index tight pinch → enters Alt+Tab
  TASK_SWITCH_NEXT         drag RIGHT while task pinch held → next window
  TASK_SWITCH_PREV         drag LEFT  while task pinch held → prev window
  TASK_SWITCH_COMMIT       release task pinch → confirm selection
  CURSOR_MOVE              thumb+middle pinch held → cursor follows hand
  CURSOR_CLICK             double thumb+middle pinch → left click
  SCROLL_UP / DOWN         index+middle up, hand moving vertically
  SWIPE_LEFT / RIGHT       3+ fingers open, horizontal sweep
  MINIMIZE                 closed fist held ≥ FIST_HOLD_FRAMES
  SCREENSHOT               peace sign held still ≥ PEACE_HOLD_FRAMES
  THUMBS_UP                thumb only up → play/pause
  OPEN_PALM                all 5 up → show desktop

Fix 1 — Task switch direction
──────────────────────────────
  Old (wrong): left drag → NEXT,  right drag → PREV
  New (correct):
    Drag RIGHT → TASK_SWITCH_NEXT  (Tab          → moves selector right/forward)
    Drag LEFT  → TASK_SWITCH_PREV  (Shift+Tab    → moves selector left/backward)
  Rationale: hand moving right mirrors the selector moving right in the
  Alt+Tab overlay. Intuitive, matches user expectation.

Fix 2 — Cursor control
──────────────────────
  Gesture: thumb tip + MIDDLE finger tip close (< CURSOR_PINCH_PX px).
  This is physically and metrically distinct:
    • thumb+index  → vol/bri/task (index = landmark 8)
    • thumb+middle → cursor        (middle = landmark 12)
  While pinch held: index finger tip pixel position is tracked with EMA
  smoothing and mapped to screen coordinates proportionally.
  Relative movement: the screen anchor is set when cursor mode is entered,
  and hand movement from that anchor is scaled by CURSOR_SENSITIVITY.
  Double-pinch: two close-open cycles within DOUBLE_PINCH_WINDOW seconds
  emit CURSOR_CLICK.

Conflict isolation table
─────────────────────────
  Gesture             Trigger fingers      Active modes
  ──────────────────  ───────────────────  ────────────────────────
  Vol / Bri           thumb + index        VOLUME or BRIGHTNESS only
  Task switch         thumb + index (tight) NONE only (dispatcher gate)
  Cursor move/click   thumb + MIDDLE       all modes (own sub-state)
  Scroll              index + middle UP    any
  Swipe               3+ fingers open      any
  Fist                all down             any
  Cursor vs Task:     task uses index, cursor uses middle — can't conflict
  Cursor vs Scroll:   scroll needs BOTH index+middle UP; cursor needs middle
                      CLOSED toward thumb — opposite states, no conflict
"""

from __future__ import annotations

import math
import time
import numpy as np
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Deque, Dict, List, Tuple

from core.hand_detector import HandData
from utils.logger import get_logger
import config.settings as cfg

log = get_logger(__name__)


# ── Gesture enum ──────────────────────────────────────────────────────────────

class Gesture(Enum):
    NONE              = auto()
    VOLUME_UP         = auto()
    VOLUME_DOWN       = auto()
    BRIGHTNESS_UP     = auto()
    BRIGHTNESS_DOWN   = auto()
    TASK_SWITCH_OPEN  = auto()
    TASK_SWITCH_NEXT  = auto()   # drag RIGHT → move selector right (forward)
    TASK_SWITCH_PREV  = auto()   # drag LEFT  → move selector left  (backward)
    TASK_SWITCH_COMMIT= auto()
    CURSOR_MOVE       = auto()   # meta: {'sx': int, 'sy': int} screen coords
    CURSOR_CLICK      = auto()   # double-pinch left-click
    SCROLL_UP         = auto()
    SCROLL_DOWN       = auto()
    SWIPE_LEFT        = auto()
    SWIPE_RIGHT       = auto()
    MINIMIZE          = auto()   # right hand fist hold
    SHOW_DESKTOP      = auto()   # LEFT hand fist hold  (NEW)
    SCREENSHOT        = auto()   # LEFT hand open palm  (CHANGED from peace sign)
    THUMBS_UP         = auto()
    OPEN_PALM         = auto()   # right hand open palm (no action by default)


@dataclass
class GestureResult:
    gesture:    Gesture = Gesture.NONE
    confidence: float   = 0.0
    meta:       Dict    = field(default_factory=dict)


# ── Sub-state enums ───────────────────────────────────────────────────────────

class _TSState(Enum):
    IDLE   = "idle"
    ACTIVE = "active"

class _CursorState(Enum):
    IDLE   = "idle"
    ACTIVE = "active"   # thumb+middle pinch is closed


# ── Per-hand state ────────────────────────────────────────────────────────────

class _HandState:
    def __init__(self):
        # Vol / bri EMA
        self.smooth_vol: float = -1.0
        self.smooth_bri: float = -1.0

        # Scroll
        self.prev_palm_y: int = -1

        # Swipe
        self.prev_palm_x:     int = -1
        self.swipe_start_x:   int = -1
        self.swipe_frames:    int = 0
        self.swipe_dir:       str = ""
        self.swipe_count_opp: int = 0

        # Task switcher
        self.ts_state:      _TSState = _TSState.IDLE
        self.ts_last_nav_x: int      = -1
        self.ts_nav_accum:  int      = 0

        # Cursor control
        self.cur_state:        _CursorState = _CursorState.IDLE
        self.cur_smooth_x:     float        = -1.0   # EMA screen x
        self.cur_smooth_y:     float        = -1.0   # EMA screen y
        self.cur_anchor_fx:    float        = -1.0   # normalised x when entered
        self.cur_anchor_fy:    float        = -1.0   # normalised y when entered
        self.cur_anchor_sx:    int          = -1     # screen x when entered
        self.cur_anchor_sy:    int          = -1     # screen y when entered
        # Double-pinch detection — 3-stage state machine
        # Stage 0: idle (waiting for first close)
        # Stage 1: first close recorded, waiting for first open
        # Stage 2: first open recorded, waiting for second close → CLICK
        self.dp_stage:      int   = 0
        self.dp_close_1_t:  float = 0.0   # time of first close
        self.dp_open_t:     float = 0.0   # time of first open

        # Hold counters
        self.fist_frames:  int = 0
        self.peace_frames: int = 0

        # Still-hand detector
        self.still_buf: Deque[int] = deque(maxlen=10)

    # ── Reset helpers ─────────────────────────────────────────────────────────

    def reset_pinch_smooth(self):
        self.smooth_vol = -1.0
        self.smooth_bri = -1.0

    def reset_swipe(self):
        self.swipe_dir       = ""
        self.swipe_frames    = 0
        self.swipe_start_x   = self.prev_palm_x
        self.swipe_count_opp = 0

    def reset_task_switch(self):
        self.ts_state      = _TSState.IDLE
        self.ts_last_nav_x = -1
        self.ts_nav_accum  = 0

    def reset_cursor(self):
        self.cur_state     = _CursorState.IDLE
        self.cur_smooth_x  = -1.0
        self.cur_smooth_y  = -1.0
        self.cur_anchor_fx = -1.0
        self.cur_anchor_fy = -1.0
        self.cur_anchor_sx = -1
        self.cur_anchor_sy = -1
        self.dp_stage      = 0
        self.dp_close_1_t  = 0.0
        self.dp_open_t     = 0.0


# ── Recogniser ────────────────────────────────────────────────────────────────

class GestureRecognizer:
    """
    Pure recogniser — no OS calls, no VoiceMode awareness.
    Dispatcher enforces mode-based filtering.
    """

    def __init__(self):
        self._states: Dict[str, _HandState] = {
            "Right": _HandState(),
            "Left":  _HandState(),
        }
        self._screen_w: int = 1920
        self._screen_h: int = 1080
        try:
            import pyautogui
            sw, sh = pyautogui.size()
            self._screen_w, self._screen_h = sw, sh
        except Exception:
            pass
        log.info(
            f"GestureRecognizer v8 ready.  "
            f"Screen: {self._screen_w}×{self._screen_h}"
        )

    # ── Public ────────────────────────────────────────────────────────────────

    def recognise(self, hands: List[HandData]) -> GestureResult:
        if not hands:
            self._decay_all()
            # Commit any active task switch when hand disappears
            for state in self._states.values():
                if state.ts_state == _TSState.ACTIVE:
                    state.reset_task_switch()
                    return GestureResult(Gesture.TASK_SWITCH_COMMIT, 1.0,
                                        {"reason": "hand_lost"})
            return GestureResult()

        for hand in hands:
            state  = self._states[hand.handedness]
            result = self._process(hand, state)
            if result.gesture != Gesture.NONE:
                return result

        return GestureResult()

    # ── Per-hand processing ───────────────────────────────────────────────────

    def _process(self, hand: HandData, state: _HandState) -> GestureResult:
        fingers      = hand.fingers_up()       # [thumb,idx,mid,ring,pinky]
        px, py       = hand.palm_center_px()
        n_up         = sum(fingers)
        idx_dist_px  = hand.pinch_distance_px()           # thumb ↔ index
        mid_dist_px  = hand.middle_pinch_distance_px()    # thumb ↔ middle

        state.still_buf.append(py)

        # ══════════════════════════════════════════════════════════════════════
        # P0 — Task-switch CONTINUATION (index-pinch held)
        # Hand is fully reserved while ts_state == ACTIVE.
        # ══════════════════════════════════════════════════════════════════════
        if state.ts_state == _TSState.ACTIVE:
            return self._continue_task_switch(state, idx_dist_px, px)

        # ══════════════════════════════════════════════════════════════════════
        # P1 — Cursor control (thumb+MIDDLE pinch) — checked before everything
        # else so a cursor pinch is never mis-classified as something else.
        # ══════════════════════════════════════════════════════════════════════
        cursor_result = self._process_cursor(hand, state, mid_dist_px)
        if cursor_result.gesture != Gesture.NONE:
            return cursor_result


        # ══════════════════════════════════════════════════════════════════════
        # P2 — Fist (all fingers down, n_up == 0)
        #
        #   LEFT  hand fist held → SHOW_DESKTOP   (show desktop / all windows)
        #   RIGHT hand fist held → MINIMIZE        (minimize current window)
        #
        # Both require FIST_HOLD_FRAMES consecutive frames to fire so a
        # natural hand-close mid-gesture doesn't trigger accidentally.
        # ══════════════════════════════════════════════════════════════════════
        if n_up == 0:
            state.fist_frames += 1
            state._reset_non_fist(px, py)
            if state.fist_frames >= cfg.FIST_HOLD_FRAMES:
                state.fist_frames = 0
                if hand.handedness == "Left":
                    return GestureResult(Gesture.SHOW_DESKTOP, 1.0)
                else:
                    return GestureResult(Gesture.MINIMIZE, 1.0)
            return GestureResult()
        else:
            state.fist_frames = 0

        # ══════════════════════════════════════════════════════════════════════
        # P3 — Task-switch ENTRY
        # Only when: thumb+index tight AND ring+pinky NOT both down
        # (prevents fist-to-task-switch confusion mid-close)
        # ══════════════════════════════════════════════════════════════════════
        ring_pinky_down = (not fingers[3]) and (not fingers[4])
        if idx_dist_px < cfg.TASK_PINCH_PX and not ring_pinky_down:
            state.ts_state      = _TSState.ACTIVE
            state.ts_last_nav_x = px
            state.ts_nav_accum  = 0
            state.reset_pinch_smooth()
            log.debug(f"Task switch ENTERED x={px}")
            return GestureResult(Gesture.TASK_SWITCH_OPEN, 1.0,
                                 {"x": px, "hand": hand.handedness})

        # ══════════════════════════════════════════════════════════════════════
        # P4 — Open palm (all 5 fingers up, n_up == 5)
        #
        #   LEFT  hand open palm → SCREENSHOT  (instant — no hold required)
        #   RIGHT hand open palm → OPEN_PALM   (unassigned; dispatcher ignores)
        #
        # Left open palm fires immediately because spreading all 5 fingers
        # wide is a deliberate, unambiguous pose that is never accidental.
        # ══════════════════════════════════════════════════════════════════════
        if n_up == 5:
            state._reset_non_fist(px, py)
            if hand.handedness == "Left":
                return GestureResult(Gesture.SCREENSHOT, 1.0)
            else:
                return GestureResult(Gesture.OPEN_PALM, 0.95)

        # ══════════════════════════════════════════════════════════════════════
        # P5 — Thumbs-up only → PLAY/PAUSE
        # ══════════════════════════════════════════════════════════════════════
        if fingers == [True, False, False, False, False]:
            _, iy = hand.lm_px(8)
            _, wy = hand.lm_px(0)
            if iy > wy:
                state._reset_non_fist(px, py)
                return GestureResult(Gesture.THUMBS_UP, 0.90)

        # ── P6 (peace sign screenshot) removed in v9 ─────────────────────────
        # Screenshot is now left open-palm (P4 above).
        # Peace sign [F,T,T,F,F] falls through to scroll / pinch detection.

        # ══════════════════════════════════════════════════════════════════════
        # P7 — Pinch vol / bri  (thumb+index, PINCH_MIN..PINCH_MAX range)
        # ══════════════════════════════════════════════════════════════════════
        if cfg.PINCH_MIN_PX <= idx_dist_px <= cfg.PINCH_MAX_PX:
            result = self._pinch_vol_bri(hand, state, idx_dist_px, px, py)
            if result.gesture != Gesture.NONE:
                return result
        else:
            state.reset_pinch_smooth()

        # ══════════════════════════════════════════════════════════════════════
        # P8 — Scroll (index + middle up, vertical movement)
        # Guard: middle finger must be OPEN (up), which is the opposite of
        # the cursor pinch where middle is CLOSED → zero conflict.
        # ══════════════════════════════════════════════════════════════════════
        if fingers[1] and fingers[2]:
            result = self._check_scroll(state, py)
            state.prev_palm_y = py
            state.prev_palm_x = px
            return result

        # ══════════════════════════════════════════════════════════════════════
        # P9 — Swipe (3+ fingers open, horizontal)
        # ══════════════════════════════════════════════════════════════════════
        if n_up >= 3:
            result = self._check_swipe(state, px)
            state.prev_palm_x = px
            state.prev_palm_y = py
            return result

        state.prev_palm_x = px
        state.prev_palm_y = py
        return GestureResult()

    # ══════════════════════════════════════════════════════════════════════════
    # CURSOR CONTROL — thumb + middle pinch
    # ══════════════════════════════════════════════════════════════════════════

    def _process_cursor(
        self,
        hand:        HandData,
        state:       _HandState,
        mid_dist_px: float,
    ) -> GestureResult:
        """
        Cursor control via thumb+middle pinch.

        Double-pinch click — fixed state machine
        ──────────────────────────────────────────
        Previous bug: dp_was_closed was set True on entry into ACTIVE,
        then on every release it checked dp_last_open_t and fired a click
        even on the very first release because the window condition was met
        from a previous session's timestamp.

        Fixed sequence (3 stages, no false positives):
          Stage 0 (IDLE):
            dp_stage = 0  ← waiting for first pinch

          Stage 1 (first close detected):
            dp_stage = 1
            Record dp_close_1_t = now

          Stage 2 (first release — within DOUBLE_PINCH_WINDOW of close):
            dp_stage = 2
            Record dp_open_t = now
            Only if (now - dp_close_1_t) < DOUBLE_PINCH_WINDOW

          Stage 3 (second close — within DOUBLE_PINCH_WINDOW of first open):
            if (now - dp_open_t) < DOUBLE_PINCH_WINDOW → emit CURSOR_CLICK
            Reset dp_stage = 0

        Any gap > DOUBLE_PINCH_WINDOW resets to Stage 0.
        This guarantees exactly one click per intentional double-pinch.
        """
        now         = time.time()
        is_closed   = mid_dist_px < cfg.CURSOR_PINCH_PX
        alpha       = cfg.CURSOR_SMOOTH
        sw, sh      = self._screen_w, self._screen_h
        sensitivity = cfg.CURSOR_SENSITIVITY

        # ── ACTIVE: cursor pinch is currently held ────────────────────────────
        if state.cur_state == _CursorState.ACTIVE:
            if not is_closed:
                # Pinch opened → exit cursor active mode
                state.cur_state = _CursorState.IDLE

                # Double-pinch stage 1→2: first release after first close
                if state.dp_stage == 1:
                    if (now - state.dp_close_1_t) < cfg.DOUBLE_PINCH_WINDOW:
                        state.dp_stage  = 2
                        state.dp_open_t = now
                    else:
                        state.dp_stage = 0   # too slow — reset

                return GestureResult()

            # Still closed — emit CURSOR_MOVE with EMA position
            tip_x_norm = hand.lm(8).x
            tip_y_norm = hand.lm(8).y

            raw_sx = state.cur_anchor_sx + (tip_x_norm - state.cur_anchor_fx) * sw * sensitivity
            raw_sy = state.cur_anchor_sy + (tip_y_norm - state.cur_anchor_fy) * sh * sensitivity
            raw_sx = max(0.0, min(float(sw - 1), raw_sx))
            raw_sy = max(0.0, min(float(sh - 1), raw_sy))

            if state.cur_smooth_x < 0:
                state.cur_smooth_x = raw_sx
                state.cur_smooth_y = raw_sy
            else:
                state.cur_smooth_x += (raw_sx - state.cur_smooth_x) * alpha
                state.cur_smooth_y += (raw_sy - state.cur_smooth_y) * alpha

            sx = int(round(state.cur_smooth_x))
            sy = int(round(state.cur_smooth_y))
            return GestureResult(Gesture.CURSOR_MOVE, 1.0,
                                 {"sx": sx, "sy": sy, "dist": mid_dist_px})

        # ── IDLE: check for cursor entry ──────────────────────────────────────
        if is_closed:
            # Get current mouse position as anchor
            try:
                import pyautogui
                cur_sx, cur_sy = pyautogui.position()
            except Exception:
                cur_sx, cur_sy = sw // 2, sh // 2

            tip_x_norm = hand.lm(8).x
            tip_y_norm = hand.lm(8).y

            state.cur_state     = _CursorState.ACTIVE
            state.cur_anchor_fx = tip_x_norm
            state.cur_anchor_fy = tip_y_norm
            state.cur_anchor_sx = cur_sx
            state.cur_anchor_sy = cur_sy
            state.cur_smooth_x  = float(cur_sx)
            state.cur_smooth_y  = float(cur_sy)

            # Double-pinch stage 0→1 or stage 2→click
            if state.dp_stage == 0:
                # First close — begin double-pinch sequence
                state.dp_stage     = 1
                state.dp_close_1_t = now

            elif state.dp_stage == 2:
                # Second close — check timing for double-pinch
                if (now - state.dp_open_t) < cfg.DOUBLE_PINCH_WINDOW:
                    # Valid double-pinch! Reset and fire click on next open.
                    state.dp_stage     = 0
                    # Return click immediately on second pinch-close
                    log.debug("Cursor: DOUBLE PINCH → CLICK")
                    return GestureResult(Gesture.CURSOR_CLICK, 1.0)
                else:
                    # Second close was too late — treat as new first close
                    state.dp_stage     = 1
                    state.dp_close_1_t = now

            return GestureResult(Gesture.CURSOR_MOVE, 1.0,
                                 {"sx": cur_sx, "sy": cur_sy,
                                  "dist": mid_dist_px})

        # Stale dp_stage — expire if window has passed
        if state.dp_stage > 0:
            ref_t = state.dp_open_t if state.dp_stage == 2 else state.dp_close_1_t
            if (now - ref_t) > cfg.DOUBLE_PINCH_WINDOW * 2:
                state.dp_stage = 0

        return GestureResult()

    # ══════════════════════════════════════════════════════════════════════════
    # TASK SWITCH CONTINUATION
    # ══════════════════════════════════════════════════════════════════════════

    def _continue_task_switch(
        self,
        state:       _HandState,
        idx_dist_px: float,
        px:          int,
    ) -> GestureResult:
        """
        Called every frame while ts_state == ACTIVE.

        COMMIT when pinch opens (dist > PINCH_MIN_PX).

        Navigation direction  (FIX v8 — was reversed in v7)
        ─────────────────────
          Hand moves RIGHT (px increases) → selector moves RIGHT → NEXT window
            → calls task_switch_next() → presses Tab while Alt held
          Hand moves LEFT  (px decreases) → selector moves LEFT → PREV window
            → calls task_switch_prev() → presses Shift+Tab while Alt held

          This matches the visual Alt+Tab overlay: selector highlights move
          rightward as you press Tab, leftward as you press Shift+Tab.
        """
        # Release: pinch opened
        if idx_dist_px > cfg.PINCH_MIN_PX:
            log.debug(f"Task switch COMMIT (dist={idx_dist_px:.0f})")
            state.reset_task_switch()
            return GestureResult(Gesture.TASK_SWITCH_COMMIT, 1.0)

        if state.ts_last_nav_x < 0:
            state.ts_last_nav_x = px
            return GestureResult()

        dx = px - state.ts_last_nav_x
        state.ts_nav_accum += dx

        result = GestureResult()

        if abs(state.ts_nav_accum) >= cfg.TASK_NAV_PX:
            if state.ts_nav_accum > 0:
                # Hand moved RIGHT → NEXT window (Tab)
                result = GestureResult(Gesture.TASK_SWITCH_NEXT, 0.9,
                                       {"dx": state.ts_nav_accum})
            else:
                # Hand moved LEFT → PREV window (Shift+Tab)
                result = GestureResult(Gesture.TASK_SWITCH_PREV, 0.9,
                                       {"dx": state.ts_nav_accum})

            remainder          = abs(state.ts_nav_accum) % cfg.TASK_NAV_PX
            state.ts_nav_accum = int(math.copysign(remainder, state.ts_nav_accum))

        state.ts_last_nav_x = px
        return result

    # ── Vol / Bri pinch mapping ───────────────────────────────────────────────

    def _pinch_vol_bri(
        self,
        hand:       HandData,
        state:      _HandState,
        dist_px:    float,
        px:         int,
        py:         int,
    ) -> GestureResult:
        raw = float(np.interp(dist_px,
                              [cfg.PINCH_MIN_PX, cfg.PINCH_MAX_PX], [0, 100]))
        k   = 1.0 / max(1, cfg.PINCH_SMOOTH)

        if hand.handedness == "Right":
            if state.smooth_vol < 0:
                state.smooth_vol = raw
            state.smooth_vol += (raw - state.smooth_vol) * k
            target  = int(round(state.smooth_vol))
            gesture = (Gesture.VOLUME_UP if raw >= state.smooth_vol - 1
                       else Gesture.VOLUME_DOWN)
            state._reset_scroll_swipe(px, py)
            return GestureResult(gesture, min(1.0, dist_px / cfg.PINCH_MAX_PX),
                                 {"target": target, "dist": dist_px})
        else:
            if state.smooth_bri < 0:
                state.smooth_bri = raw
            state.smooth_bri += (raw - state.smooth_bri) * k
            target  = int(round(state.smooth_bri))
            gesture = (Gesture.BRIGHTNESS_UP if raw >= state.smooth_bri - 1
                       else Gesture.BRIGHTNESS_DOWN)
            state._reset_scroll_swipe(px, py)
            return GestureResult(gesture, min(1.0, dist_px / cfg.PINCH_MAX_PX),
                                 {"target": target, "dist": dist_px})

    # ── Scroll ────────────────────────────────────────────────────────────────

    def _check_scroll(self, state: _HandState, py: int) -> GestureResult:
        if state.prev_palm_y < 0:
            state.prev_palm_y = py
            return GestureResult()
        dy = py - state.prev_palm_y
        if abs(dy) >= cfg.SCROLL_THRESHOLD_PX:
            g    = Gesture.SCROLL_DOWN if dy > 0 else Gesture.SCROLL_UP
            conf = min(1.0, abs(dy) / (cfg.SCROLL_THRESHOLD_PX * 4))
            return GestureResult(g, conf, {"dy": dy})
        return GestureResult()

    # ── Swipe ─────────────────────────────────────────────────────────────────

    def _check_swipe(self, state: _HandState, px: int) -> GestureResult:
        if state.prev_palm_x < 0:
            state.prev_palm_x   = px
            state.swipe_start_x = px
            return GestureResult()

        dx = px - state.prev_palm_x

        if abs(dx) > 5:
            direction = "right" if dx > 0 else "left"

            if state.swipe_dir == "" or state.swipe_dir == direction:
                state.swipe_dir       = direction
                state.swipe_frames   += 1
                state.swipe_count_opp = 0
            else:
                state.swipe_count_opp += 1
                if state.swipe_count_opp >= 3:
                    state.swipe_dir       = direction
                    state.swipe_frames    = 1
                    state.swipe_start_x   = px
                    state.swipe_count_opp = 0

            total = abs(px - state.swipe_start_x)
            if state.swipe_frames >= cfg.SWIPE_FRAMES and total >= cfg.SWIPE_MIN_PX:
                fired = state.swipe_dir
                state.reset_swipe()
                g = (Gesture.SWIPE_RIGHT if fired == "right"
                     else Gesture.SWIPE_LEFT)
                return GestureResult(g, 0.90, {"travel": total})
        else:
            state.swipe_frames = max(0, state.swipe_frames - 1)
            if state.swipe_frames == 0:
                state.swipe_start_x = px

        return GestureResult()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _decay_all(self):
        for s in self._states.values():
            s.fist_frames  = max(0, s.fist_frames  - 1)
            s.peace_frames = max(0, s.peace_frames - 1)


# ── Static helpers ────────────────────────────────────────────────────────────

def _hand_is_still(state: _HandState) -> bool:
    if len(state.still_buf) < 6:
        return False
    return (max(state.still_buf) - min(state.still_buf)) < 15


# ── Monkey-patch reset helpers onto _HandState ────────────────────────────────

def _reset_non_fist(self, px, py):
    self.peace_frames = 0
    self.prev_palm_x  = px
    self.prev_palm_y  = py
    self.reset_swipe()
    self.reset_pinch_smooth()
    self.still_buf.clear()
    self.reset_task_switch()
    # Note: do NOT reset cursor here — cursor uses middle finger and has its
    # own independent state machine

def _reset_scroll_swipe(self, px, py):
    self.prev_palm_x = px
    self.prev_palm_y = py
    self.reset_swipe()

_HandState._reset_non_fist    = _reset_non_fist
_HandState._reset_scroll_swipe = _reset_scroll_swipe
