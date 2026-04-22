# GestureFlow Configuration  –  v4
# ────────────────────────────────
# All tunable values in one place.
# Resolution is 640×480 by default — this is the single biggest factor
# for smooth FPS.  1280×720 costs ~3× the CPU with no gesture benefit.

# ── Camera ────────────────────────────────────────────────────────────────────
CAMERA_INDEX   = 0        # 0 = built-in webcam, 1 = first USB cam
FRAME_WIDTH    = 640      # Keep at 640×480 for smooth 30 fps on any laptop
FRAME_HEIGHT   = 480
TARGET_FPS     = 30

# ── MediaPipe Detection ───────────────────────────────────────────────────────
DETECTION_CONFIDENCE = 0.7   # 0.5–0.9  (lower = detects in dim light, more CPU)
TRACKING_CONFIDENCE  = 0.4   # lowered from 0.5 → saves ~2 fps on tracking path
MAX_HANDS            = 1     # 1 = fastest; set 2 if you want both hands at once

# ── Volume / Brightness  (pinch gesture) ─────────────────────────────────────
# The pinch maps FINGER DISTANCE directly to an absolute volume/brightness
# level — same technique as the reference VolumeHandControl.py.
# PINCH_MIN_PX  : pixel distance below which = minimum (mute / dark)
# PINCH_MAX_PX  : pixel distance above which = maximum (100%)
# These are in PIXELS at 640×480.  Good hands ~30 cm from cam ≈ 30–200 px.
PINCH_MIN_PX   = 30    # fingers almost touching
PINCH_MAX_PX   = 200   # fingers wide apart
PINCH_SMOOTH   = 5     # EMA smoothing  (1=instant, 10=very smooth)

# ── Scroll ────────────────────────────────────────────────────────────────────
SCROLL_THRESHOLD_PX  = 12   # min pixel movement per frame to count as scroll
SCROLL_COOLDOWN      = 0.05  # seconds between scroll events (very fast)

# ── Swipe  (tab / window switch) ─────────────────────────────────────────────
SWIPE_MIN_PX         = 80    # total pixel travel required to fire swipe
SWIPE_FRAMES         = 4     # must be sustained for N frames
SWIPE_COOLDOWN       = 0.7   # seconds between swipe events

# ── Hold gestures ─────────────────────────────────────────────────────────────
FIST_HOLD_FRAMES     = 10    # frames of closed fist → minimize (~0.33 s at 30fps)
PEACE_HOLD_FRAMES    = 12    # frames of still peace sign → screenshot

# ── Action cooldowns ─────────────────────────────────────────────────────────
VOLUME_COOLDOWN      = 0.0   # 0 = every frame  (direct mapping, no stepping)
BRIGHTNESS_COOLDOWN  = 0.0
MINIMIZE_COOLDOWN    = 1.2
SCREENSHOT_COOLDOWN  = 2.0
MEDIA_COOLDOWN       = 1.0
DESKTOP_COOLDOWN     = 1.5

# ── UI / Overlay ──────────────────────────────────────────────────────────────
SHOW_FPS             = True
SHOW_LANDMARKS       = True
SHOW_GESTURE_NAME    = True
SHOW_ACTION_FEEDBACK = True
FEEDBACK_DURATION_SEC= 1.5
OVERLAY_ALPHA        = 0.70

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_TO_FILE  = False     # False = faster startup, no disk I/O during gesture loop
LOG_LEVEL    = "INFO"
LOG_DIR      = "logs"

# ── Task Switcher (thumb+index pinch + drag) ─────────────────────────────────
# Only active in VoiceMode.NONE. Uses THUMB + INDEX distance.
TASK_PINCH_PX        = 22    # px — must be below PINCH_MIN_PX (30)
TASK_NAV_PX          = 30    # px of hand travel per navigation step
TASK_NAV_COOLDOWN    = 0.35  # s — min time between steps

# ── Cursor Control (thumb+middle pinch + move) ────────────────────────────────
# Uses THUMB + MIDDLE finger distance — physically distinct from index-based
# gestures so there is zero conflict with vol/bri/task-switch.
#
# CURSOR_PINCH_PX      : max thumb–middle distance to count as "cursor pinch"
# CURSOR_SENSITIVITY   : screen pixels moved per camera pixel moved
#                        (increase for faster cursor, decrease for precision)
# CURSOR_SMOOTH        : EMA factor 0–1 (lower = smoother but more lag)
# DOUBLE_PINCH_WINDOW  : max seconds between two pinch-releases = double-pinch
# DOUBLE_PINCH_PX      : thumb–middle must be BELOW this to count as "closed"
#                        for double-pinch detection
CURSOR_PINCH_PX      = 40    # px thumb-to-middle; tunable
CURSOR_SENSITIVITY   = 2.5   # multiplier on hand delta → cursor delta
CURSOR_SMOOTH        = 0.45  # EMA alpha: 0=no movement, 1=instant/jittery
DOUBLE_PINCH_WINDOW  = 0.55  # seconds between two pinches = double
DOUBLE_PINCH_PX      = 35    # px below which counts as "closed" for double

# ── Voice ─────────────────────────────────────────────────────────────────────
#   "auto"   → try vosk offline first, fall back to Google online
#   "google" → always use Google Speech API (needs internet)
#   "vosk"   → always use vosk offline (needs model in models/ folder)
#              Download: https://alphacephei.com/vosk/models
#              Extract any small-en model to GestureFlow/models/
VOICE_ENABLED        = True
VOICE_BACKEND        = "auto"
VOICE_PHRASE_LIMIT   = 3.0   # max seconds per listening burst
VOICE_ENERGY_THRESH  = 300   # mic sensitivity (lower = picks up softer speech)
# Mode timeout: voice lock auto-releases after this many seconds of inactivity
# Set 0 to never auto-release (must say "stop" manually)
VOICE_MODE_TIMEOUT   = 30    # seconds
