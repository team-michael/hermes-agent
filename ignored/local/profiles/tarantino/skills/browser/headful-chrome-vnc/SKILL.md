---
name: headful-chrome-vnc
description: Run Chrome in headful mode on the VNC display with persistent profile (cookies, localStorage, cache). Use for web scraping and automation that benefits from a real GUI browser.
tags: [chrome, selenium, vnc, scraping, automation, headful]
---

# Headful Chrome on VNC with Persistent Profile

## When to Use
- Web scraping where headless gets blocked by bot detection
- Browser automation that needs a visible GUI (VNC)
- Tasks needing persistent cookies, localStorage, or login sessions across runs
- Any Selenium work on this system

## CAPTCHA Policy
If the automated page hits a CAPTCHA (TikTok rotation puzzle, Cloudflare Turnstile,
reCAPTCHA, Google `/sorry/` interstitial, etc.):
- **Do not spend iterations trying to auto-solve.** OpenCV angle estimation + xdotool
  drag does not beat modern trajectory-based bot detection (verified on TikTok 2026-04).
- **Do not silently fall back to a different SERP/provider** just to keep the run alive.
  Coverage that comes from an unannounced fallback is worse than a clean halt because it
  poisons the dataset with mixed-provider results. Halt and hand off instead.
- Stop and ask the user to connect via VNC (noVNC on port 6080, DISPLAY=:1) and solve
  the captcha by hand inside the already-running Chrome window.
- **Keep the driver alive.** Do not call `driver.quit()` — the blocked page must stay
  open in Chrome so the human can solve it inside the same Tarantino profile. Cookies
  set by solving will persist and be picked up on the next run.
- After the user solves it, continue automation in the same driver (don't quit) or
  reuse the profile in the next run.
- Offer 2Captcha/NopeCHA/CapSolver API integration only for bulk/recurring jobs where
  manual solving isn't scalable.

### Block detection

```python
def is_google_sorry(driver) -> bool:
    url = (driver.current_url or "")
    if "/sorry/" in url or "google.com/sorry" in url:
        return True
    src = (driver.page_source or "").lower()
    return any(n in src for n in [
        "detected unusual traffic",
        "our systems have detected",
        "unusual traffic from your computer",
        "비정상적인 트래픽",
    ])

def is_tiktok_captcha(driver) -> bool:
    src = (driver.page_source or "").lower()
    return ("captcha_slide" in src
            or "verify to continue" in src
            or "__captcha" in src)
```

Turnstile / reCAPTCHA surface as `<iframe src*="challenges.cloudflare.com">` or
`<iframe src*="recaptcha">` — detect by iframe src, not visual cues. Driver hitting
3 consecutive `TimeoutException` on the same URL also counts as a block.

### Async / cron-job handoff variant

When this skill is invoked from a cron job, webhook run, or any context where the
user is **not watching a live Slack reply**, "ask the user" means **post the handoff
request to the Slack channel/thread the run is associated with**. A log line is not
enough — the human needs a notification. This is what `autonomous-ai-agents/hermes-agent`
cross-references under "jace's standing rule for scraping cron jobs".

Recipe:

1. Detect the block using the selectors above.
2. **Do not `driver.quit()`.** Record the driver's PID. Then extend the process
   lifetime so Chrome stays mounted long enough for a human to arrive over VNC — a
   trailing `time.sleep(86400)` in the probe script is the simplest way. The cron
   scheduler's 3-minute interrupt does not kill a background child you spawned via
   `terminal(background=True)` — but SIGPIPE from a bad pipe does (see Pitfalls).
3. Raise the blocked Chrome window to the noVNC viewport's visible area so the
   human landing over VNC sees the challenge page immediately. **Do NOT use the
   pipe-to-`tail -n1` shortcut** — it silently produces empty `WID` when xdotool's
   internal window list isn't ready or the title-based search doesn't match (race
   observed 2026-05-13: `xdotool search --name 'Chrome'` returned empty even
   though a Chrome tab was visible on the display, because the only matching
   window's title was the URL string with `- Google Chrome` as a suffix — and
   the search ran while the tab was still loading the `/sorry/` redirect, so
   the title was momentarily different). Use the enumerate-then-filter form:
   ```bash
   # List all windows and their titles, then pick by URL substring
   DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority \
     xdotool search --name '.' 2>/dev/null | while read wid; do
       title=$(DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority \
         xdotool getwindowname $wid 2>/dev/null)
       echo "$wid | $title"
     done
   # Pick the WID whose title contains your blocked URL or 'Google Chrome'.
   # The root 'google-chrome' window has title literal 'google-chrome' — skip it.
   # The real tab has title '<url> - Google Chrome'.
   WID=<picked id>
   DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority bash -c "
     xdotool windowactivate $WID
     xdotool windowraise   $WID
     xdotool windowsize    $WID 1600 1000
     xdotool windowmove    $WID 0 0
   "
   ```
   Verify with `xdotool getwindowname $WID` — title should reference the blocked URL.

   If you embed the promote step inside the probe script's `finally` block (so it
   runs automatically on block), be aware that **calling `os.system()` with a
   `tail -n1` recipe inside the script also fails the same way** — the search
   may run before the window manager has stable focus on the tab. Two practical
   fixes: (a) sleep 1-2s before the xdotool call, or (b) accept that the
   in-script promotion may noop and do it manually after the handoff post.
   Today's session (2026-05-13) hit (a) failure mode — the script logged a
   cascade of "There are no windows in the stack" / "Invalid window '%1'"
   errors from xdotool because `$WID` was empty. The post-script manual
   enumerate+promote worked instantly.
4. Post a handoff message to the governing Slack location (if the cron job has a
   pinned `thread_ts`, post to that thread; otherwise to the channel it delivers to)
   using the profile's bot token. A ready-to-run template lives in the
   `tiktok-viral-research-via-google` skill at `templates/post_vnc_handoff.py` —
   copy it to your task's tmp dir, edit the `BLOCK_TYPE` / `BLOCK_URL` /
   `DRIVER_PID` / `COVERAGE_LINE` fields, run with the clix-growth venv. It
   publishes the post via direct `chat.postMessage` (not `send_message`) so the
   text is not re-transformed by the Slack gateway. Proven legible shape:
   ```
   :octagonal_sign: *VNC 수동 솔빙 요청*
   *차단 종류*: <google-sorry | tiktok-captcha | turnstile | recaptcha | other>
   *차단 URL*: <url>
   *감지 시각*: <UTC ISO>
   *현재 상태*: 드라이버 살려둠(pid <pid>), Tarantino 프로필에 차단 페이지 열려 있음
   *요청*: noVNC(포트 6080, `DISPLAY=:1`) 접속해서 띄워진 Chrome 창 안에서 수동 솔빙 부탁.
   쿠키는 Tarantino 프로필에 자동 저장되니까 풀기만 하면 됨.
   *이 Slack 스레드에 "풀었음" 한 줄 주면 이어서 재시도.*
   ```
5. **Stop the run.** Do not emit a partial report with reduced coverage — that
   silently degrades decision quality. Final agent output should be a single line
   like `차단됨 ({종류}): VNC 솔빙 요청 포스트 완료, ts=<reply_ts>, 드라이버 PID <pid> 유지`.
6. The next cron tick reuses the same Tarantino profile. If the human solved the
   challenge in the meantime, cookies from that solve are already in the profile and
   the next run passes naturally. If the block recurs on the next tick despite a
   clean solve, escalate (VPN / proxy change) rather than loop.

Cron jobs operating under this contract should declare it by listing
`headful-chrome-vnc` in `skills:` and anchoring `deliver:` to a fixed Slack thread
(`slack:CHANNEL:THREAD_TS`) so the daily report and any handoff requests share one
conversation. Auto-retry, SERP-provider fallback, and silent skipping are all
forbidden for blocks under this contract.

### Probe-died-with-script handoff (verified 2026-05-26)

A sibling failure mode of the "Stale handoff" section above. The "Stale" case
is *driver was parked, Chrome died mid-park*. This case is *the script never
parked at all* — it crashed cleanly on block detection and took the driver
with it on `driver.quit()` in its `finally` clause.

This is the common shape when the blocking script is **not** a probe written
to the §4 contract but a regular pipeline stage (`p2_weekly_report.py`,
`dom_verify_run.py`, etc.) whose CAPTCHA detection raises an exception
through a `with create_driver() as d:` block. The driver dies, Chrome dies,
the script exits 1, and the user has nothing to solve in VNC.

**Symptom signature:**
- Pipeline log shows `STAGE A HALTED on query: CAPTCHA on: '<query>'` (or
  equivalent) followed by a clean `Saved to ...` line + traceback + exit 1.
- `pgrep -af 'chrome|chromedriver' | grep -v grep` returns empty.
- `ls /tmp/.X*-lock` shows X is up but no Chrome attached.
- No `time.sleep(86400)` parked process anywhere.

**Recovery — manual Chrome relaunch directly to the blocked URL:**

The standard "leave driver alive" §4 recipe doesn't apply here because there's
no driver to leave alive. Instead, relaunch Chrome via the wrapper directly
to the URL that triggered the block. Cookies still seed correctly because
the wrapper points at the same Tarantino `--user-data-dir` the dead Selenium
session used.

```bash
# 1. Confirm Chrome really is gone (prevent SingletonLock collision later)
pgrep -af 'chrome|chromedriver' | grep -v grep | head
ls /home/ubuntu/.hermes/profiles/tarantino/Tarantino/Singleton* 2>/dev/null
# If anything lives, sweep with the enumerate-then-kill recipe in the
# SingletonLock section — never `pkill -f chrome` (self-terminates the shell).

# 2. Relaunch via the wrapper, directly to the blocked URL.
# Use terminal(background=True), NOT shell `&`/`disown`/`nohup`.
DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority \
  /home/ubuntu/.hermes/profiles/tarantino/bin/chrome '<exact-blocked-URL>'

# 3. Wait ~5s for the tab title to settle.
sleep 5

# 4. Enumerate windows and find the WID by URL substring (NOT title 'Chrome')
DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority \
  xdotool search --name '.' 2>/dev/null | while read wid; do
    title=$(DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority \
      xdotool getwindowname $wid 2>/dev/null)
    echo "$wid | $title"
  done
# Pick the WID whose title contains the URL fragment or query keywords.
# Skip the root 'google-chrome' window.

# 5. Promote it to the noVNC viewport
WID=<picked id>
# If `xdotool` from a `bash -c` wrapper hits "Authorization required, but no
# authorization protocol specified" / "Can't open display: (null)", the
# environment isn't propagating. Run via Python's `subprocess` with an
# explicit env dict instead — that path works:
#   import os, subprocess
#   env = os.environ.copy()
#   env["DISPLAY"] = ":1"
#   env["XAUTHORITY"] = "/home/ubuntu/.Xauthority"
#   for cmd in [["xdotool","windowactivate",WID], ...]:
#       subprocess.run(cmd, env=env, capture_output=True, text=True)
# Bash's `DISPLAY=:1 XAUTHORITY=... xdotool ...` form sometimes loses the
# vars before xdo init when wrapped through `bash -c '...'` — running each
# xdotool command standalone or via subprocess.run with explicit env works.

# 6. Post the Slack VNC handoff via templates/post_vnc_handoff.py.
# Body should explicitly state "Chrome 살아있음" and the exact URL.
```

**After the user solves and replies "완료":**

```bash
# 1. Verify cookie was set — title should have flipped from /sorry/... to
# the legitimate destination page title (e.g. real Google Search results).
DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority xdotool getwindowname $WID

# 2. Kill the manual Chrome cleanly (enumerate-then-kill, NOT pkill -f).
for pid in $(ps -eo pid,args | \
  grep -E 'chrome.*--user-data-dir=/home/ubuntu/.hermes/profiles/tarantino/Tarantino|chrome_crashpad' | \
  grep -v grep | awk '{print $1}'); do
  kill $pid 2>/dev/null
done
sleep 3

# 3. Sweep singletons (always do this before re-running automation)
rm -f /home/ubuntu/.hermes/profiles/tarantino/Tarantino/Singleton{Lock,Cookie,Socket}

# 4. Re-run the original pipeline. Cookies seeded by the manual solve are
# in the Tarantino profile and inherited by the next create_driver().
```

**Why "manual Chrome to blocked URL" beats "rerun probe to re-trigger block":**
- Faster (no probe budget burn, no risk of Q14-style rate-limit cascade
  on a fresh driver).
- Same cookie outcome — the solve writes to `--user-data-dir`, not the
  driver session.
- Cleaner handoff message — you can name the exact URL the human will see.

**Pitfall — do NOT skip the singleton sweep before re-running.** Even though
your `kill` command exited and `pgrep -af chrome` returns empty, the wrapper's
post-launch `chrome_crashpad` worker can briefly hold the SingletonLock for
a second or two after kill. If you re-run P2 immediately and it tries to
spawn its own Selenium-controlled Chrome at the same `user-data-dir`, you
get a silent SingletonLock collision (Selenium reports a generic "Chrome
failed to start"). Always: kill → sleep 3 → rm Singleton* → then re-run.

**Verified 2026-05-26** on duolog W22 P2 retry: P2 hit Google `/sorry/` on
Q1, exited 1, Chrome gone. Wrapper-relaunched to the same blocked Google
search URL → user solved CAPTCHA in noVNC → killed manual Chrome → swept
SingletonLock → re-ran P2 → completed 16/16 queries clean (Q14 reddit
CAPTCHA in late stage, but Stage A had already saved 103 URLs at that
point, so report.json/clusters.json/report.md emerged intact).

### Two-stage captcha on recovery runs (Google + TikTok are separate cookie layers)

Observed 2026-05-11: a clean VNC solve on Google `/sorry/` does NOT seed TikTok cookies. When the recovery pipeline moves from SERP scraping to TikTok DOM verification, expect a **second captcha handoff** on the first TikTok page load if it's been more than ~a day since the last TikTok session in this profile.

Detection signature for Stage 2:
- `dom_verify*.out` logs `CAPTCHA at @<handle>: <url>` on video #1 (not a random mid-run failure)
- Chrome window title still shows the video URL (rotation puzzle is a modal overlay, doesn't rewrite title)
- `#captcha-verify-container-main-page` present in DOM

Handling:
- Treat Stage 2 as continuation of the same incident, not a new failure. In interactive Slack contexts, post the Stage-2 request as a **reply in the same thread** as the Stage-1 handoff, not a new top-level ops post. In cron/webhook contexts, a fresh top-level handoff may be appropriate because the user needs a push notification.
- Promote the TikTok tab to VNC viewport with the same xdotool recipe as Stage 1.
- After human solves, remaining DOM-verify candidates pass without further captcha (TikTok cookie stays warm for same-day runs).

Multi-day gap → multi-stage handoff risk. If the cron job hasn't done a TikTok DOM verify in 3+ days, plan for Stage 2 even if Stage 1 went clean.

### Rapid probe script

Use `scripts/probe_google_block.py` (bundled with this skill) for a fast isolated
check — "is Google blocking us right now?" — before committing a full scraping run.
It runs a few representative queries, stops at the first `/sorry/`, writes a
structured JSON log, and by default keeps the driver alive for VNC handoff per the
variant above. See Quick Start for invocation. Run it backgrounded with stdout
redirected to a file — **not** piped to `head`/`tail` (SIGPIPE trap documented in
Pitfalls).

## Environment
- Chrome: `/usr/bin/google-chrome` (v147+)
- ChromeDriver: prefer profile-local `/home/ubuntu/.hermes/cache/chrome/chromedriver-linux64/chromedriver` when present; system `/usr/local/bin/chromedriver` may lag Chrome after auto-updates and fail on major-version mismatch.
- VNC Display: `:1` (TigerVNC, 1920x1080)
- noVNC: accessible via port 6080
- Python module: `/home/ubuntu/.hermes/profiles/tarantino/bin/hermes_chrome.py`
- Manual-launch wrapper: `/home/ubuntu/.hermes/profiles/tarantino/bin/chrome` (template: `templates/chrome-wrapper.sh`; verify with `scripts/verify_chrome_wrapper.sh`)
- Profile dir: `/home/ubuntu/.hermes/profiles/tarantino/Tarantino/` (Chrome user-data-dir name: "Tarantino")

## Manual Launch Wrapper (`bin/chrome`)

For any non-Selenium invocation — VNC terminal, user asking to "just open TikTok", desktop shortcut, `xdg-open` — use the wrapper so manual and automated sessions share cookies/localStorage/logins:

```bash
/home/ubuntu/.hermes/profiles/tarantino/bin/chrome                         # empty tab
/home/ubuntu/.hermes/profiles/tarantino/bin/chrome https://www.tiktok.com  # direct nav
```

The wrapper pins `DISPLAY=:1`, `XAUTHORITY`, `--user-data-dir=...Tarantino`, `--password-store=basic`, and the bot-detection-mitigation flags. Source of truth lives in `templates/chrome-wrapper.sh` in this skill — if the wrapper is missing on disk (fresh profile recovery), copy that template to `bin/chrome` and `chmod +x`.

### Verifying the wrapper

Run the bundled script:

```bash
bash /home/ubuntu/.hermes/profiles/tarantino/skills/browser/headful-chrome-vnc/scripts/verify_chrome_wrapper.sh
```

It checks (in order): file exists, executable, `--version`, launches with a unique window title, `ps` confirms `--user-data-dir` matches, `xdotool` sees the window on `DISPLAY=:1`, and — the key same-profile-share proof — a second invocation prints `Opening in existing browser session.` and exits instead of opening a separate browser. That marker is cleaner evidence than inspecting `SingletonLock` alone. Finally it kills only the test window it launched.

### Same-profile share marker

When Chrome is already running against the Tarantino `user-data-dir`, calling the wrapper again will NOT spawn a second browser. It will log:

```
Opening in existing browser session.
```

…and the wrapper process exits. This is **expected and desired** — it's the proof that both invocations resolve to the same profile. Do not interpret it as a failure. If you genuinely need a fresh Chrome process (e.g. driverless after a webdriver crash), follow the SingletonLock kill recipe below.

### Recovery note — missing module / ChromeDriver mismatch

After profile recovery, `/home/ubuntu/.hermes/profiles/tarantino/bin/hermes_chrome.py` may be missing even though workflows import it. Recreate it under the profile `bin/` directory and keep all mutable assets under `~/.hermes`.

If `google-chrome --version` and `chromedriver --version` have different major versions, do **not** overwrite `/usr/local/bin/chromedriver` unless the user explicitly asked for system mutation. Download the matching driver into `~/.hermes/cache/chrome` instead:

```bash
/home/ubuntu/.hermes/venvs/clix-growth/bin/python -m pip install selenium
mkdir -p /home/ubuntu/.hermes/cache/chrome
CHROME_VERSION=$(google-chrome --version | grep -oP '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+')
curl -fsS -o /home/ubuntu/.hermes/cache/chrome/chromedriver-${CHROME_VERSION}.zip \
  "https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chromedriver-linux64.zip"
unzip -qo /home/ubuntu/.hermes/cache/chrome/chromedriver-${CHROME_VERSION}.zip -d /home/ubuntu/.hermes/cache/chrome/
chmod +x /home/ubuntu/.hermes/cache/chrome/chromedriver-linux64/chromedriver
```

Then have `hermes_chrome.py` use Selenium `Service('/home/ubuntu/.hermes/cache/chrome/chromedriver-linux64/chromedriver')`.

## Persistent Profile — Manual Launch Parity

Automation already pins the Tarantino profile via `hermes_chrome.py` (it passes `--user-data-dir=/home/ubuntu/.hermes/profiles/tarantino/Tarantino`). For **manual** Chrome launches from VNC terminals, desktop shortcuts, or `xdg-open`, use the wrapper at `~/.hermes/profiles/tarantino/bin/chrome` so cookies, logins, and CAPTCHA-unlocked sessions persist across every entry point — not just Selenium runs.

Wrapper (kept under `~/.hermes`, the only writable boundary). A reference copy lives at `scripts/chrome-tarantino-wrapper.sh` — copy it into place with `install -m 0755 scripts/chrome-tarantino-wrapper.sh ~/.hermes/profiles/tarantino/bin/chrome` if the live wrapper is missing after a profile recovery.

```bash
/home/ubuntu/.hermes/profiles/tarantino/bin/chrome                         # empty tab, Tarantino profile
/home/ubuntu/.hermes/profiles/tarantino/bin/chrome https://www.tiktok.com  # open a URL in the same profile
```

It sets `DISPLAY=:1`, `XAUTHORITY=/home/ubuntu/.Xauthority`, `--user-data-dir=...Tarantino`, `--password-store=basic`, `--use-mock-keychain`, and the standard anti-automation-detection flags — same shape Selenium uses, so manual and automated sessions share one cookie jar.

### Extending profile parity beyond the wrapper

The wrapper alone means users must type the full path. To make *every* Chrome entry point use Tarantino, two further hooks live **outside `~/.hermes`** and therefore require explicit user consent before being written (SOUL.md hard boundary):

1. **Terminal alias** — append to `~/.bashrc`:
   ```bash
   alias chrome='/home/ubuntu/.hermes/profiles/tarantino/bin/chrome'
   ```
2. **Desktop override** — create `~/.local/share/applications/google-chrome.desktop` with `Exec=/home/ubuntu/.hermes/profiles/tarantino/bin/chrome %U` so the VNC taskbar icon and `xdg-open https://...` both route through the wrapper.

Always present these two as an explicit choice ("wrapper only" vs "+ alias" vs "+ alias + desktop override") and wait for confirmation. Do not silently mutate `.bashrc` or `~/.local/share/applications/`.

### Pitfalls

- **SingletonLock collision:** if automation (chromedriver tree) is already attached to the Tarantino profile, the manual wrapper invocation silently exits. Check `ps -eo pid,comm,args | grep -E 'chrome|chromedriver' | grep -v grep` first; reuse the existing window via xdotool instead of spawning a second Chrome (see SingletonLock section below).
- **Wrapper lives under `~/.hermes`** by design — do not move it to `/usr/local/bin` or `~/bin`; that violates the hard filesystem boundary.
- **Chrome/ChromeDriver major version must match.** Verify with `google-chrome --version` and `/home/ubuntu/.hermes/cache/chrome/chromedriver-linux64/chromedriver --version` before a run; mismatch is a silent failure mode.
- **SIGPIPE kills the handoff.** When spawning a probe script via
  `terminal(background=True)`, do NOT pipe its stdout to `| head`, `| tail`, or any
  truncating consumer. When the pipe reader closes early, the Python process
  receives SIGPIPE, dies, and takes `chromedriver` + the blocked Chrome window with
  it — defeating the entire "leave driver alive for VNC" policy. Either redirect
  to a file (`python probe.py > probe.out 2>&1`) or let the terminal tool capture
  the full stream. Confirmed trap: `terminal(command="python probe.py 2>&1 | head -5", background=True)` returns quickly, Chrome is gone, `ps | grep chrome` is empty.
  Symptom: the script printed "driver INTENTIONALLY not quit" but no
  `chromedriver`/`google-chrome` process remains.

## Quick Start

Diagnostic helper:

```bash
bash /home/ubuntu/.hermes/profiles/tarantino/skills/browser/headful-chrome-vnc/scripts/check_vnc_chrome.sh
```

It checks VNC, noVNC/websockify, X display, Chrome processes, and visible Chrome window titles before you ask the user to solve a CAPTCHA.

Rapid "is Google blocking us right now" probe — runs a handful of real queries,
stops at the first `/sorry/`, writes a structured JSON log, leaves the driver
alive for VNC handoff per policy above. Use when you need decision-grade
"blocked yes/no" evidence before committing a full scraping run:

```bash
# MUST redirect to a file — do NOT pipe to `| head`/`| tail` (SIGPIPE kills Chrome)
DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority \
  /home/ubuntu/.hermes/venvs/clix-growth/bin/python \
  /home/ubuntu/.hermes/profiles/tarantino/skills/browser/headful-chrome-vnc/scripts/probe_google_block.py \
  > /tmp/probe_google.out 2>&1 &
# Log → $PROBE_LOG_PATH (default: ~/.hermes/tmp/cron_tiktok/probe_google_log.json)
# Override queries: PROBE_QUERIES='q1|q2|q3' python probe_google_block.py
```

```python
import sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/tarantino/bin')
from hermes_chrome import create_driver, set_persistent_cookie, take_screenshot, By, WebDriverWait, EC

driver = create_driver()          # headful, 1920x1080
driver.get('https://example.com')

# Set a cookie that survives restarts (MUST be on the target domain already)
set_persistent_cookie(driver, 'my_cookie', 'my_value')

# Take screenshot
path = take_screenshot(driver, 'my_page')

driver.quit()
```

## Critical Environment Variables
These are set automatically by `hermes_chrome.py`, but if running Chrome manually:
```
DISPLAY=:1
XAUTHORITY=/home/ubuntu/.Xauthority
```

## VNC Visibility Triage

If the user says they cannot see Chrome in VNC/noVNC:

1. Run the diagnostic helper above.
2. If VNC/noVNC are running but there are **no Chrome processes**, launch Chrome explicitly onto the VNC display:

```bash
DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority \
/usr/bin/google-chrome \
  --user-data-dir=/home/ubuntu/.hermes/profiles/tarantino/Tarantino \
  --password-store=basic --use-mock-keychain --no-sandbox --disable-dev-shm-usage \
  --disable-blink-features=AutomationControlled --window-size=1400,900 --start-maximized \
  'https://www.google.com/search?q=test&hl=en'
```

3. Bring the window to the front:

```bash
DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority \
xdotool search --onlyvisible --name 'Google Chrome' windowactivate %@ windowraise %@ windowsize %@ 1400 900 windowmove %@ 0 0
```

4. Ask the user to refresh/reconnect the noVNC page. If Chrome still does not render but the diagnostic shows a visible Chrome window title, the issue is the viewer/session rendering layer, not Chrome.

### SingletonLock — don't spawn a second Chrome into a busy profile

If a Selenium/webdriver-controlled Chrome is already running against the `Tarantino` user-data-dir (for example, because `p2_weekly_report.py` halted on CAPTCHA and left chromedriver alive), launching a second `google-chrome --user-data-dir=.../Tarantino` **silently exits** — Chrome detects the existing instance's `SingletonLock` and bails without an error message. Symptom: `ps -eo pid,comm | grep chrome` still shows the old `chromedriver` + children with `--test-type=webdriver` and no new window appears.

**Cron-specific common case (verified 2026-05-09)**: The previous cron tick's probe/scrape is still parked. When §4's "driver INTENTIONALLY not quit; parking 24h" policy triggers, the Python process sits in `time.sleep(86400)` with chromedriver + Chrome attached. The next cron tick (~24h later) finds them still alive. Check for this first:

**Sibling failure mode — zombie chromedriver from completed pipeline stage (verified 2026-05-10)**: A DOM-verify / ranker / post-processing script from the *previous* pipeline run can exit normally but leave its chromedriver child as a defunct process (`STAT=Z`, `comm=[chromedriver] <defunct>`). The Python parent is gone but the zombie still holds the profile's SingletonLock via its parent reaping. Symptom on next cron tick:
```
ubuntu  223780  850  0  01:08 ?  00:00:00 /home/ubuntu/.hermes/venvs/clix-growth/bin/python dom_verify_run.py
ubuntu  223782 223780 0 01:08 ?  00:00:00 [chromedriver] <defunct>
```
(ETIME is ~22h, STAT=Z on the child.) Kill the Python parent with `kill -9` — it reaps the zombie — then proceed. Do NOT skip this check; `create_driver()` will hang or fail cryptically against a locked profile.

```bash
# Find a parked scrape process from a previous tick
ps -eo pid,etime,stat,comm,args | grep -E 'scrape_google|probe.*google' | grep -v grep
# ETIME > 20h + STAT=S means it's parked. Kill the Python parent; chromedriver
# becomes a zombie (Z STAT) and dies when you reap it:
kill -9 <python_pid>
# Then clean up any orphans:
kill -9 $(ps -eo pid,comm,args | grep -E 'chrome|chromedriver' | grep -v grep | awk '{print $1}')
rm -f /home/ubuntu/.hermes/profiles/tarantino/Tarantino/SingletonLock \
      /home/ubuntu/.hermes/profiles/tarantino/Tarantino/SingletonCookie \
      /home/ubuntu/.hermes/profiles/tarantino/Tarantino/SingletonSocket
```

After manual solve in VNC, if the user reports "풀었음" the cookies are persisted even if the parked probe is still running — you can kill the parked probe and `create_driver()` on the next tick without re-solving. So the kill-then-spawn sequence does NOT lose session state.

### Stale handoff — Chrome dies, Python keeps sleeping (verified 2026-05-13)

The parked-Python pattern (`time.sleep(86400)` after detecting block) assumes Chrome
stays attached for the full sleep. **It doesn't always.** Observed failure mode:

- Probe script posts the VNC handoff to Slack.
- User arrives over noVNC hours later → sees an empty desktop, no Chrome window.
- `ps` shows: parent Python alive (`STAT=S`, ETIME hours), `chromedriver` as
  `<defunct>` zombie, **zero `chrome`/`google-chrome` processes**.
- The handoff post still says "차단 페이지 열린 상태" but the page is gone.

Causes (any of these): chromedriver crashed on the `/sorry/` redirect and took
Chrome with it; Chrome OOM-killed; renderer process bug on the captcha page.
Python doesn't notice because it's not interacting with the driver during sleep.

**Recovery (no need to wait for next cron tick):**

1. Confirm the failure mode:
   ```bash
   ps -p <handoff_pid> -o pid,stat,etime,cmd       # parent Python alive
   pgrep -af 'chrome|chromedriver' | grep -v grep  # only zombies / nothing
   ```
2. Kill the parked Python (reaps the zombie chromedriver) + sweep any stragglers
   using the **enumerate-then-kill** form from the SingletonLock section. Never
   `pkill -f chrome` (self-terminates the bash wrapper).
3. Clear SingletonLock/Cookie/Socket.
4. Relaunch Chrome **directly to the original blocked URL** via the wrapper —
   no Selenium, no probe re-run. The `/sorry/` page reappears and the user can
   solve in the same Tarantino profile so cookies still seed correctly:
   ```bash
   # Use terminal(background=True), NOT shell `&`/`disown` (the agent shell
   # rejects nohup/disown/setsid wrappers).
   DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority \
     /home/ubuntu/.hermes/profiles/tarantino/bin/chrome '<original /sorry/ URL>'
   ```
5. Wait ~5-6s, enumerate windows, find the WID whose title contains the search
   query or the `/sorry/` URL fragment, promote it to `(0,0) 1600×1000`.
6. Reply in the Slack handoff thread that Chrome is back up — do NOT post a
   fresh top-level handoff (it's the same incident).

This is faster than waiting a full cron interval and avoids re-running the probe
just to re-trigger the block.

**Hardening for future probes** (not yet implemented but worth doing): make the
park loop poll `len(driver.window_handles)` every N seconds and exit if Chrome
disappeared, so the handoff post auto-corrects with a "Chrome died, relaunch
needed" follow-up instead of leaving a stale "open and ready" claim.

### Variant: P2 (or any pipeline) halted on first query — no parked driver

When `p2_weekly_report.py` (or any one-shot pipeline that quits cleanly on
CAPTCHA without parking the driver) halts on Stage A Q1 with Google `/sorry/`,
there is **no live Chrome to hand off** — the pipeline already called
`driver.quit()` as part of normal shutdown. Verified 2026-05-26 (Duolog W22).

Symptom:
- Pipeline exit code 0 (it's a clean halt, not a crash)
- `pgrep -af 'chrome|chromedriver'` returns empty
- Log shows `⚠️ STAGE A HALTED on query: CAPTCHA on: 'site:tiktok.com/@ ...'`
- `Recovered 0 URLs from 0 completed queries → partial report mode`
- Empty `report.json` (~2.6KB) gets emitted with 0 trends / 0 ICP

Recovery (faster than running a fresh probe):

1. Extract the exact blocked URL from the log: it's the Q1 search URL P2
   constructed. Reconstruct via `https://www.google.com/search?q=<urlencoded query>&num=30&hl=en&tbs=qdr:w2`
   — the `qdr:w2` is P2's hardcoded recency window.
2. Launch Chrome **directly to that URL** via the wrapper (no Selenium):
   ```bash
   DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority \
     /home/ubuntu/.hermes/profiles/tarantino/bin/chrome \
     'https://www.google.com/search?q=<encoded>&num=30&hl=en&tbs=qdr:w2'
   ```
   Use `terminal(background=True)` — not shell `&`/`disown`. Chrome wrapper
   exits ~1s after launching the actual Chrome process (it just `exec`s).
3. Wait 3-5s, enumerate windows, find the WID whose title matches the search
   query (NOT the literal `google-chrome` root window).
4. Promote it to `(0,0) 1600×1000` per the recipe above. Note env-var ordering
   pitfall — `DISPLAY` must come first.
5. Post VNC handoff to Slack thread.
6. After user solves: re-run the original pipeline (e.g. `p2_weekly_report.py
   --app-id duolog`). The cookies set by the manual solve are now in the
   Tarantino profile and Stage A passes. **Don't blow away the outdir** — the
   resume cache is empty (Q1 was the first query) so `rm -rf` makes no
   difference here, but in principle the cached partial state is harmless.

Difference from the parked-Python recovery: there is no zombie chromedriver,
no SingletonLock to clear, no `kill -9` sweep needed. The pipeline shut down
cleanly. Skip straight to the wrapper-relaunch.

The user-facing handoff message is the same template as §4. **Do NOT post a
fresh "차단됨 again" alert if the user already saw the original pipeline
failure** — frame the wrapper-relaunch as continuation of the same incident.

Do this instead of trying to attach to the existing window:

```bash
# 1. Enumerate existing Chrome windows on the VNC display
DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority xdotool search --name 'Chrome' 2>/dev/null | while read wid; do
  echo "--- $wid ---"
  DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority xdotool getwindowname $wid 2>/dev/null
done
```

Pick the window whose title matches what the automation was doing (e.g. a halted Google search query) — that's the live webdriver tab the user needs to see.

```bash
# 2. Promote it to the VNC viewport
WID=<that id>
DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority bash -c "
  xdotool windowactivate $WID
  xdotool windowraise   $WID
  xdotool windowsize    $WID 1400 900
  xdotool windowmove    $WID 0 0
"
```

If you do need a fresh Chrome (automation is done, next run hasn't started, user wants to log into something manually), kill the webdriver tree first.

**PITFALL — `pkill -f 'chrome.*--user-data-dir=...'` kills YOUR terminal session** (verified 2026-05-11). `pkill -9 -f` matches against its own `bash -c` argv because the full-args pattern contains the kill pattern itself. Symptom: the `pkill` command exits with code -9 (SIGKILL) and every subsequent command in the same terminal call is silently dropped. Do NOT use the broad `-f` form on `chrome`/`chromedriver`. Enumerate PIDs first, then kill explicitly — the enumeration step filters out your own shell:

```bash
# SAFE — enumerate-then-kill, awk+grep runs in a separate process tree
for pid in $(ps -eo pid,args | \
  grep -E 'chrome.*--user-data-dir=/home/ubuntu/.hermes/profiles/tarantino/Tarantino|chrome_crashpad|chromedriver' | \
  grep -v grep | awk '{print $1}'); do
  kill -9 $pid 2>/dev/null
done
sleep 3
# Verify empty
ps -eo pid,args | grep -E 'chrome|chromedriver' | grep -v grep | wc -l   # expect 0

# Optional, only if Chrome refuses to start: rm -f /home/ubuntu/.hermes/profiles/tarantino/Tarantino/SingletonLock
rm -f /home/ubuntu/.hermes/profiles/tarantino/Tarantino/SingletonLock \
      /home/ubuntu/.hermes/profiles/tarantino/Tarantino/SingletonCookie \
      /home/ubuntu/.hermes/profiles/tarantino/Tarantino/SingletonSocket
```

**DO NOT USE** — the obvious-looking form self-terminates:
```bash
# ❌ Kills the terminal tool's own bash -c wrapper; exit code -9, silent drop.
pkill -9 -f 'chromedriver'
pkill -9 -f 'chrome.*--user-data-dir=/home/ubuntu/.hermes/profiles/tarantino/Tarantino'
```

Cookies and localStorage from the manual interaction persist in the profile and are picked up by the next automation run against the same `user-data-dir`.

### Long-Running Probes — Keep Driver Alive for VNC Handoff

When you write a probe script whose whole purpose is to **detect a block and then freeze so the human can solve in VNC**, three pitfalls cost real time:

1. **Never pipe the launcher through `| head -N`.** If you run `python probe.py 2>&1 | head -5` in the background and `head` closes its end after 5 lines, `python` gets SIGPIPE on its next `print()` and dies — taking the Selenium driver and Chrome with it. The whole "leave-alive for VNC" policy is then gone. Redirect to a file instead:
   ```bash
   # WRONG — SIGPIPE kills Chrome before user can solve
   python probe.py 2>&1 | head -5 &
   # RIGHT — full output preserved, process untouched
   python probe.py > probe.out 2>&1 &
   ```
2. **Do not call `driver.quit()` in the block path.** Script structure:
   ```python
   try:
       # probe queries / nav / detect sorry/captcha
       if blocked:
           log_state()
           post_vnc_handoff_to_slack()  # includes pid, window title
           break
   finally:
       write_log(log_path)
       # DO NOT quit the driver — human needs the live tab
       print("driver INTENTIONALLY not quit (VNC handoff policy)", flush=True)
       time.sleep(86400)  # park the process so Chrome stays up
   ```
3. **When the human solves in VNC, kill the probe session cleanly** (`process.kill` on the background session) and verify Chrome went with it before firing the actual automation. A second run against a still-held `--user-data-dir` will trip the SingletonLock section above.

Template: `scripts/probe_first_query_google.py` — probes Q01 of a Google query list, leaves driver alive on `/sorry/`, writes log to `~/.hermes/tmp/`. Copy and customize `QUERIES` / `URL_TMPL` / `is_blocked()` per task.

### Bringing the Live Window to the VNC Viewport

After the probe freezes, the solve window might be off-screen or behind other windows. Reposition before telling the user to connect:

**Critical env-var ordering pitfall (verified 2026-05-26)**: `xdotool` requires `DISPLAY` to come **before** `XAUTHORITY` in the env prefix when invoked via the agent's terminal tool. The reverse order:

```bash
# ❌ FAILS — every xdotool call returns "Error: Can't open display: (null)"
XAUTHORITY=/home/ubuntu/.Xauthority DISPLAY=:1 xdotool windowactivate $WID
```

…fails on every call because the terminal tool's bash -c wrapper does not propagate `DISPLAY` reliably when it appears second in the env prefix. The same env vars in the correct order work:

```bash
# ✓ WORKS
DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority xdotool windowactivate $WID
```

If you hit "Can't open display: (null)" repeatedly across `windowactivate`/`windowraise`/`windowsize`/`getwindowname` despite a clean `DISPLAY=:1 xdpyinfo` confirming the X server, the cause is almost certainly env-var ordering, not the X server. Two-line fallback when the bash form keeps failing — drop into Python:

```python
import os, subprocess
env = os.environ.copy()
env["DISPLAY"] = ":1"
env["XAUTHORITY"] = "/home/ubuntu/.Xauthority"
subprocess.run(["xdotool", "windowactivate", WID], env=env, check=True)
```

`subprocess.run(env=...)` always works because Python passes the env dict directly into `execvpe()` — no shell-wrapper layer to mangle it. Use this form in `execute_code` blocks when bash refuses.

**Tab-completion artifact pitfall**: do NOT type `XAUTHORITY=/home/...rity` (the literal `...rity` is a shell tab-completion fragment of `.Xauthority`). Chrome's wrapper silently ignores a bogus XAUTHORITY value (it falls back to default), but `xdotool` fails loudly. Always type the full path `/home/ubuntu/.Xauthority` or skip the var entirely if the default works.

**Recurrence 2026-05-26**: confirmed twice in one session. (1) During the Q14-handoff window-promote, an `XAUTHORITY=*** placeholder` (used while drafting commands and not replaced before send) caused four consecutive xdotool calls to fail with "Authorization required, but no authorization protocol specified". The literal `***` made it past terminal tool intake because it's syntactically valid env-var syntax, but `xdotool` parses it as a path that doesn't exist. (2) Earlier in the same session, a **background-launched Python scrape script** had the same bad `XAUTHORITY=*** in its terminal command — Chrome started anyway (Selenium's `hermes_chrome.py` resets XAUTHORITY internally), but if the scrape had needed any post-launch xdotool step it would have silently failed. The lesson: never paste secret-redaction or tab-completion placeholders into env-var values; always type the full literal `/home/ubuntu/.Xauthority` or omit the var entirely. If you find yourself drafting a command with `***` or `...rity` in any var slot, that's the bug — fix it before sending.

**Recurrence 2026-05-27 (third occurrence)**: hit it AGAIN despite the doubled warning above. Drafted four xdotool commands (`windowactivate`/`windowraise`/`windowsize`/`windowmove`) with `XAUTHORITY=***` placeholders — every call returned "Authorization required, but no authorization protocol specified / Can't open display: (null)". Re-ran with full literal `/home/ubuntu/.Xauthority` and all four succeeded immediately. **The placeholder slips in when copy-editing prior commands** that had the secret-redaction render of XAUTHORITY shown in the terminal echo — the redaction looks like a literal value at draft time. **Operating rule: before pressing send on any command containing `XAUTHORITY=`, scan the value. If it contains `*`, `...`, or anything other than a path starting with `/`, replace it with `/home/ubuntu/.Xauthority` literally.** This is the third documented occurrence (2026-05-13, 2026-05-26 ×2, 2026-05-27); treat it as a chronic operator hazard, not a one-time mistake. **Cheapest prevention**: skip `XAUTHORITY` entirely on subsequent xdotool calls in a session where the first DISPLAY=:1 call worked — the env var is often optional once X11 has authenticated the session. Test: `DISPLAY=:1 xdotool getwindowname <wid>` without XAUTHORITY. If it works, drop XAUTHORITY from the rest of the run.

```bash
# Enumerate Chrome windows — note DISPLAY first
DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority xdotool search --name 'Chrome' 2>/dev/null | while read wid; do
  title=$(DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority xdotool getwindowname $wid 2>/dev/null)
  echo "$wid | $title"
done

# Pick the real tab (not the root "google-chrome" window); promote it
WID=<that id>
DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority bash -c "
  xdotool windowactivate $WID
  xdotool windowraise   $WID
  xdotool windowsize    $WID 1600 1000
  xdotool windowmove    $WID 0 0
"
```

Two Chrome-related windows show up: the root `google-chrome` window (useless) and the actual tab whose title matches the page you navigated to. **Pick the one whose title matches the query/URL.** Sizing to 1600×1000 at `(0,0)` fits the noVNC viewport cleanly without the user having to scroll.

### Confirming Handoff Success

After the user says "풀었음" / "solved":
1. Re-check `xdotool getwindowname` on the same WID — the title should have flipped from `/sorry/...` or `captcha...` to the legitimate destination page title (e.g. query result title, video-page title). That's the cheapest proof the cookie set.
2. Verify Chrome/chromedriver count stays sane before killing the probe. If your probe script is parked in `time.sleep(86400)`, `process kill` on that session should take the driver + Chrome with it.
3. Now fire the real automation. The cookies seeded by the solve are in the Tarantino `user-data-dir` and will be inherited automatically on the next `create_driver()` call.

### Screenshots on this box — don't try

On this machine none of the common screenshot tools work:

- `PIL.ImageGrab` — `No module named 'PIL'` in the clix-growth venv (and PIL's Linux grab path needs `xdisplay` anyway).
- `import` (ImageMagick), `scrot`, `gnome-screenshot` — all missing from `$PATH`.
- `mss` (pure-Python) — fails on this X server with `drawable's visual not found in screen's supported visuals`.

Don't burn turns trying. Use `xdotool getwindowname <wid>` for title-level evidence that the right page is up, and ask the user for visual confirmation over VNC/noVNC. If a screenshot is truly required, install a working tool deliberately instead of flailing through candidates.

## Cookie Persistence — Pitfalls

1. **Selenium `add_cookie()` often creates session cookies** (is_persistent=0) that vanish on browser close, even if you set `expiry`. Unreliable for persistence.

2. **`document.cookie` via JS with explicit `expires` works reliably.** Use `set_persistent_cookie()` helper.

3. **Domain matters:** set cookies on the exact domain you're on (e.g., `www.google.com` not `.google.com`). Cross-domain cookie setting silently fails.

4. **Server-set cookies** (via HTTP Set-Cookie header with Max-Age/Expires) persist automatically.

5. **`--password-store=basic`** is required in Chrome args. Without it, Chrome uses gnome-keyring which can produce session-specific encryption keys, making cookies unreadable across restarts.

6. **localStorage persists reliably** — no encryption or keyring issues.

## create_driver() Options

```python
driver = create_driver(
    width=1920,          # window width
    height=1080,         # window height
    headless=False,      # True for headless fallback
    page_load_timeout=30,
    implicit_wait=5,
    extra_args=None,     # list of additional Chrome args
)
```

## Bot Detection Mitigations (built-in)
- `--disable-blink-features=AutomationControlled`
- `excludeSwitches: ['enable-automation']`
- `navigator.webdriver` set to undefined via CDP
- Real desktop User-Agent (not headless signature)

## Updating ChromeDriver
When Chrome auto-updates:
```bash
CHROME_VERSION=$(google-chrome --version | grep -oP '\d+\.\d+\.\d+\.\d+')
cd /tmp
curl -sL -o chromedriver.zip "https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chromedriver-linux64.zip"
unzip -o chromedriver.zip
sudo cp chromedriver-linux64/chromedriver /usr/local/bin/
chromedriver --version
```

## Profile Reset
To wipe all browser state and start fresh:
```bash
rm -rf /home/ubuntu/.hermes/profiles/tarantino/Tarantino
mkdir -p /home/ubuntu/.hermes/profiles/tarantino/Tarantino
```
