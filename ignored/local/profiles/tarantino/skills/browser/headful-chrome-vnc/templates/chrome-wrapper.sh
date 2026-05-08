#!/usr/bin/env bash
# Tarantino Chrome wrapper.
#
# Always launches /usr/bin/google-chrome against the persistent Tarantino
# user-data-dir so cookies, logins, and CAPTCHA-solved sessions persist across
# runs (per Minkyu Cho directive, #clix-app-growth-project).
#
# Works for both automation (reused by hermes_chrome.py via --user-data-dir)
# and manual invocations from VNC terminals / desktop shortcuts.
#
# Install at: /home/ubuntu/.hermes/profiles/tarantino/bin/chrome  (chmod +x)
#
# Pitfall: if another Chrome is already running against this profile, the new
# invocation will NOT start a second browser — it prints
# "Opening in existing browser session." and exits. That's the same-profile-
# share signal; use it as proof the wrapper is pointing at the right profile.
# If you genuinely need a fresh Chrome process, kill chromedriver + chrome
# trees against this profile first (see SKILL.md § SingletonLock).
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
