#!/usr/bin/env bash
# Verify that ~/.hermes/profiles/tarantino/bin/chrome exists, is executable,
# and actually launches Chrome against the Tarantino user-data-dir on DISPLAY=:1.
#
# Safe to run when no Chrome is currently open against the profile. If a Chrome
# is already running, the second-instance probe will report "same session"
# instead of "silently exits" — both prove the wrapper points at the right
# profile.
#
# Exit code 0 = all checks passed; non-zero = first failing check.
set -euo pipefail

WRAPPER="/home/ubuntu/.hermes/profiles/tarantino/bin/chrome"
PROFILE_DIR="/home/ubuntu/.hermes/profiles/tarantino/Tarantino"
TITLE="Tarantino-Wrapper-Verify-$$"

echo "=== [1] file exists ==="
ls -la "$WRAPPER"

echo
echo "=== [2] executable bit ==="
test -x "$WRAPPER"
echo "OK"

echo
echo "=== [3] --version ==="
"$WRAPPER" --version

echo
echo "=== [4] pre-state: chrome processes against this profile ==="
PRE_COUNT=$(pgrep -cf "google-chrome.*--user-data-dir=$PROFILE_DIR" || echo 0)
echo "existing: $PRE_COUNT"

echo
echo "=== [5] launch with unique title in background ==="
nohup "$WRAPPER" "data:text/html,<title>$TITLE</title><h1>OK</h1>" \
  >/tmp/chrome_verify.log 2>&1 &
LAUNCH_PID=$!
sleep 4

echo
echo "=== [6] process carries --user-data-dir=$PROFILE_DIR ==="
ps -eo pid,args | grep -F -- "--user-data-dir=$PROFILE_DIR" | grep -v grep | head -1 \
  || { echo "FAIL: no chrome process with expected --user-data-dir" >&2; exit 6; }

echo
echo "=== [7] xdotool sees the window on DISPLAY=:1 ==="
WID=$(DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority \
        xdotool search --name "$TITLE" 2>/dev/null | head -1)
if [ -z "$WID" ]; then
  echo "FAIL: no window matching '$TITLE' on DISPLAY=:1" >&2
  exit 7
fi
echo "window $WID: $(DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority xdotool getwindowname $WID)"

echo
echo "=== [8] second invocation reuses the same profile ==="
SECOND_LOG=$(mktemp)
"$WRAPPER" --no-first-run 'about:blank' >"$SECOND_LOG" 2>&1 || true
if grep -q "Opening in existing browser session" "$SECOND_LOG"; then
  echo "OK: 'Opening in existing browser session.' — same-profile share confirmed"
else
  echo "NOTE: second invocation did not print the expected share marker; log follows:"
  cat "$SECOND_LOG"
fi
rm -f "$SECOND_LOG"

echo
echo "=== [9] cleanup: killing the test Chrome we launched ==="
# Only kill chrome processes that point at our profile AND have the test title
# in their args (the top-level process only). Child procs die with parent.
pkill -f "data:text/html,<title>$TITLE</title>" || true
sleep 2
POST_COUNT=$(pgrep -cf "google-chrome.*--user-data-dir=$PROFILE_DIR" || echo 0)
echo "remaining chrome against profile: $POST_COUNT (was $PRE_COUNT pre-test)"

echo
echo "=== ALL CHECKS PASSED ==="
