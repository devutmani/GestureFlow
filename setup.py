"""
setup.py
─────────
Installs GestureFlow as a local package.

Usage:
    pip install -e .          # editable install (recommended for development)
    pip install .             # normal install
"""

from setuptools import setup, find_packages
import platform

# Platform-specific dependencies
WINDOWS_DEPS = ["pycaw>=20181226", "comtypes>=1.2.0"]
LINUX_DEPS   = []   # brightness via screen-brightness-control (amixer/xrandr)
MACOS_DEPS   = []   # brightness via screen-brightness-control

extra_deps = []
if platform.system() == "Windows":
    extra_deps = WINDOWS_DEPS

setup(
    name="gestureflow",
    version="1.0.0",
    author="GestureFlow",
    description="Control your laptop with hand gestures via webcam",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "opencv-python>=4.8.0",
        "mediapipe>=0.10.0",
        "numpy>=1.24.0",
        "screen-brightness-control>=0.22.0",
        "pyautogui>=0.9.54",
        "Pillow>=10.0.0",
        "psutil>=5.9.0",
        "colorama>=0.4.6",
    ] + extra_deps,
    entry_points={
        "console_scripts": [
            "gestureflow=main:run",
        ]
    },
)
