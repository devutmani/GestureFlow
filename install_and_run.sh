#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# install_and_run.sh
# One-shot script: create venv → install deps → launch GestureFlow
# ─────────────────────────────────────────────────────────────────────────────
set -e

VENV_DIR=".venv"

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║        GestureFlow  Installer        ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.9+ first."
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  Python $PY_VERSION detected."

# Create virtual environment
if [ ! -d "$VENV_DIR" ]; then
    echo "  Creating virtual environment …"
    python3 -m venv "$VENV_DIR"
fi

# Activate
source "$VENV_DIR/bin/activate"

# Upgrade pip quietly
pip install --upgrade pip -q

# Install dependencies
echo "  Installing dependencies (this may take 2–3 minutes) …"
pip install -r requirements.txt -q

echo ""
echo "  ✓  Installation complete!"
echo "  Launching GestureFlow …"
echo ""

python main.py
