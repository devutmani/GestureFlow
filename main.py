"""
main.py  –  v7
───────────────
GestureFlow — targeting 28–35 FPS on Windows.

FPS problems fixed in this version
─────────────────────────────────────
1. Voice listener init was blocking camera startup for 20-30 seconds.
   Fix: voice starts on a background thread AFTER the camera window opens.
   Camera is live immediately; voice initialises in parallel.

2. `cv2.getWindowProperty()` on Windows is slow (~1ms per call).
   Fix: only check it every 15 frames instead of every frame.

3. `from voice.listener import VoiceMode` inside render() was running
   every frame (Python import cache is fast but the lookup still costs).
   Fix: VoiceMode imported once at module level.

4. `_blend_buf` shape check in overlay was calling np.empty_like on mismatch.
   Fix: pre-allocate to exact frame size in Overlay.__init__ instead of
   checking every frame.

5. Log level set to WARNING during the frame loop — avoids string formatting
   overhead for INFO messages fired ~30× per second on gesture detection.

Key startup order:
  1. Camera opens immediately (< 2s)
  2. Window shown with "Voice initialising..." banner
  3. Voice thread completes in background (~5s)
  4. Banner disappears — full functionality available
"""

import sys
import threading
import cv2

from core.camera         import Camera
from core.hand_detector  import HandDetector
from core.fps_counter    import FPSCounter
from core.overlay        import Overlay
from gestures.recognizer import GestureRecognizer, GestureResult, Gesture
from actions.dispatcher  import ActionDispatcher, ActionResult
from utils.logger        import get_logger
import config.settings   as cfg

# Import VoiceMode once at module level — not inside render() every frame
try:
    from voice.listener import VoiceMode as _VoiceMode
except ImportError:
    _VoiceMode = None

log = get_logger("GestureFlow")
WIN = "GestureFlow"

_SILENT = frozenset({
    Gesture.VOLUME_UP, Gesture.VOLUME_DOWN,
    Gesture.BRIGHTNESS_UP, Gesture.BRIGHTNESS_DOWN,
    Gesture.CURSOR_MOVE,
})

_EMPTY_RESULT = GestureResult()


def _start_voice_background(result_holder: list):
    """
    Run in a daemon thread.
    Writes (listener, state) to result_holder[0] when done.
    Writes (None, None) if voice is disabled or fails.
    """
    if not cfg.VOICE_ENABLED:
        result_holder[0] = (None, None)
        return

    # Check that speech_recognition is installed before even trying
    try:
        import speech_recognition  # noqa: F401
    except ImportError:
        log.warning(
            "Voice disabled: 'speech_recognition' package not found.\n"
            "  Fix: run  pip install SpeechRecognition pyaudio  in your venv.\n"
            "  Then restart GestureFlow."
        )
        result_holder[0] = (None, None)
        return

    try:
        from voice.listener import VoiceListener, VoiceState
        vs = VoiceState()
        vl = VoiceListener(vs)
        vl.start()

        # Only report success if the listener thread is actually running
        if vl._running and vl._thread and vl._thread.is_alive():
            result_holder[0] = (vl, vs)
            log.info("Voice ready.  Say 'volume', 'brightness', or 'lock'.")
        else:
            result_holder[0] = (None, None)
            log.warning("Voice listener started but thread is not alive — voice disabled.")

    except Exception as e:
        log.warning(f"Voice failed to start: {e}")
        result_holder[0] = (None, None)


def run():
    log.info("=" * 52)
    log.info("  GestureFlow v7  —  starting up")
    log.info("=" * 52)

    detector   = HandDetector()
    recognizer = GestureRecognizer()
    dispatcher = ActionDispatcher()
    fps_ctr    = FPSCounter(window=10)

    # Start voice on background thread so camera opens without waiting
    voice_result: list = ["starting"]
    voice_thread = threading.Thread(
        target=_start_voice_background,
        args=(voice_result,),
        daemon=True
    )
    voice_thread.start()

    voice_listener = None
    voice_state    = None

    paused       = False
    frame_n      = 0
    window_check = 0   # only check WND_PROP_VISIBLE every N frames

    with Camera() as cam:
        # Pre-pass frame size to overlay so blend_buf is allocated immediately
        overlay = Overlay(cam.width, cam.height)

        cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)
        log.info(f"Camera: {cam.width}×{cam.height}  |  Press Q to quit")

        while True:
            ok, frame = cam.read()
            if not ok:
                log.error("Camera read failed.")
                break

            fps     = fps_ctr.tick()
            frame_n += 1

            # ── Pick up voice once it finishes initialising ───────────────────
            if voice_listener is None and voice_result[0] != "starting":
                voice_listener, voice_state = voice_result[0]

            if not paused:
                hands = detector.process(frame)

                # Draw landmarks every frame — landmark drawing is fast with
                # cached styles; only skip when FPS critically low (<20)
                if fps > 20 or frame_n % 2 == 0:
                    detector.draw_landmarks(frame, hands)

                gesture_result = recognizer.recognise(hands)
                action_result  = dispatcher.dispatch(gesture_result, voice_state)

                if action_result:
                    overlay.set_action(action_result)
                    if gesture_result.gesture not in _SILENT:
                        log.info(
                            f"{gesture_result.gesture.name:<20} → "
                            f"{action_result.label} {action_result.value}"
                        )
            else:
                hands          = []
                gesture_result = _EMPTY_RESULT
                cv2.rectangle(frame, (0, 0), (cam.width, cam.height),
                              (30, 30, 30), -1)
                cv2.putText(frame, "PAUSED  —  press P to resume",
                            (cam.width // 2 - 165, cam.height // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.85, (80, 80, 255), 2)

            # ── Render HUD ────────────────────────────────────────────────────
            frame = overlay.render(frame, gesture_result, hands, fps, voice_state)

            # Voice init banner while still loading
            if voice_result[0] == "starting":
                cv2.putText(frame, "Voice: initialising...",
                            (8, cam.height - 12),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.50,
                            (100, 100, 255), 1, cv2.LINE_AA)

            cv2.imshow(WIN, frame)

            # ── Key input ─────────────────────────────────────────────────────
            key = cv2.waitKey(1) & 0xFF

            if key in (ord("q"), ord("Q"), 27):
                log.info("Quit.")
                break
            elif key in (ord("g"), ord("G")):
                overlay.toggle_guide()
            elif key in (ord("p"), ord("P")):
                paused = not paused
                log.info("Detection " + ("paused." if paused else "resumed."))
            elif key in (ord("s"), ord("S")):
                from actions.window_manager import take_screenshot
                take_screenshot()
                overlay.set_action(ActionResult("Screenshot", "Saved"))
            elif key in (ord("v"), ord("V")):
                if voice_listener:
                    voice_listener.stop()
                    voice_listener = None
                    voice_state    = None
                    voice_result   = [("stopped",)]
                    overlay.set_action(ActionResult("Voice", "OFF"))
                else:
                    voice_result = ["starting"]
                    voice_thread = threading.Thread(
                        target=_start_voice_background,
                        args=(voice_result,), daemon=True
                    )
                    voice_thread.start()

            # ── Window-closed check — only every 15 frames (Windows perf fix) ─
            window_check += 1
            if window_check >= 15:
                window_check = 0
                try:
                    if cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
                        break
                except Exception:
                    break

    if voice_listener:
        voice_listener.stop()
    detector.release()
    cv2.destroyAllWindows()
    log.info("GestureFlow shut down cleanly.")


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Interrupted.")
        cv2.destroyAllWindows()
        sys.exit(0)
    except Exception as e:
        log.exception(f"Fatal: {e}")
        cv2.destroyAllWindows()
        sys.exit(1)
