#!/usr/bin/env python3
"""Policy-compliant full-loop Google SERP scraper for TikTok viral research.

Counterpart to the one-shot `probe_first_query_google.py` in the
`headful-chrome-vnc` skill. This one iterates through a full query list,
halts on first /sorry/ block (per §4 VNC handoff policy — no auto-bypass),
leaves the driver + Chrome alive for human handoff, and writes structured
status + raw result JSON to an output directory.

Usage:
    # Edit QUERIES and OUT_DIR below per topic, then:
    DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority \
      /home/ubuntu/.hermes/venvs/clix-growth/bin/python \
      /path/to/scrape_google_loop.py > scrape.out 2>&1 &

    # NEVER pipe to `| head`/`| tail` — SIGPIPE kills Chrome.

Outputs (in OUT_DIR):
    google_status.json   — per-query success/block log + final verdict
    google_results.json  — list of {query, items:[{url,snippet}]}

On block, process parks in `time.sleep(86400)` so Chrome stays mounted
for the VNC solver. Kill with `kill -TERM <pid>` after the human solves
and the cookies are captured in the Tarantino profile.

See tiktok-viral-research-via-google SKILL.md §4 (Cron jobs — VNC handoff
pattern) and headful-chrome-vnc SKILL.md "Long-Running Probes" section.
"""
import sys, os, time, json, urllib.parse, datetime

sys.path.insert(0, '/home/ubuntu/.hermes/profiles/tarantino/bin')
from hermes_chrome import create_driver  # type: ignore

# ============================================================
# EDIT HERE per topic
# ============================================================
OUT_DIR = '/home/ubuntu/.hermes/tmp/cron_tiktok'

QUERIES = [
    # priority-first: head-of-list survives, tail is what you lose on block
    'site:tiktok.com/@ "college social app"',
    'site:tiktok.com/@ "campus app" college',
    # ... etc
]
URL_TMPL = "https://www.google.com/search?q={q}&num=30&tbs=qdr:w&hl=ko"
# ============================================================

os.makedirs(OUT_DIR, exist_ok=True)

EXTRACT_JS = r"""
const out = [], seen = new Set();
document.querySelectorAll('a[href*="tiktok.com/@"][href*="/video/"]').forEach(a => {
    let href = a.href;
    try {
        const u = new URL(href);
        if (u.hostname.includes('google') && u.searchParams.get('q')) href = u.searchParams.get('q');
    } catch(e) {}
    const m = href.match(/https:\/\/www\.tiktok\.com\/@[^\/]+\/video\/\d+/);
    if (!m || seen.has(m[0])) return;
    seen.add(m[0]);
    const card = a.closest('div[data-hveid], div.MjjYud, div.g') || a.parentElement;
    const snippet = card ? (card.innerText||'').slice(0,400).replace(/\n+/g,' | ') : '';
    out.push({url: m[0], snippet});
});
return out;
"""


def is_blocked(driver) -> bool:
    try:
        url = (driver.current_url or "")
    except Exception:
        url = ""
    if "/sorry/" in url or "google.com/sorry" in url:
        return True
    try:
        src = (driver.page_source or "").lower()
    except Exception:
        src = ""
    needles = [
        "detected unusual traffic", "our systems have detected",
        "unusual traffic from your computer", "비정상적인 트래픽",
    ]
    return any(n in src for n in needles)


def main():
    t0 = datetime.datetime.utcnow().isoformat() + "Z"
    print(f"[{t0}] creating driver (Tarantino profile)...", flush=True)
    driver = create_driver()
    pid = os.getpid()
    status = {
        "started_utc": t0, "pid": pid, "driver_pid": pid,
        "attempts": [], "final": None,
    }
    all_results = []

    try:
        for i, q in enumerate(QUERIES, start=1):
            url = URL_TMPL.format(q=urllib.parse.quote(q))
            ts = datetime.datetime.utcnow().isoformat() + "Z"
            print(f"[{ts}] Q{i:02d} -> {q}", flush=True)
            try:
                driver.get(url)
            except Exception as e:
                status["attempts"].append({
                    "i": i, "q": q, "error": f"driver.get failed: {e}", "ts": ts,
                })
                time.sleep(5)
                try:
                    driver.get(url)
                except Exception as e2:
                    status["attempts"].append({
                        "i": i, "q": q, "error2": f"retry failed: {e2}", "ts": ts,
                    })
                    continue
            time.sleep(4)
            if is_blocked(driver):
                cur = driver.current_url
                print(f"[{ts}] BLOCKED at Q{i:02d}: {cur}", flush=True)
                status["attempts"].append({
                    "i": i, "q": q, "url": url, "cur": cur,
                    "sorry": True, "results": 0, "ts": ts,
                })
                status["final"] = {
                    "status": "blocked", "at_query": i, "block_url": cur,
                    "detected_at_utc": ts, "driver_pid": pid,
                }
                break
            try:
                items = driver.execute_script(EXTRACT_JS) or []
            except Exception as e:
                items = []
                status["attempts"].append({
                    "i": i, "q": q, "extract_error": str(e), "ts": ts,
                })
                continue
            print(f"  -> {len(items)} items", flush=True)
            all_results.append({"query": q, "items": items})
            status["attempts"].append({
                "i": i, "q": q, "url": url, "results": len(items), "ts": ts,
            })
            # jittered 2/3/4/2/3/4 ... (skill-verified cadence for hl=ko)
            time.sleep(2 + (i % 3))

        if status["final"] is None:
            status["final"] = {"status": "ok", "at_query": len(QUERIES), "driver_pid": pid}
    except KeyboardInterrupt:
        status["final"] = {"status": "interrupted", "driver_pid": pid}
    finally:
        status["ended_utc"] = datetime.datetime.utcnow().isoformat() + "Z"
        with open(os.path.join(OUT_DIR, "google_status.json"), "w") as f:
            json.dump(status, f, indent=2, ensure_ascii=False)
        with open(os.path.join(OUT_DIR, "google_results.json"), "w") as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False)
        print(f"[done] status: {status['final']}", flush=True)

        if status["final"] and status["final"].get("status") == "blocked":
            # Leave driver alive for VNC handoff (§4 policy).
            # DO NOT call driver.quit(). Park process so Chrome stays mounted.
            print("driver INTENTIONALLY not quit (VNC handoff policy); parking 24h", flush=True)
            try:
                time.sleep(86400)
            except KeyboardInterrupt:
                pass
        else:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()
