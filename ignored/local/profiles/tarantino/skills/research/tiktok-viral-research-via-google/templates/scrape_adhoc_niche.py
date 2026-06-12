#!/usr/bin/env python3
"""Ad-hoc niche concept scraper — Google SERP -> TikTok URLs (ALL-TIME).

Known-good template (verified 2026-06-11, date niche: 157 unique videos,
96 with hard view counts before block at Q13). Copy to
~/.hermes/profiles/tarantino/work/<niche>/, then edit:
  1. OUT_DIR
  2. QUERIES  — PRIORITY-FIRST. Blocks commonly land around Q12-13;
     anything past Q12 is a bonus, so front-load must-answer clusters.
  3. URL_TMPL — keep all-time for "what concepts WORK"; add &tbs=qdr:w
     for "what's trending NOW" (see references/adhoc-niche-concept-research.md).

Run: cd <OUT_DIR>/.. && DISPLAY=:1 \
  /home/ubuntu/.hermes/venvs/clix-growth/bin/python scrape_<niche>.py > scrape.out 2>&1
(background=true, notify_on_complete=true; progress via `tail scrape.out`)
"""
import sys, os, time, json, urllib.parse, datetime

sys.path.insert(0, '/home/ubuntu/.hermes/profiles/tarantino/bin')
from hermes_chrome import create_driver  # type: ignore

OUT_DIR = '/home/ubuntu/.hermes/profiles/tarantino/work/CHANGE_ME/scrape'
os.makedirs(OUT_DIR, exist_ok=True)

QUERIES = [
    # PRIORITY-FIRST. Quote exact phrases to lock the format.
    'site:tiktok.com/@ "CHANGE ME"',
    'site:tiktok.com/@ "CHANGE ME TOO"',
]
URL_TMPL = "https://www.google.com/search?q={q}&num=30&hl=ko"   # all-time

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
    status = {"started_utc": t0, "pid": pid, "driver_pid": pid,
              "attempts": [], "final": None}
    all_results = []

    try:
        for i, q in enumerate(QUERIES, start=1):
            url = URL_TMPL.format(q=urllib.parse.quote(q))
            ts = datetime.datetime.utcnow().isoformat() + "Z"
            print(f"[{ts}] Q{i:02d} -> {q}", flush=True)
            try:
                driver.get(url)
            except Exception as e:
                status["attempts"].append({"i": i, "q": q, "error": str(e), "ts": ts})
                time.sleep(5)
                try:
                    driver.get(url)
                except Exception as e2:
                    status["attempts"].append({"i": i, "q": q, "error2": str(e2), "ts": ts})
                    continue
            time.sleep(4)
            if is_blocked(driver):
                cur = driver.current_url
                print(f"[{ts}] BLOCKED at Q{i:02d}: {cur}", flush=True)
                status["attempts"].append({"i": i, "q": q, "url": url, "cur": cur,
                                           "sorry": True, "ts": ts})
                status["final"] = {"status": "blocked", "at_query": i,
                                   "block_url": cur, "driver_pid": pid}
                break
            try:
                items = driver.execute_script(EXTRACT_JS) or []
            except Exception as e:
                items = []
                status["attempts"].append({"i": i, "q": q, "extract_error": str(e), "ts": ts})
                continue
            print(f"  -> {len(items)} items", flush=True)
            all_results.append({"query": q, "items": items})
            status["attempts"].append({"i": i, "q": q, "results": len(items), "ts": ts})
            time.sleep(2 + (i % 3))  # jittered 2/3/4 cadence

        if status["final"] is None:
            status["final"] = {"status": "ok", "at_query": len(QUERIES), "driver_pid": pid}
    except KeyboardInterrupt:
        status["final"] = {"status": "interrupted", "driver_pid": pid}
    finally:
        # NOTE: results are written BEFORE parking — on block you can parse +
        # ship partial data immediately, then kill the parked driver.
        status["ended_utc"] = datetime.datetime.utcnow().isoformat() + "Z"
        with open(os.path.join(OUT_DIR, "google_status.json"), "w") as f:
            json.dump(status, f, indent=2, ensure_ascii=False)
        with open(os.path.join(OUT_DIR, "google_results.json"), "w") as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False)
        print(f"[done] status: {status['final']}", flush=True)

        if status["final"] and status["final"].get("status") == "blocked":
            print("driver INTENTIONALLY left alive for VNC handoff; parking 1h", flush=True)
            try:
                time.sleep(3600)
            except KeyboardInterrupt:
                pass
        else:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()
