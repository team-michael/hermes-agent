#!/usr/bin/env python3
"""Probe Google SERP access with the Tarantino headful Chrome profile.

Runs a configurable list of queries in order, stops at the first `/sorry/`
block, writes a structured JSON log, and — per the headful-chrome-vnc
async-handoff policy — leaves the driver alive so a human can solve the
challenge over noVNC.

How to run (background, so Chrome stays up):

    terminal(
        command=(
            "DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority "
            "/home/ubuntu/.hermes/venvs/clix-growth/bin/python "
            "/home/ubuntu/.hermes/profiles/tarantino/skills/browser/"
            "headful-chrome-vnc/scripts/probe_google_block.py "
            "> /tmp/probe_google.out 2>&1"
        ),
        background=True,
    )

**DO NOT** pipe stdout to `| head` / `| tail` / etc. — SIGPIPE when the
reader closes early will kill the script, chromedriver, and Chrome, which
defeats the whole point of leaving the driver alive.

After the run:

    tail /tmp/probe_google.out
    cat /home/ubuntu/.hermes/profiles/tarantino/home/.hermes/tmp/cron_tiktok/probe_google_log.json

If blocked, raise the Chrome window and ask the user to solve via VNC:

    WID=$(DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority \\
      xdotool search --name 'Chrome' 2>/dev/null | tail -n1)
    DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority bash -c "
      xdotool windowactivate $WID; xdotool windowraise $WID
      xdotool windowsize $WID 1600 1000; xdotool windowmove $WID 0 0
    "

When done, kill only the background python process (NOT chromedriver —
that's still holding the solved cookies). The process exits cleanly after
its 24h sleep, or the next cron tick can reuse the persisted profile.
"""
import sys, time, json, urllib.parse, os, datetime

sys.path.insert(0, "/home/ubuntu/.hermes/profiles/tarantino/bin")
from hermes_chrome import create_driver  # type: ignore

# Override via env if you want a different probe set
DEFAULT_QUERIES = [
    'site:tiktok.com/@ "college social app"',
    'site:tiktok.com/@ "campus app" college',
    'site:tiktok.com/@ "Fizz app"',
    'site:tiktok.com/@ "Sidechat"',
    'site:tiktok.com/@ "Yik Yak"',
]

URL_TMPL = "https://www.google.com/search?q={q}&num=30&tbs=qdr:w&hl=ko"

LOG_PATH = os.environ.get(
    "PROBE_LOG_PATH",
    "/home/ubuntu/.hermes/profiles/tarantino/home/.hermes/tmp/cron_tiktok/"
    "probe_google_log.json",
)
KEEP_ALIVE_SECS = int(os.environ.get("PROBE_KEEP_ALIVE_SECS", "86400"))


def is_sorry(driver) -> bool:
    url = (driver.current_url or "")
    if "/sorry/" in url or "google.com/sorry" in url:
        return True
    try:
        src = driver.page_source or ""
    except Exception:
        src = ""
    low = src.lower()
    return any(n in low for n in [
        "detected unusual traffic",
        "our systems have detected",
        "unusual traffic from your computer",
        "비정상적인 트래픽",
    ])


def count_results(driver) -> int:
    try:
        n = driver.execute_script(
            "return document.querySelectorAll('div.g, div[data-hveid], "
            "div.MjjYud').length"
        )
        return int(n or 0)
    except Exception:
        return -1


def main() -> int:
    queries_env = os.environ.get("PROBE_QUERIES")
    if queries_env:
        queries = [q for q in queries_env.split("|") if q.strip()]
    else:
        queries = DEFAULT_QUERIES

    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

    t0 = datetime.datetime.utcnow().isoformat() + "Z"
    print(f"[{t0}] creating driver (pid={os.getpid()})...", flush=True)
    driver = create_driver()
    log = {
        "started_utc": t0,
        "pid": os.getpid(),
        "queries_total": len(queries),
        "attempts": [],
        "final": None,
    }
    try:
        for i, q in enumerate(queries, 1):
            url = URL_TMPL.format(q=urllib.parse.quote_plus(q))
            ts = datetime.datetime.utcnow().isoformat() + "Z"
            print(f"\n[{ts}] Q{i:02d}: {q}", flush=True)
            try:
                driver.get(url)
            except Exception as e:
                log["attempts"].append({
                    "i": i, "q": q, "url": url, "err": f"get-failed: {e!r}",
                    "sorry": False, "ts": ts,
                })
                print(f"  get-failed: {e!r}", flush=True)
                continue

            time.sleep(2.5)
            sorry = is_sorry(driver)
            nres = count_results(driver) if not sorry else 0
            cur = driver.current_url
            title = (driver.title or "")[:120]
            print(f"  cur={cur}\n  title={title}\n  sorry={sorry} results={nres}",
                  flush=True)
            log["attempts"].append({
                "i": i, "q": q, "url": url, "cur": cur, "title": title,
                "sorry": sorry, "results": nres, "ts": ts,
            })

            if sorry:
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
                            "queries_run": len(queries)}
    finally:
        log["ended_utc"] = datetime.datetime.utcnow().isoformat() + "Z"
        with open(LOG_PATH, "w") as f:
            json.dump(log, f, indent=2, ensure_ascii=False)
        print(f"\nlog written → {LOG_PATH}", flush=True)
        # DO NOT driver.quit(). Keep Chrome alive for VNC handoff.
        print(f"driver INTENTIONALLY not quit; sleeping "
              f"{KEEP_ALIVE_SECS}s (VNC handoff policy)", flush=True)
        time.sleep(KEEP_ALIVE_SECS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
