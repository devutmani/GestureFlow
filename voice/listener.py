"""
voice/listener.py  –  v6
──────────────────────────
Continuous background voice listener implementing strict mode-locking.

New mode semantics (v6)
────────────────────────
  VoiceMode.NONE        ← DEFAULT on startup
    Pinch gestures are FULLY DISABLED.
    Only non-pinch gestures work: scroll, swipe, minimize, media, screenshot.
    The system stays here until the user explicitly speaks a mode word.

  VoiceMode.VOLUME
    Entered by saying "volume".
    ONLY volume-related pinch gestures are processed.
    ALL other pinch routes (brightness) are suppressed.
    Stays active until the user says "lock".

  VoiceMode.BRIGHTNESS
    Entered by saying "brightness".
    ONLY brightness-related pinch gestures are processed.
    ALL other pinch routes (volume) are suppressed.
    Stays active until the user says "lock".

Transition diagram
───────────────────
  [NONE] ──"volume"──→ [VOLUME] ──"lock"──→ [NONE]
  [NONE] ──"brightness"──→ [BRIGHTNESS] ──"lock"──→ [NONE]
  [VOLUME] ──"brightness"──→ [BRIGHTNESS]  (direct switch, no lock needed)
  [BRIGHTNESS] ──"volume"──→ [VOLUME]      (direct switch)

Voice commands summary
───────────────────────
  "volume"      → enter VOLUME mode  (pinch = volume only)
  "brightness"  → enter BRIGHTNESS mode (pinch = brightness only)
  "lock"        → exit current mode → NONE (pinch disabled)
  "mute"        → one-shot: set volume = 0 immediately
  "pause"/"play"→ one-shot: media play/pause key
"""

from __future__ import annotations

import os
import threading
import time
from enum import Enum
from typing import Optional

from utils.logger import get_logger

log = get_logger(__name__)


# ── Voice Mode enum ───────────────────────────────────────────────────────────

class VoiceMode(Enum):
    NONE       = "none"        # DEFAULT — pinch gestures DISABLED
    VOLUME     = "volume"      # pinch → volume only (brightness blocked)
    BRIGHTNESS = "brightness"  # pinch → brightness only (volume blocked)


# ── Keyword tables ────────────────────────────────────────────────────────────

_VOLUME_WORDS     = {"volume", "volumes", "sound", "audio"}
_BRIGHTNESS_WORDS = {"brightness", "bright", "screen", "display", "dim", "dimmer"}
# "lock" is the ONLY exit word — explicit as per spec
_LOCK_WORDS       = {"lock", "locked", "unlock"}
_MUTE_WORDS       = {"mute", "silence", "silent"}
_MEDIA_WORDS      = {"pause", "play", "music"}


def _classify(text: str):
    """
    Parse a transcript string into a command.
    Returns (command, raw_text).
    command ∈ {"volume", "brightness", "lock", "mute", "media", None}

    Priority: lock > volume > brightness > mute > media
    This prevents "volume lock" from being parsed as "volume" alone.
    """
    words = set(text.lower().split())
    # Lock takes absolute priority so "volume lock" exits the mode
    if words & _LOCK_WORDS:
        return "lock", text
    if words & _VOLUME_WORDS:
        return "volume", text
    if words & _BRIGHTNESS_WORDS:
        return "brightness", text
    if words & _MUTE_WORDS:
        return "mute", text
    if words & _MEDIA_WORDS:
        return "media", text
    return None, text


# ── Thread-safe shared state ──────────────────────────────────────────────────

class VoiceState:
    """
    Thread-safe container holding the current VoiceMode and ancillary info.

    Written by VoiceListener thread.
    Read every frame by ActionDispatcher (main thread).

    Default state: VoiceMode.NONE  (pinch disabled until voice command)
    """

    def __init__(self):
        self._lock           = threading.Lock()
        self._mode           = VoiceMode.NONE   # ← starts LOCKED (pinch off)
        self._last_heard:    str  = ""
        self._listening:     bool = False
        self._error:         str  = ""
        self._mute_trigger:  bool = False
        self._media_trigger: bool = False

    # ── Read-only (main thread) ───────────────────────────────────────────────

    @property
    def mode(self) -> VoiceMode:
        with self._lock:
            return self._mode

    @property
    def last_heard(self) -> str:
        with self._lock:
            return self._last_heard

    @property
    def listening(self) -> bool:
        with self._lock:
            return self._listening

    @property
    def error(self) -> str:
        with self._lock:
            return self._error

    def consume_mute(self) -> bool:
        """Atomically read-and-clear the mute one-shot flag."""
        with self._lock:
            v = self._mute_trigger
            self._mute_trigger = False
            return v

    def consume_media(self) -> bool:
        """Atomically read-and-clear the media one-shot flag."""
        with self._lock:
            v = self._media_trigger
            self._media_trigger = False
            return v

    # ── Write (voice thread only) ─────────────────────────────────────────────

    def _set_mode(self, mode: VoiceMode, heard: str):
        with self._lock:
            self._mode       = mode
            self._last_heard = heard

    def _set_listening(self, val: bool):
        with self._lock:
            self._listening = val

    def _set_error(self, msg: str):
        with self._lock:
            self._error = msg

    def _trigger_mute(self, heard: str):
        with self._lock:
            self._mute_trigger = True
            self._last_heard   = heard

    def _trigger_media(self, heard: str):
        with self._lock:
            self._media_trigger = True
            self._last_heard    = heard


# ── Voice Listener ────────────────────────────────────────────────────────────

class VoiceListener:
    """
    Background daemon thread — continuously listens and updates VoiceState.

    Speech backends (tried in order):
      1. Vosk  (fully offline) — if a model folder exists in models/
      2. Google Speech API (online fallback)

    Usage:
        state    = VoiceState()
        listener = VoiceListener(state)
        listener.start()
        # ... main loop reads state.mode each frame ...
        listener.stop()
    """

    _PHRASE_LIMIT   = 3.0   # max seconds per listen burst
    _CALIBRATE_SEC  = 0.8   # noise-floor calibration duration

    def __init__(self, state: VoiceState):
        self._state      = state
        self._running    = False
        self._thread: Optional[threading.Thread] = None
        self._recognizer = None
        self._mic        = None
        self._use_vosk   = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        log.info("VoiceListener: initialising …")
        try:
            self._init_recognizer()
        except Exception as e:
            log.error(f"VoiceListener: mic init failed: {e}")
            self._state._set_error(str(e))
            return

        self._running = True
        self._thread  = threading.Thread(
            target   = self._loop,
            name     = "VoiceListener",
            daemon   = True,
        )
        self._thread.start()
        log.info(
            "VoiceListener: started.  "
            "Say 'volume', 'brightness', or 'lock' to control pinch mode."
        )

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        log.info("VoiceListener: stopped.")

    # ── Initialisation ────────────────────────────────────────────────────────

    def _init_recognizer(self):
        import speech_recognition as sr
        self._recognizer = sr.Recognizer()
        self._recognizer.energy_threshold        = 300
        self._recognizer.dynamic_energy_threshold = True
        self._recognizer.pause_threshold          = 0.5

        self._mic = sr.Microphone()

        log.info("VoiceListener: calibrating noise floor …")
        with self._mic as source:
            self._recognizer.adjust_for_ambient_noise(
                source, duration=self._CALIBRATE_SEC
            )
        log.info(
            f"VoiceListener: noise threshold = "
            f"{self._recognizer.energy_threshold:.0f}"
        )
        self._use_vosk = self._try_init_vosk()

    def _try_init_vosk(self) -> bool:
        model_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "models"
        )
        if not os.path.isdir(model_dir):
            return False
        candidates = [
            d for d in os.listdir(model_dir)
            if os.path.isdir(os.path.join(model_dir, d))
            and "vosk" in d.lower()
        ]
        if not candidates:
            log.info(
                "VoiceListener: no vosk model found — using Google Speech API."
            )
            return False
        try:
            from vosk import Model
            path = os.path.join(model_dir, candidates[0])
            self._vosk_model = Model(path)
            log.info(f"VoiceListener: vosk model loaded from '{path}'")
            return True
        except Exception as e:
            log.warning(f"VoiceListener: vosk load failed ({e}) — using Google.")
            return False

    # ── Listen loop ───────────────────────────────────────────────────────────

    def _loop(self):
        import speech_recognition as sr
        log.info(
            "VoiceListener: listening …  "
            "[volume | brightness | lock | mute | pause]"
        )
        while self._running:
            try:
                self._state._set_listening(True)
                with self._mic as source:
                    audio = self._recognizer.listen(
                        source,
                        phrase_time_limit=self._PHRASE_LIMIT,
                        timeout=None,
                    )
                self._state._set_listening(False)

                text = self._recognise(audio)
                if text:
                    log.info(f"VoiceListener heard: '{text}'")
                    self._handle(text)

            except sr.WaitTimeoutError:
                pass
            except OSError as e:
                log.warning(f"VoiceListener mic error: {e}")
                self._state._set_error(f"Mic error: {e}")
                self._state._set_listening(False)
                time.sleep(0.5)
            except Exception as e:
                log.warning(f"VoiceListener error: {e}")
                self._state._set_listening(False)
                time.sleep(0.3)

        self._state._set_listening(False)

    # ── Recognition backend ───────────────────────────────────────────────────

    def _recognise(self, audio) -> str:
        import speech_recognition as sr

        if self._use_vosk:
            try:
                import json
                raw  = self._recognizer.recognize_vosk(audio)
                text = json.loads(raw).get("text", "").strip()
                if text:
                    return text
            except Exception as e:
                log.debug(f"vosk error: {e}")

        try:
            return self._recognizer.recognize_google(audio).lower().strip()
        except sr.UnknownValueError:
            return ""
        except sr.RequestError as e:
            log.warning(f"Google Speech API: {e}")
            self._state._set_error("No internet / API error")
            return ""

    # ── Command handler ───────────────────────────────────────────────────────

    def _handle(self, text: str):
        command, raw = _classify(text)

        if command == "volume":
            self._state._set_mode(VoiceMode.VOLUME, raw)
            log.info("Mode → VOLUME  (pinch = volume only; say 'lock' to exit)")

        elif command == "brightness":
            self._state._set_mode(VoiceMode.BRIGHTNESS, raw)
            log.info("Mode → BRIGHTNESS  (pinch = brightness only; say 'lock' to exit)")

        elif command == "lock":
            prev = self._state.mode
            self._state._set_mode(VoiceMode.NONE, raw)
            log.info(f"Mode → NONE  (exited {prev.value}; pinch now DISABLED)")

        elif command == "mute":
            self._state._trigger_mute(raw)
            log.info("One-shot: mute")

        elif command == "media":
            self._state._trigger_media(raw)
            log.info("One-shot: media play/pause")
