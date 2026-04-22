# GestureFlow — Complete Manual
### Version 1.0  |  Cross-platform Gesture Control System

---

## Table of Contents

1. [What is GestureFlow?](#1-what-is-gestureflow)
2. [System Requirements](#2-system-requirements)
3. [Installation](#3-installation)
4. [Quick Start](#4-quick-start)
5. [Gesture Reference](#5-gesture-reference)
6. [Keyboard Shortcuts (while running)](#6-keyboard-shortcuts)
7. [Configuration Guide](#7-configuration-guide)
8. [Project File Structure](#8-project-file-structure)
9. [Platform Notes](#9-platform-notes)
10. [Troubleshooting](#10-troubleshooting)
11. [Adding New Gestures](#11-adding-new-gestures)
12. [Adding New Actions](#12-adding-new-actions)
13. [FAQ](#13-faq)

---

## 1. What is GestureFlow?

GestureFlow is a real-time computer vision application that lets you control your laptop using hand gestures detected through your webcam — no extra hardware, no gloves, no markers.

**What you can do:**

| Gesture | Action |
|---|---|
| Right-hand pinch open | Volume Up |
| Right-hand pinch close | Volume Down |
| Left-hand pinch open | Brightness Up |
| Left-hand pinch close | Brightness Down |
| Open hand swipe left | Previous Window |
| Open hand swipe right | Next Window |
| Two fingers up + move up/down | Scroll |
| Closed fist (hold) | Minimize Window |
| Open palm (all 5 fingers) | Show Desktop |
| Peace sign (hold) | Take Screenshot |
| Thumbs Up | Play / Pause Media |

---

## 2. System Requirements

| Component | Minimum | Recommended |
|---|---|---|
| Python | 3.9 | 3.11+ |
| RAM | 4 GB | 8 GB |
| CPU | Dual-core 2GHz | Quad-core 3GHz |
| Webcam | 720p 15fps | 1080p 30fps |
| OS | Windows 10, macOS 12, Ubuntu 20.04 | Windows 11, macOS 14, Ubuntu 22.04 |

> **Note:** A dedicated GPU is NOT required. MediaPipe runs entirely on CPU.

---

## 3. Installation

### Option A — One-click Script (Recommended)

**Linux / macOS:**
```bash
cd GestureFlow
chmod +x install_and_run.sh
./install_and_run.sh
```

**Windows:**
```
Double-click install_and_run.bat
```
Or from Command Prompt:
```
cd GestureFlow
install_and_run.bat
```

### Option B — Manual Installation

```bash
# 1. Create a virtual environment
python3 -m venv .venv

# 2. Activate it
# Linux/macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python main.py
```

### Option C — System-wide (not recommended for most users)
```bash
pip install -r requirements.txt
python main.py
```

---

## 4. Quick Start

1. Run GestureFlow (see Installation above).
2. A window opens showing your camera feed.
3. Hold your hand in front of the camera (30–80 cm away works best).
4. Perform any gesture from the table below.
5. The action banner at the bottom confirms what fired.
6. Press **Q** to quit.

**Tips for best detection:**
- Use a well-lit environment (face a window or lamp).
- Keep your hand against a plain background if possible.
- Move gestures deliberately — slow, intentional motions work better than fast flicks.
- Keep your hand fully in frame.

---

## 5. Gesture Reference

### Volume Control (Right Hand)

**Volume Up**
- Form: Touch thumb tip and index tip together, then spread them apart.
- Trigger: The distance between thumb and index tip increases.
- Speed: Hold the spread — volume climbs continuously as long as you spread.

**Volume Down**
- Form: Spread thumb and index apart, then bring them together (pinch).
- Trigger: Distance decreases.

### Brightness Control (Left Hand)

Same as Volume but uses your **left hand**:
- Left-hand pinch open → Brightness Up
- Left-hand pinch close → Brightness Down

### Window Switching (Swipe)

**Swipe Right → Next Window (Alt+Tab)**
- Form: Hold 3+ fingers up, sweep your open hand to the right.
- The swipe must travel at a minimum speed across at least 6 frames (~0.2 seconds).

**Swipe Left → Previous Window (Alt+Shift+Tab)**
- Same but sweep to the left.

### Scrolling

**Scroll Up / Down**
- Form: Hold exactly index + middle finger up (like a peace sign but horizontal).
- Action: Move your hand upward to scroll up, downward to scroll down.
- Scrolls at the current mouse cursor position.

### Minimize Window

**Fist Hold**
- Form: Close all fingers into a fist.
- Hold it for ~0.4 seconds (12 frames at 30fps).
- The current focused window minimizes.

### Show Desktop

**Open Palm**
- Form: Spread all 5 fingers wide open.
- Fires immediately (no hold needed).

### Screenshot

**Peace Sign Hold**
- Form: Raise index + middle fingers (peace sign ✌️), keep others down.
- Hold for ~0.3 seconds (8 frames).
- A progress bar appears as you hold.
- Screenshot saved to your Desktop as `GestureFlow_screenshot_YYYYMMDD_HHMMSS.png`.

### Play / Pause Media

**Thumbs Up**
- Form: Only thumb extended upward, all other fingers curled.
- Sends the media play/pause key to your OS.

---

## 6. Keyboard Shortcuts

While the GestureFlow window is focused:

| Key | Action |
|---|---|
| `Q` | Quit GestureFlow |
| `G` | Toggle gesture guide overlay (bottom-left panel) |
| `P` | Pause / Resume gesture detection (camera keeps running) |
| `S` | Take a screenshot immediately |

---

## 7. Configuration Guide

All tunable parameters are in **`config/settings.py`**. You do not need to touch any other file to customise behaviour.

### Camera Settings

```python
CAMERA_INDEX  = 0     # 0 = built-in webcam, 1 = first USB cam, etc.
FRAME_WIDTH   = 1280
FRAME_HEIGHT  = 720
TARGET_FPS    = 30
```

If your camera runs slowly, try lowering `FRAME_WIDTH` and `FRAME_HEIGHT` to `640 × 480`.

### Detection Sensitivity

```python
DETECTION_CONFIDENCE  = 0.75   # Range: 0.5–0.95
TRACKING_CONFIDENCE   = 0.75   # Range: 0.5–0.95
```

- **Lower values** → more sensitive, may pick up false detections.
- **Higher values** → more stable, may miss gestures in poor lighting.

### Gesture Thresholds

```python
PINCH_THRESHOLD          = 0.055   # How small a pinch must be to be "in pinch zone"
SWIPE_VELOCITY_THRESHOLD = 0.025   # How fast you must swipe
SWIPE_FRAMES_REQUIRED    = 6       # Frames swipe direction must be consistent
FIST_HOLD_FRAMES         = 12      # Frames fist must be held (at 30fps → 0.4s)
PEACE_HOLD_FRAMES        = 8       # Frames peace sign must be held
```

**To make swipe easier to trigger:** Lower `SWIPE_VELOCITY_THRESHOLD` to `0.015` and `SWIPE_FRAMES_REQUIRED` to `4`.

**To make minimize require a longer hold:** Increase `FIST_HOLD_FRAMES` to `20`.

### Cooldowns

```python
VOLUME_COOLDOWN     = 0.08   # seconds between volume steps
BRIGHTNESS_COOLDOWN = 0.12
SWIPE_COOLDOWN      = 0.6    # prevents double-swipe
MINIMIZE_COOLDOWN   = 1.0
SCREENSHOT_COOLDOWN = 2.0
SCROLL_COOLDOWN     = 0.06
```

Increase a cooldown if an action fires too often accidentally. Decrease for faster response.

### Step Sizes

```python
VOLUME_STEP_PERCENT     = 2    # % per pinch unit
BRIGHTNESS_STEP_PERCENT = 3
```

### UI Toggles

```python
SHOW_FPS             = True   # FPS counter top-left
SHOW_LANDMARKS       = True   # Skeleton hand drawing
SHOW_GESTURE_NAME    = True   # Gesture label top-center
SHOW_ACTION_FEEDBACK = True   # Action banner bottom-center
```

---

## 8. Project File Structure

```
GestureFlow/
│
├── main.py                   ← Entry point. Run this.
├── requirements.txt          ← All Python dependencies
├── setup.py                  ← Package installer
├── install_and_run.sh        ← Linux/macOS one-click setup
├── install_and_run.bat       ← Windows one-click setup
├── MANUAL.md                 ← This file
├── HOW_I_WAS_BORN.md         ← Developer guide / build story
│
├── config/
│   ├── __init__.py
│   └── settings.py           ← ALL tunable parameters live here
│
├── core/
│   ├── __init__.py
│   ├── camera.py             ← Webcam management (open/read/release)
│   ├── hand_detector.py      ← MediaPipe wrapper + HandData type
│   ├── fps_counter.py        ← Rolling-average FPS measurement
│   └── overlay.py            ← HUD drawing (all cv2 rendering)
│
├── gestures/
│   ├── __init__.py
│   └── recognizer.py         ← Converts HandData → GestureResult
│
├── actions/
│   ├── __init__.py
│   ├── volume.py             ← Volume get/set (Windows/macOS/Linux)
│   ├── brightness.py         ← Brightness get/set
│   ├── window_manager.py     ← Minimize, swipe, scroll, screenshot
│   └── dispatcher.py        ← Maps GestureResult → OS action + cooldown
│
├── utils/
│   ├── __init__.py
│   ├── logger.py             ← Coloured console + rotating file logger
│   ├── cooldown.py           ← Time-based cooldown guard
│   └── math_helpers.py       ← Pure math: distance, clamp, map_range …
│
└── logs/
    └── gestureflow.log       ← Auto-created on first run
```

---

## 9. Platform Notes

### Windows
- Volume control uses **pycaw** (Windows Core Audio API) — most reliable.
- Brightness control uses **WMI** via `screen-brightness-control`.
- External monitors may not support brightness control via software.
- Run as a regular user — no admin rights needed.

### macOS
- Volume uses **osascript** (AppleScript) — works system-wide.
- Brightness: `screen-brightness-control` may require System Preferences → Privacy → Accessibility permission for the Terminal/app.
- macOS may ask for camera permission on first run — allow it.

### Linux (Ubuntu/Debian)
- Volume uses **amixer** (ALSA) or **pactl** (PulseAudio/PipeWire).
- Brightness uses **xrandr** or `/sys/class/backlight/` via `screen-brightness-control`.
- If brightness control fails, install `xrandr`: `sudo apt install x11-xserver-utils`.
- For Wayland: pyautogui may have limited functionality. Use X11 session for full support.

---

## 10. Troubleshooting

### Camera not opening
```
RuntimeError: Cannot open camera at index 0
```
- Try `CAMERA_INDEX = 1` in `config/settings.py`.
- Check if another application (Zoom, Teams) is using the camera.
- On Linux: `ls /dev/video*` to list cameras. Use the number that matches.

### Gestures not detected / shaky
- Improve lighting — face a lamp or window.
- Lower `DETECTION_CONFIDENCE` to `0.6` in settings.
- Keep hand 30–80cm from camera, palm facing the lens.
- Against a plain background (not a cluttered scene).

### Volume/Brightness not changing
- **Windows volume**: Install `pycaw` with `pip install pycaw`.
- **Linux brightness**: Run `sudo pip install screen-brightness-control` or install `xrandr`.
- **macOS**: Grant Accessibility permissions in System Preferences.

### FPS is very low (< 10)
- Lower camera resolution: `FRAME_WIDTH = 640`, `FRAME_HEIGHT = 480`.
- Set `SHOW_LANDMARKS = False` to skip skeleton drawing.
- Close other CPU-intensive applications.
- Lower `MAX_HANDS = 1` if you only need one hand.

### Swipe fires accidentally
- Increase `SWIPE_VELOCITY_THRESHOLD` to `0.035`.
- Increase `SWIPE_FRAMES_REQUIRED` to `10`.
- Increase `SWIPE_COOLDOWN` to `1.0`.

### "ImportError: No module named mediapipe"
Run: `pip install mediapipe` (inside your virtual environment).

---

## 11. Adding New Gestures

To add a new gesture (e.g., "three fingers up = open browser"):

**Step 1** — Add the name to `gestures/recognizer.py`:
```python
class Gesture(Enum):
    ...
    OPEN_BROWSER = auto()    # ← add this
```

**Step 2** — Add detection logic inside `GestureRecognizer.recognise()`:
```python
# Three fingers up (index, middle, ring) → open browser
if fingers == [False, True, True, True, False]:
    return GestureResult(Gesture.OPEN_BROWSER, 0.90)
```

**Step 3** — Add the action in `actions/dispatcher.py`:
```python
if g == Gesture.OPEN_BROWSER and self._cd["browser"].reset_if_ready():
    import webbrowser
    webbrowser.open("https://google.com")
    return ActionResult("Browser", "Opening …")
```

Don't forget to add `"browser": CooldownTimer(2.0)` in the `__init__` dict.

**Step 4** — Add the label in `core/overlay.py`:
```python
Gesture.OPEN_BROWSER: ("Browser  Open Browser", C_ACCENT),
```

That's it — four small edits across four files.

---

## 12. Adding New Actions

To add an action that's triggered by an *existing* gesture (e.g., make swipe-right open a specific app instead of switching windows):

1. Open `actions/dispatcher.py`.
2. Find the block for the gesture you want to change:
   ```python
   if g == Gesture.SWIPE_RIGHT and self._cd["swipe"].reset_if_ready():
       window_manager.next_window()        # ← change this
       return ActionResult("Swipe", "Next Window")
   ```
3. Replace the action with anything you want:
   ```python
   import subprocess
   subprocess.Popen(["firefox"])
   return ActionResult("Launch", "Firefox")
   ```

---

## 13. FAQ

**Q: Does it work without internet?**
A: Yes. Everything runs locally. No data is sent anywhere.

**Q: Does it store my video?**
A: No. Frames are processed in memory and never saved (unless you trigger a screenshot gesture).

**Q: Can I use both hands simultaneously?**
A: Yes — `MAX_HANDS = 2` by default. Volume on the right hand and brightness on the left work at the same time.

**Q: Will it conflict with my touchpad or mouse?**
A: No. GestureFlow only sends keyboard shortcuts and OS API calls. It does not move the mouse cursor.

**Q: Can I add a gesture for my own script?**
A: Yes — see Section 11 and 12. Adding a gesture takes about 10 minutes.

**Q: What if my camera is 4K and the app is slow?**
A: Set `FRAME_WIDTH = 1280` and `FRAME_HEIGHT = 720` in settings. Higher resolution gives no benefit for hand detection.
