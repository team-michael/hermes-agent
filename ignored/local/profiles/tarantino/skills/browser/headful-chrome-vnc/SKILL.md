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
reCAPTCHA, etc.):
- **Do not spend iterations trying to auto-solve.** OpenCV angle estimation + xdotool
  drag does not beat modern trajectory-based bot detection (verified on TikTok 2026-04).
- Stop and ask the user to connect via VNC (noVNC on port 6080, DISPLAY=:1) and solve
  the captcha by hand inside the already-running Chrome window.
- After the user solves it, the Tarantino profile's cookies/session persist; continue
  automation in the same driver (don't quit) or reuse the profile in the next run.
- Offer 2Captcha/NopeCHA/CapSolver API integration only for bulk/recurring jobs where
  manual solving isn't scalable.

## Environment
- Chrome: `/usr/bin/google-chrome` (v147+)
- ChromeDriver: prefer profile-local `/home/ubuntu/.hermes/cache/chrome/chromedriver-linux64/chromedriver` when present; system `/usr/local/bin/chromedriver` may lag Chrome after auto-updates and fail on major-version mismatch.
- VNC Display: `:1` (TigerVNC, 1920x1080)
- noVNC: accessible via port 6080
- Python module: `/home/ubuntu/.hermes/profiles/tarantino/bin/hermes_chrome.py`
- Profile dir: `/home/ubuntu/.hermes/profiles/tarantino/Tarantino/` (Chrome user-data-dir name: "Tarantino")

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

## Quick Start

Diagnostic helper:

```bash
bash /home/ubuntu/.hermes/profiles/tarantino/skills/browser/headful-chrome-vnc/scripts/check_vnc_chrome.sh
```

It checks VNC, noVNC/websockify, X display, Chrome processes, and visible Chrome window titles before you ask the user to solve a CAPTCHA.

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

Do this instead:

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

If you do need a fresh Chrome (automation is done, next run hasn't started, user wants to log into something manually), kill the webdriver tree first:

```bash
pkill -f 'chromedriver'
pkill -f 'chrome.*--user-data-dir=/home/ubuntu/.hermes/profiles/tarantino/Tarantino'
sleep 2
# Optional, only if Chrome refuses to start: rm -f /home/ubuntu/.hermes/profiles/tarantino/Tarantino/SingletonLock
```

Cookies and localStorage from the manual interaction persist in the profile and are picked up by the next automation run against the same `user-data-dir`.

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
