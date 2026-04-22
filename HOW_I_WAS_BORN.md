# HOW_I_WAS_BORN — The Complete Build Story of GestureFlow

> This document teaches you **why** every decision was made, **what** each part does, and **how** to extend anything. Written so that even if you've never touched computer vision before, you can understand, modify, and grow GestureFlow confidently.

---

## Part 1: The Big Idea — What Are We Even Building?

Before writing a single line of code, we had to answer: **what problem are we solving and what's the simplest possible technical pipeline to solve it?**

The goal: move your hand in front of a webcam → laptop does something (change volume, switch windows, etc.)

Let's trace the journey of a single hand gesture from reality to action:

```
Your Hand
   ↓  (light reflects off your hand)
Webcam captures pixels → a grid of RGB numbers (a "frame")
   ↓
MediaPipe finds 21 key points on your hand (fingertips, knuckles, wrist)
   ↓
Our code looks at those 21 points and says "this is a pinch gesture"
   ↓
We call the OS volume API with "turn up by 2%"
   ↓
Speaker gets louder
```

Every design decision we made was to keep this pipeline clear, fast, and easy to change.

---

## Part 2: How the Camera Works

**File: `core/camera.py`**

### Why we need it
`cv2.VideoCapture` is the raw OpenCV camera object. It's not complex, but it has lifecycle concerns — you must open it before use and release it afterward, or your webcam stays locked. If the program crashes mid-run without a `release()`, other apps can't use the camera.

### The solution: a context manager
We wrapped `VideoCapture` in a Python class with `__enter__` and `__exit__`. This guarantees the camera releases even on crash:

```python
with Camera() as cam:
    ok, frame = cam.read()
# Camera automatically released here, even if an exception happened
```

### The flip
We flip every frame horizontally with `cv2.flip(frame, 1)`. This makes it a mirror — when you move your right hand right, the on-screen hand moves right. Without the flip, gestures feel unnatural (like looking at someone else's hands).

### Why we store width/height
We read back the actual resolution from the camera driver because drivers don't always give you what you asked for. If you request 1280×720 but your camera only supports 640×480, you need to know the real size for correct coordinate math later.

---

## Part 3: The Hand Detector — MediaPipe Explained

**File: `core/hand_detector.py`**

### What is MediaPipe?
MediaPipe is a Google library that runs pre-trained machine learning models on camera frames. The `Hands` model finds hands and outputs 21 landmarks (key points) per hand.

### What is a landmark?
Think of your hand skeleton. MediaPipe knows where each joint is:

```
Landmark 0  = WRIST
Landmark 4  = THUMB TIP
Landmark 8  = INDEX FINGER TIP
Landmark 12 = MIDDLE FINGER TIP
... and so on up to Landmark 20 = PINKY TIP
```

Each landmark has `(x, y, z)` where x and y are **normalised** — they're not pixel coordinates, they're fractions of the frame size:
- `x = 0.0` means the far left of the frame
- `x = 1.0` means the far right
- `y = 0.0` means the top
- `y = 1.0` means the bottom

This normalisation is brilliant: it means our gesture math works regardless of camera resolution.

### Why `HandData`?
We wrap MediaPipe's raw output in our own `HandData` dataclass. This has two benefits:

1. **Decoupling**: The rest of the code never imports MediaPipe. Only `hand_detector.py` does. If MediaPipe changes its API in a future version, we only update one file.

2. **Clean API**: Instead of writing `results.multi_hand_landmarks[0].landmark[8].x`, you write `hand.tip("index").x`. Same data, much more readable.

### The `fingers_up()` method — the core trick
This is used by almost every gesture. It returns a list like `[True, False, True, True, False]` meaning [thumb, index, middle, ring, pinky].

How do we know if a finger is "up"?

**For fingers 2-5 (index through pinky):** If the TIP landmark's y-coordinate is *smaller* than the PIP (middle joint) landmark's y — the tip is *higher* on screen than the middle joint — the finger is extended. Remember: in image coordinates, y=0 is at the TOP, so a smaller y means higher up.

**For the thumb:** The thumb extends sideways, not upward. So we compare x instead of y. If the hand is a Right hand: thumb is up if `THUMB_TIP.x < THUMB_IP.x` (tip is more to the left, which is "out" for a right hand). For left hands it's flipped.

---

## Part 4: The Gesture Recognizer — The Brain

**File: `gestures/recognizer.py`**

This is the most important and interesting file. It takes a list of `HandData` (one per detected hand) and returns exactly one `GestureResult` per frame.

### Why stateful?
Some gestures need *time* to complete — a fist must be held for half a second, a swipe must travel at a minimum velocity over several frames. We can't determine this from a single frame.

The `_HandState` class stores per-hand rolling data:
- `prev_palm_x/y`: where the palm was last frame (to compute velocity/direction)
- `prev_pinch_dist`: how open the pinch was last frame (to detect opening vs closing)
- `fist_frames`: how many consecutive frames the fist has been closed
- `swipe_frames`: how many consecutive frames the hand has been moving in one direction

### Priority system
We check gestures in a strict priority order:
1. Open palm (show desktop) — highest priority, immediately obvious
2. Fist (minimize) — needs hold, but checked before most
3. Thumbs-up (media)
4. Peace sign (screenshot) — needs hold
5. Scroll (two fingers up + vertical motion)
6. Pinch (volume/brightness) — continuous
7. Swipe — continuous + directional

Why this order? Some finger configurations overlap. For example, during a swipe with an open hand, the pinch distance also fluctuates. By checking open-palm first, we don't accidentally trigger volume changes during a swipe.

### Pinch geometry
The pinch gesture uses **Euclidean distance** between thumb tip and index tip:

```python
dist = sqrt((thumb.x - index.x)² + (thumb.y - index.y)²)
delta = dist - prev_dist
```

- `delta > 0` → fingers spreading apart → Volume/Brightness UP
- `delta < 0` → fingers coming together → Volume/Brightness DOWN

We only fire if `abs(delta) > 0.003` to ignore tiny jitter (hands are never perfectly still).

Right hand = volume. Left hand = brightness. Simple rule, zero ambiguity.

### Swipe velocity
```python
dx = palm_center_x - prev_palm_center_x   # horizontal movement this frame
```

If `abs(dx) > SWIPE_VELOCITY_THRESHOLD` for `SWIPE_FRAMES_REQUIRED` consecutive frames in the same direction → swipe fires.

Why require consecutive frames? Because a hand naturally drifts and wobbles. Requiring 6 frames of sustained motion in one direction filters out jitter.

### Fist hold
Each frame we check if all fingers are down. If yes, increment `fist_frames`. If it reaches `FIST_HOLD_FRAMES` (default 12 frames = 0.4 sec at 30fps), fire `MINIMIZE`. Then reset to 0. This prevents the minimize from firing repeatedly.

---

## Part 5: The Action System

**Files: `actions/volume.py`, `actions/brightness.py`, `actions/window_manager.py`, `actions/dispatcher.py`**

### Why separate files?
Each OS has different APIs for volume, brightness, and windows. Separating them means:
- You can add Linux support to volume.py without touching brightness.py
- You can test volume control independently

### Volume — platform detection
```python
import platform
_SYSTEM = platform.system()  # "Windows", "Darwin" (macOS), "Linux"
```

Then each function has an if/elif chain:
- Windows: `pycaw` (Python Core Audio Wrapper) talks directly to the Windows Audio Session API
- macOS: AppleScript via `subprocess.call(["osascript", "-e", "..."])`
- Linux: `amixer` (ALSA command-line tool)

### Brightness
We use the `screen-brightness-control` library which handles the platform differences for us. It falls back gracefully if a display doesn't support software brightness control (common with external monitors).

### Window management — pyautogui keyboard shortcuts
Rather than calling OS-specific window management APIs (which are complex and different on every OS), we simply send keyboard shortcuts that the OS already understands:

```python
# Minimize: simulate pressing Win+Down on Windows
pyautogui.hotkey("win", "down")
```

This is elegant because:
1. Same code pattern on all platforms (just different key combos)
2. Works with any window manager
3. The user can see what shortcut is being sent (easy to understand and change)

### The Dispatcher — connecting gestures to actions
`dispatcher.py` is the "wiring" file. It answers: "I have a GestureResult — what should actually happen now?"

The cooldown system is crucial here. Without it:
- Holding a pinch would fire volume up 30 times per second
- A slightly slow swipe could fire next-window twice

Each action type has its own `CooldownTimer`:

```python
self._cd = {
    "volume":    CooldownTimer(0.08),   # fast — smooth continuous control
    "swipe":     CooldownTimer(0.6),    # slow — discrete action
    "minimize":  CooldownTimer(1.0),    # very slow — prevent accidental double
}
```

The pattern for every action is:
```python
if gesture == Gesture.X and self._cd["x"].reset_if_ready():
    do_the_action()
    return ActionResult("Label", "value shown in UI")
```

`reset_if_ready()` returns True AND resets the timer atomically only if the cooldown has elapsed. Clean, no race conditions.

---

## Part 6: The Cooldown Timer

**File: `utils/cooldown.py`**

One of the simplest but most important utilities. The implementation is just:

```python
def ready(self) -> bool:
    return (time.time() - self._last_fired) >= self.interval

def reset(self):
    self._last_fired = time.time()
```

`time.time()` returns a float (seconds since epoch). The difference gives elapsed time. If elapsed ≥ interval → ready to fire again.

`reset_if_ready()` combines both calls to prevent a race condition where two threads both call `ready()` before either calls `reset()`.

---

## Part 7: The Overlay — Drawing the HUD

**File: `core/overlay.py`**

### OpenCV coordinate system
In OpenCV, `(0, 0)` is the **top-left** corner. x increases rightward, y increases downward. All drawing calls use pixel coordinates.

```python
cv2.putText(frame, "Hello", (100, 200), font, scale, colour, thickness)
#                              x   y
```

### Semi-transparent panels
OpenCV doesn't support true alpha blending natively (SVG-style). We fake it:

```python
overlay = frame.copy()               # copy of current frame
cv2.rectangle(overlay, ...)          # draw solid rectangle on copy
cv2.addWeighted(overlay, alpha,      # blend copy with original
                frame, 1-alpha, 0, frame)
```

The result looks like a semi-transparent panel.

### Feedback banner timing
The action banner has a timestamp (`_action_expire`). Each frame we check `time.time() > _action_expire`. If not expired, draw it. The fade effect multiplies alpha by how close we are to expiry:

```python
alpha = min(1.0, (expire - time.time()) / duration * 2)
```

This fades in quickly and fades out slowly — feels natural.

### Volume/Brightness bars
These are simple vertical progress bars on the right edge. We store `_last_vol` and `_last_bri` (updated when a volume/brightness action fires). The bar's filled height is:

```python
filled_h = int(bar_height * percent / 100)
```

We draw from the bottom up (higher % = bar fills from bottom toward top) which matches the intuition of "louder = higher bar".

---

## Part 8: The Main Loop

**File: `main.py`**

The main loop is intentionally simple — it just calls everything in order:

```
Camera.read()
    → HandDetector.process()
        → GestureRecognizer.recognise()
            → ActionDispatcher.dispatch()
                → Overlay.render()
                    → cv2.imshow()
                        → cv2.waitKey(1)
```

`cv2.waitKey(1)` waits 1 millisecond for a key press. This is required for OpenCV to process its event queue (without it, the window doesn't update). The `& 0xFF` masks the result to 8 bits for cross-platform compatibility.

### Why `with Camera() as cam:`?
Using the context manager ensures `cam.release()` is called even if the loop crashes. Without this, you'd have to ctrl-C repeatedly to free the camera.

### The pause feature
When paused, we skip the detection and action pipeline entirely but still call `cam.read()` and `overlay.render()`. This keeps the camera feed live (so you can see yourself) but nothing fires.

---

## Part 9: The Math Helpers

**File: `utils/math_helpers.py`**

### Euclidean distance
Used for pinch detection. The classic distance formula:

```
distance = sqrt((x2-x1)² + (y2-y1)²)
```

Since coordinates are normalised (0–1), the maximum possible distance in a 1×1 space is `sqrt(2) ≈ 1.41`. A pinch threshold of `0.055` means "thumb and index are within 5.5% of frame width."

### `map_range()`
Maps a value from one number range to another. Used to convert pinch delta magnitude into a confidence percentage (0–1) for the confidence bar:

```python
# map_range(value, in_lo, in_hi, out_lo, out_hi)
conf = map_range(abs(delta), 0.003, 0.04, 0.3, 1.0)
# delta of 0.003 (minimum) → confidence 0.30
# delta of 0.040 (big move) → confidence 1.00
```

### `clamp()`
Prevents values from going out of range. Used everywhere:
```python
volume = clamp(new_vol, 0, 100)   # can't go below 0% or above 100%
```

---

## Part 10: How to Add a New Gesture (Step-by-Step Example)

Let's add: **"Point with index finger only → move mouse to that position"**

### Step 1: Name the gesture (1 line)

In `gestures/recognizer.py`, add to the `Gesture` enum:
```python
class Gesture(Enum):
    ...
    MOUSE_POINT = auto()
```

### Step 2: Detect it (5-10 lines)

In `GestureRecognizer.recognise()`, add a detection block:
```python
# Index finger only (index up, all others down)
if fingers == [False, True, False, False, False]:
    # Pass index tip position as metadata
    tip = hand.tip("index")
    return GestureResult(
        Gesture.MOUSE_POINT, 0.85,
        {"x": tip.x, "y": tip.y}  # normalised coords
    )
```

### Step 3: Add the action (5-10 lines)

In `actions/dispatcher.py`, add to `__init__`:
```python
"mouse": CooldownTimer(0.033),  # ~30fps mouse updates
```

Add to `dispatch()`:
```python
if g == Gesture.MOUSE_POINT and self._cd["mouse"].reset_if_ready():
    import pyautogui
    # Convert normalised → screen pixels
    sw, sh = pyautogui.size()
    x = int(result.meta["x"] * sw)
    y = int(result.meta["y"] * sh)
    pyautogui.moveTo(x, y, duration=0)
    return ActionResult("Mouse", f"({x},{y})")
```

### Step 4: Add overlay label (1 line)

In `core/overlay.py`:
```python
Gesture.MOUSE_POINT: (">>  Mouse Control", C_BLUE),
```

### Step 5: Add to MANUAL.md
Document the new gesture in the Gesture Reference table.

**Total code added: ~15 lines across 4 files.**

---

## Part 11: The Logger

**File: `utils/logger.py`**

### Why a custom logger?
Python's built-in `logging` module works fine but its default output is ugly. We add:
1. **Colours** via `colorama` — green for INFO, yellow for WARNING, red for ERROR
2. **Rotating file log** — so the log file never grows beyond 2MB (3 backups kept)
3. **Lazy initialisation** — settings are imported inside the function to avoid circular imports

### Why `get_logger(__name__)`?
`__name__` is the module's dotted path (e.g., `core.hand_detector`). This means each module's logs show their source, making debugging easy:

```
12:34:56  INFO      core.hand_detector  │  HandDetector ready
12:34:57  INFO      gestures.recognizer │  GestureRecognizer initialised
```

---

## Part 12: Dependency Map (What Imports What)

```
main.py
  ├── core/camera.py
  ├── core/hand_detector.py     ← imports mediapipe
  ├── core/fps_counter.py
  ├── core/overlay.py           ← imports gestures/recognizer (for Gesture enum)
  ├── gestures/recognizer.py    ← imports core/hand_detector (HandData)
  │                                      utils/math_helpers
  │                                      config/settings
  └── actions/dispatcher.py    ← imports gestures/recognizer (Gesture enum)
        ├── actions/volume.py
        ├── actions/brightness.py
        └── actions/window_manager.py

utils/ ← imported by everyone, imports nothing from GestureFlow
config/ ← imported by everyone, imports nothing from GestureFlow
```

The architecture is a **directed acyclic graph** — nothing imports from a file that's "above" it in the pipeline. This prevents circular imports and makes each layer testable in isolation.

---

## Part 13: Known Limitations and Future Ideas

### Current limitations
- **Lighting**: MediaPipe struggles in very dark or backlit conditions.
- **External monitors**: Brightness control may not work on external displays.
- **Wayland**: pyautogui has limited functionality on Linux Wayland sessions.
- **Multi-monitor**: Screenshots capture only the primary monitor.

### Future ideas you could implement

| Feature | What to change |
|---|---|
| Two-hand pinch-zoom | Add two-hand detection in `recognizer.py`, add zoom action in `window_manager.py` |
| Custom gesture training | Replace rule-based `fingers_up()` logic with a trained classifier |
| Voice + gesture combo | Add a speech recognition thread alongside the camera thread |
| Gesture macros | Let users record a sequence of gestures to replay |
| Config GUI | Build a Tkinter/PyQt settings window that writes to `settings.py` |
| Gesture profiles | Load different `settings.py` files per application (gaming vs office) |
| Multiple cameras | Change `MAX_HANDS` logic to merge detections from 2 cameras |
| Hand tracking cursor | Use index finger position to control mouse (see Part 10 example) |

---

## Part 14: Why These Libraries?

| Library | Why this one |
|---|---|
| **OpenCV** | Industry standard for camera I/O and image drawing. Fast, widely supported. |
| **MediaPipe** | State-of-the-art hand landmark detection from Google. Runs on CPU, free, no training needed. |
| **NumPy** | Required by OpenCV. Used for frame manipulation. |
| **pycaw** | The only reliable way to control Windows system volume from Python without admin rights. |
| **screen-brightness-control** | Handles all 3 OSes with one API. |
| **pyautogui** | Cross-platform keyboard simulation. No platform-specific APIs needed for window actions. |
| **colorama** | Makes logger colours work on Windows (Windows doesn't support ANSI codes natively). |

---

## Summary: The Mental Model

```
┌─────────────────────────────────────────────────────────┐
│  REAL WORLD: Your hand moves                            │
└─────────────────────────┬───────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  CAPTURE: Camera → RGB frame (numpy array)              │
│  core/camera.py                                         │
└─────────────────────────┬───────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  DETECT: MediaPipe → 21 landmarks (normalised x,y,z)    │
│  core/hand_detector.py                                  │
└─────────────────────────┬───────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  RECOGNISE: Geometry rules → named Gesture + confidence │
│  gestures/recognizer.py                                 │
└─────────────────────────┬───────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  DISPATCH: Gesture + cooldown → OS API call             │
│  actions/dispatcher.py + volume/brightness/window_mgr   │
└─────────────────────────┬───────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  FEEDBACK: Draw HUD on frame → display to user          │
│  core/overlay.py                                        │
└─────────────────────────────────────────────────────────┘
```

Each layer has exactly one job. If you want to change *how gestures are detected*, edit only `recognizer.py`. If you want to change *what a gesture does*, edit only `dispatcher.py`. The layers don't know about each other — they only pass typed data structures between them.

This separation is the most important architectural decision in the whole project. It's what makes GestureFlow easy to extend, debug, and maintain.
