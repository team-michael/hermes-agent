#!/usr/bin/env bash
# Diagnose VNC/noVNC/Chrome visibility for the Tarantino profile.
set -euo pipefail

echo "VNC server:"
pgrep -a Xtigervnc || true

echo
echo "noVNC/websockify:"
pgrep -a 'websockify|novnc|noVNC' || true

echo
echo "X display:"
DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority xdpyinfo 2>/dev/null | grep -E 'name of display|dimensions' || echo "xdpyinfo failed"

echo
echo "Chrome processes:"
pgrep -a 'google-chrome|chrome' | head -20 || true

echo
echo "Visible Chrome windows:"
if command -v xdotool >/dev/null; then
  DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority xdotool search --onlyvisible --name 'Google Chrome' getwindowname %@ || true
else
  echo "xdotool missing"
fi
