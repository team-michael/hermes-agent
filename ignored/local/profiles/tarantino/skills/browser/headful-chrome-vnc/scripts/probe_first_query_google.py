#!/usr/bin/env python3
"""Probe Google SERP access with Tarantino headful Chrome.

Template for the 'leave-alive for VNC handoff' pattern documented in
headful-chrome-vnc SKILL.md. Customize QUERIES / URL_TMPL / is_blocked()
per task, then background-launch:

    python probe_first_query_google.py > probe.out 2>&1 &

Do NOT pipe into `| head -N` — SIGPIPE kills the driver and defeats
the handoff. See SKILL.md "Long-Running Probes" section.

Exit behavior:
- All queries pass: logs success, parks in time.sleep for 1 day so the
  human can `kill -TERM` the session explicitly when they inspect.
- First block detected: logs the block, leaves driver + Chrome up, parks.
  Human solves via noVNC (port 6080, DISPLAY=:1), then kills this session.
"""
import sys, time, json, urllib.parse, os, datetime

sys.path.insert(0, '/home/ubuntu/.hermes/profiles/tarantino/bin')
from hermes_chrome import create_driver  # type: ignore

# ============================================================
# EDIT HERE per task
# ============================================================
QUERIES = [
    # put your real queries here, priority-first
    'site:tiktok.com/@ "college social app"',
]
URL_TMPL = "https://www.google.com/search?q={q}&num=30&tbs=qdr:w&hl=ko"
LOG_PATH = '/home/ubuntu/.hermes/tmp/cron_probe/probe_log.json'
# ============================================================

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)


def is_blocked(driver) -> bool:
    """Return True if current page is a block/captcha wall.

    Customize per engine — Google /sorry/, TikTok captcha modal, Turnstile, etc.
    """
    url = (driver.current_url or "")
    if "/sorry/" in url or "google.com/sorry" in url:
        return True
    try:
        src = driver.page_source or ""
    except Exception:
        src = ""
    needles = [
        "detected unusual traffic",
        "about this page",
        "Our systems have detected",
        "unusual traffic from your computer",
        "비정상적인 트래픽",
    ]
    low = src.lower()
    return any(n.lower() in low for n in needles)


def count_results(driver) -> int:
    try:
        elems = driver.execute_script(
            "return document.querySelectorAll('div.g, div[data-hveid], div.MjjYud').length"
        )
        return int(elems or 0)
    except Exception:
        return -1


def main():
    t0 = datetime.datetime.utcnow().isoformat() + "Z"
    print(f"[{t0}] creating driver...", flush=True)
    driver = create_driver()
    log = {
        "started_utc": t0,
        "pid": os.getpid(),
        "attempts": [],
        "final": None,
    }
    try:
        for i, q in enumerate(QUERIES, 1):
            url = URL_TMPL.format(q=urllib.parse.quote_plus(q))
            ts = datetime.datetime.utcnow().isoformat() + "Z"
            print(f"\n[{ts}] Q{i:02d}: {q}", flush=True)
            try:
                driver.get(url)
            except Exception as e:
                rec = {"i": i, "q": q, "url": url, "err": f"get-failed: {e!r}",
                       "blocked": False, "ts": ts}
                log["attempts"].append(rec)
                print(f"  get-failed: {e!r}", flush=True)
                continue

            time.sleep(2.5)
            blocked = is_blocked(driver)
            nres = count_results(driver) if not blocked else 0
            cur = driver.current_url
            title = (driver.title or "")[:120]
            rec = {"i": i, "q": q, "url": url, "cur": cur, "title": title,
                   "blocked": blocked, "results": nres, "ts": ts}
            log["attempts"].append(rec)
            print(f"  cur={cur}\n  title={title}\n  blocked={blocked} results={nres}",
                  flush=True)

            if blocked:
                log["final"] = {
                    "status": "blocked",
                    "at_query": i,
                    "block_url": cur,
                    "detected_at_utc": ts,
                    "driver_pid": os.getpid(),
                }
                break
        else:
            log["final"] = {"status": "all_passed",
                            "queries_run": len(QUERIES)}
    finally:
        # DO NOT quit the driver — per headful-chrome-vnc CAPTCHA policy we
        # leave it alive so the human can solve via VNC. Caller must kill
        # this process explicitly when done inspecting.
        log["ended_utc"] = datetime.datetime.utcnow().isoformat() + "Z"
        with open(LOG_PATH, "w") as f:
            json.dump(log, f, indent=2, ensure_ascii=False)
        print(f"\nlog written → {LOG_PATH}", flush=True)
        print("driver INTENTIONALLY not quit (VNC handoff policy)", flush=True)
        time.sleep(86400)


if __name__ == "__main__":
    main()
