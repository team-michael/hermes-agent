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
- ChromeDriver: `/usr/local/bin/chromedriver` (must match Chrome major version)
- VNC Display: `:1` (TigerVNC, 1920x1080)
- noVNC: accessible via port 6080
- Python module: `/home/ubuntu/.hermes/profiles/tarantino/bin/hermes_chrome.py`
- Profile dir: `/home/ubuntu/.hermes/profiles/tarantino/Tarantino/` (Chrome user-data-dir name: "Tarantino")

## Quick Start

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
