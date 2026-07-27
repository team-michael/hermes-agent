#!/usr/bin/env bash
# Tarantino Chrome wrapper — reference copy.
#
# The live wrapper lives at ~/.hermes/profiles/tarantino/bin/chrome and is
# what both automation (hermes_chrome.py) and manual VNC launches should use,
# so cookies, logins, and CAPTCHA-unlocked sessions stay shared across every
# entry point. If the live wrapper is missing (profile recovery, fresh box),
# copy this file into place:
#
#   install -m 0755 scripts/chrome-tarantino-wrapper.sh \
#     /home/ubuntu/.hermes/profiles/tarantino/bin/chrome
#
# Pitfall: if chromedriver is already attached to the Tarantino profile, this
# wrapper will silently exit on SingletonLock. Check running processes first
# and reuse the existing window via xdotool instead of spawning a second one.
set -euo pipefail

export DISPLAY="${DISPLAY:-:1}"
export XAUTHORITY="${XAUTHORITY:-/home/ubuntu/.Xauthority}"

PROFILE_DIR="/home/ubuntu/.hermes/profiles/tarantino/Tarantino"
mkdir -p "$PROFILE_DIR"

exec /usr/bin/google-chrome \
  --user-data-dir="$PROFILE_DIR" \
  --password-store=basic \
  --use-mock-keychain \
  --no-sandbox \
  --disable-dev-shm-usage \
  --disable-blink-features=AutomationControlled \
  --lang=en-US,en \
  --disable-infobars \
  --disable-notifications \
  --start-maximized \
  "$@"
