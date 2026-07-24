#!/usr/bin/env python3
"""Full-profile scan of a single TikTok account via headful Chrome DOM extraction.

VNC-assisted: if a rotation captcha appears, BLOCK (poll) until a human solves it in
VNC (noVNC port 6080, DISPLAY=:1), then continue scrolling + extracting. Window is
screen-fitting (1440x900) so the puzzle is fully visible for the human solver.

See SKILL.md "Analyzing a SINGLE ACCOUNT" section and
references/single-account-profile-analysis.md.

Usage:
    # Edit HANDLE / OUT_DIR below, then:
    DISPLAY=:1 /home/ubuntu/.hermes/venvs/clix-growth/bin/python profile_full_scan.py \
      > scan.out 2>&1 &
"""
import sys, os, time, json, datetime
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/tarantino/bin')
from hermes_chrome import create_driver  # type: ignore

# ============ EDIT HERE ============
HANDLE = 'maheshowbout'
OUT_DIR = '/home/ubuntu/.hermes/tmp/cron_tiktok_profile'
# ===================================
PROFILE_URL = f'https://www.tiktok.com/@{HANDLE}'
os.makedirs(OUT_DIR, exist_ok=True)

EXTRACT_JS = r"""
const out = [], seen = new Set();
document.querySelectorAll('a[href*="/video/"], a[href*="/photo/"]').forEach(a => {
    const m = a.href.match(/\/(video|photo)\/(\d+)/);
    if (!m) return;
    const key = m[2];
    if (seen.has(key)) return;
    seen.add(key);
    let views = '';
    const card = a.closest('div[data-e2e="user-post-item"]') || a.parentElement;
    if (card) {
        const vc = card.querySelector('[data-e2e="video-views"], strong');
        if (vc) views = (vc.innerText || '').trim();
    }
    let caption = '';
    const img = a.querySelector('img[alt]');
    if (img) caption = (img.getAttribute('alt') || '').slice(0, 400);
    out.push({type: m[1], id: m[2], url: a.href.split('?')[0], views, caption});
});
return out;
"""

CAPTCHA_JS = "return !!document.querySelector('#captcha-verify-container-main-page, #captcha_slide_button');"


def has_captcha(driver):
    try:
        return bool(driver.execute_script(CAPTCHA_JS))
    except Exception:
        return False


def wait_for_human_solve(driver, status, max_wait=600):
    """Block until the human solves the captcha in VNC, or timeout. Returns True if solved."""
    print(f"CAPTCHA detected — waiting up to {max_wait}s for VNC solve "
          f"(noVNC 6080, DISPLAY=:1). Drag the slider puzzle.", flush=True)
    status["captcha"] = True
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if not has_captcha(driver):
            print("CAPTCHA cleared — continuing.", flush=True)
            time.sleep(3)
            return True
        time.sleep(2)
    print("CAPTCHA solve TIMED OUT.", flush=True)
    return False


def main():
    t0 = datetime.datetime.utcnow().isoformat() + "Z"
    print(f"[{t0}] driver (screen-fitting 1440x900 for VNC handoff)...", flush=True)
    # IMPORTANT: 1440x900 so the rotation puzzle is fully on-screen for the human solver.
    # A tall window (e.g. 2200) pushes the slider off-screen and the handoff silently fails.
    driver = create_driver(width=1440, height=900)
    pid = os.getpid()
    status = {"started_utc": t0, "pid": pid, "handle": HANDLE, "final": None,
              "scrolls": 0, "captcha": False}
    items = []
    try:
        driver.get(PROFILE_URL)
        time.sleep(6)
        if has_captcha(driver):
            if not wait_for_human_solve(driver, status):
                status["final"] = {"status": "captcha_timeout", "driver_pid": pid}
                raise SystemExit
            driver.get(PROFILE_URL)
            time.sleep(5)
        last, stagnant = 0, 0
        for s in range(150):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2.2)
            if has_captcha(driver):
                if not wait_for_human_solve(driver, status):
                    break
            cnt = driver.execute_script(
                "return document.querySelectorAll('a[href*=\"/video/\"], a[href*=\"/photo/\"]').length;")
            status["scrolls"] = s + 1
            if s % 5 == 0:
                print(f"  scroll {s}: {cnt} items", flush=True)
            if cnt == last:
                stagnant += 1
                if stagnant >= 4:
                    print(f"  grid fully loaded at {cnt} items (scroll {s})", flush=True)
                    break
            else:
                stagnant = 0
            last = cnt
        items = driver.execute_script(EXTRACT_JS) or []
        print(f"[extract] {len(items)} unique posts", flush=True)
        json.dump(items, open(os.path.join(OUT_DIR, "profile_items.json"), "w"),
                  indent=2, ensure_ascii=False)
        if status["final"] is None:
            status["final"] = {"status": "ok", "items": len(items), "driver_pid": pid}
    except SystemExit:
        pass
    except Exception as e:
        status["final"] = {"status": "error", "error": str(e), "items": len(items), "driver_pid": pid}
        print(f"ERROR {e}", flush=True)
        if items:
            json.dump(items, open(os.path.join(OUT_DIR, "profile_items.json"), "w"),
                      indent=2, ensure_ascii=False)
    finally:
        status["ended_utc"] = datetime.datetime.utcnow().isoformat() + "Z"
        json.dump(status, open(os.path.join(OUT_DIR, "profile_status.json"), "w"),
                  indent=2, ensure_ascii=False)
        print(f"[done] {status['final']}", flush=True)
        try:
            driver.quit()
        except Exception:
            pass


# ---- ANALYSIS snippet (run after profile_items.json exists) -------------------
# Verified 2026-06-09 on @maheshowbout (465 posts). Attributes views properly:
# rank hashtags by MEDIAN (not mean -- one outlier wrecks the mean), rank sounds,
# and report the power-law concentration honestly. See
# references/single-account-drilldown.md "Analysis depth" for the interpretation.
#
# import json, re, datetime, statistics
# from collections import defaultdict
# items = json.load(open("profile_items.json"))
# def pv(s):
#     s=(s or "").strip().upper().replace(",","")
#     m=re.match(r'([\d.]+)([KMB]?)',s)
#     if not m or not m.group(1): return 0
#     return int(float(m.group(1))*{'K':1e3,'M':1e6,'B':1e9,'':1}[m.group(2)])
# for it in items:
#     it["v"]=pv(it.get("views"))
#     it["tags"]=[t.lower() for t in re.findall(r'#(\w+)', it.get("caption","") or "")]
#     it["date"]=datetime.datetime.utcfromtimestamp(int(it["id"])>>32)
#     mm=re.search(r'created by .+ with (.+)$', it.get("caption","") or "")
#     it["sound"]=mm.group(1).strip()[:50] if mm else ""
# # hashtags by MEDIAN views (min 5 uses):
# tv=defaultdict(list)
# for it in items:
#     for t in set(it["tags"]): tv[t].append(it["v"])
# for t,v in sorted(((t,v) for t,v in tv.items() if len(v)>=5), key=lambda r:-statistics.median(r[1])):
#     print(f"#{t}: uses={len(v)} median={int(statistics.median(v))} max={max(v)}")
# # sounds by median views (min 3 uses):
# sv=defaultdict(list)
# for it in items:
#     if it["sound"]: sv[it["sound"]].append(it["v"])
# for s,v in sorted(((s,v) for s,v in sv.items() if len(v)>=3), key=lambda r:-statistics.median(r[1]))[:12]:
#     print(f"sound: {s} median={int(statistics.median(v))} uses={len(v)}")
# # power-law concentration:
# allv=sorted((it["v"] for it in items),reverse=True); tot=sum(allv) or 1
# print(f"top1={allv[0]/tot:.1%} top10={sum(allv[:10])/tot:.1%} flops<2K={sum(1 for v in allv if v<2000)/len(allv):.0%}")

if __name__ == "__main__":
    main()
