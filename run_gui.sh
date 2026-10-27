#!/bin/sh
# Launches the reel2movie desktop GUI.
set -e
cd "$(dirname "$0")"
python3 -c "import PySide6" 2>/dev/null || pip3 install -e ".[gui]"
python3 -m gui.main
