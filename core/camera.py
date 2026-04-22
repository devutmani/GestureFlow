"""
core/camera.py  –  v5
──────────────────────
Camera wrapper with Windows DirectShow backend for maximum FPS.

Key FPS fixes
─────────────
• Windows: use CAP_DSHOW backend — avoids MSMF's 3-frame startup buffer
  and reduces per-frame overhead by ~30% on most laptops.
• CAP_PROP_BUFFERSIZE = 1 — prevents reading stale frames.
• MJPEG codec — cameras deliver natively; decode is ~2× faster than YUV.
• in-place flip via dst parameter — avoids allocating a new array per frame.
"""

from __future__ import annotations

import cv2
import numpy as np
from typing import Optional, Tuple

from utils.logger import get_logger
import config.settings as cfg

log = get_logger(__name__)


class Camera:
    def __init__(self):
        self._cap:      Optional[cv2.VideoCapture] = None
        self._flip_buf: Optional[np.ndarray]       = None  # reused flip dst
        self.width  = cfg.FRAME_WIDTH
        self.height = cfg.FRAME_HEIGHT
        self.fps    = cfg.TARGET_FPS

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def open(self) -> "Camera":
        import platform
        log.info(f"Opening camera index={cfg.CAMERA_INDEX} …")

        # On Windows use DirectShow — far lower overhead than MSMF (default)
        if platform.system() == "Windows":
            self._cap = cv2.VideoCapture(cfg.CAMERA_INDEX, cv2.CAP_DSHOW)
        else:
            self._cap = cv2.VideoCapture(cfg.CAMERA_INDEX)

        if not self._cap.isOpened():
            raise RuntimeError(
                f"Cannot open camera at index {cfg.CAMERA_INDEX}. "
                "Check CAMERA_INDEX in config/settings.py."
            )

        # MJPEG for faster decode
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._cap.set(cv2.CAP_PROP_FPS,          self.fps)
        # 1-frame buffer — no stale frames, lower latency
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self.width  = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps  = self._cap.get(cv2.CAP_PROP_FPS)

        # Pre-allocate the flip destination buffer
        self._flip_buf = np.empty((self.height, self.width, 3), dtype=np.uint8)

        log.info(f"Camera opened: {self.width}×{self.height} @ {actual_fps:.1f} fps")
        return self

    def release(self):
        if self._cap and self._cap.isOpened():
            self._cap.release()
            log.info("Camera released.")

    # ── Frame I/O ─────────────────────────────────────────────────────────────

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Read one frame, flipped horizontally (mirror mode).
        Uses a pre-allocated dst buffer so cv2.flip() never mallocs.
        """
        if not self._cap or not self._cap.isOpened():
            return False, None

        ret, frame = self._cap.read()
        if not ret or frame is None:
            return False, None

        # In-place flip into pre-allocated buffer
        cv2.flip(frame, 1, dst=self._flip_buf)
        return True, self._flip_buf

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "Camera":
        self.open()
        return self

    def __exit__(self, *_):
        self.release()
