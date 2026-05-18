#!/usr/bin/env python3
"""DOM-verify top N TikTok videos for like / share / comment / favorite.

Stage 3 of the Clix pilot format-research pipeline. Reads ranked.json
(top25_by_views), hits the top 10 URLs, extracts engagement, saves to
dom_verified.json. Aborts cleanly on TikTok captcha per skill §4 policy
(leaves driver alive for VNC handoff).

Edit IN / OUT paths and TOP_N per run.

Usage:
    DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority \
      /home/ubuntu/.hermes/venvs/clix-growth/bin/python dom_verify_top10.py
"""
import sys, json, time, datetime, re

sys.path.insert(0, '/home/ubuntu/.hermes/profiles/tarantino/bin')
from hermes_chrome import create_driver  # type: ignore

IN = '/home/ubuntu/.hermes/profiles/tarantino/work/<app>/scrape/ranked.json'
OUT = '/home/ubuntu/.hermes/profiles/tarantino/work/<app>/scrape/dom_verified.json'
TOP_N = 10


def has_captcha(driver):
    try:
        return bool(driver.execute_script(
            "return !!document.querySelector('#captcha-verify-container-main-page');"))
    except Exception:
        return False


def parse_count(s):
    if not s or not isinstance(s, str):
        return None
    s = s.strip().replace(',', '')
    m = re.match(r'([0-9]*\.?[0-9]+)\s*([KkMmBb])?', s)
    if not m:
        return None
    n = float(m.group(1))
    mult = {'k': 1e3, 'm': 1e6, 'b': 1e9}.get((m.group(2) or '').lower(), 1)
    return int(n * mult)


READ_JS = r"""
const sel = s => document.querySelector(s);
const pick = s => { const e = sel(s); return e ? e.innerText : null; };
return {
  like_raw:     pick('[data-e2e="like-count"]'),
  comment_raw:  pick('[data-e2e="comment-count"]'),
  share_raw:    pick('[data-e2e="share-count"]'),
  favorite_raw: pick('[data-e2e="favorite-count"]'),
  caption:      pick('[data-e2e="browse-video-desc"], [data-e2e="video-desc"]'),
  captcha:      !!document.querySelector('#captcha-verify-container-main-page'),
};
"""


def main():
    with open(IN) as f:
        data = json.load(f)
    targets = [v['url'] for v in data['top25_by_views'][:TOP_N]]
    print(f"Targeting {len(targets)} videos")

    driver = create_driver()
    results = []
    captcha_hit = False
    try:
        for i, url in enumerate(targets, 1):
            ts = datetime.datetime.utcnow().isoformat() + "Z"
            print(f"[{ts}] {i:02d}/{len(targets)} {url}")
            try:
                driver.get(url)
            except Exception as e:
                print(f"  driver.get fail: {e}")
                continue
            time.sleep(4)
            if has_captcha(driver):
                print(f"  CAPTCHA at video {i}; aborting DOM verify")
                captcha_hit = True
                break
            try:
                d = driver.execute_script(READ_JS) or {}
            except Exception as e:
                print(f"  extract err: {e}")
                continue
            like = parse_count(d.get('like_raw'))
            share = parse_count(d.get('share_raw'))
            comment = parse_count(d.get('comment_raw'))
            favorite = parse_count(d.get('favorite_raw'))
            # Guard against share_raw='Share' string on zero-share videos
            sl = (share / like) if (isinstance(share, int) and isinstance(like, int) and like) else None
            results.append({
                'url': url,
                'like': like, 'share': share, 'comment': comment, 'favorite': favorite,
                'share_like_ratio': sl,
                'caption': (d.get('caption') or '')[:300],
            })
            print(f"  like={like} share={share} comment={comment} fav={favorite} s/l={sl}")
            time.sleep(2 + (i % 3))
    finally:
        with open(OUT, 'w') as f:
            json.dump({'captcha_hit': captcha_hit, 'verified': results}, f, indent=2, ensure_ascii=False)
        print(f"saved -> {OUT}")
        if not captcha_hit:
            try:
                driver.quit()
            except Exception:
                pass
        else:
            print("driver left alive for VNC handoff (§4 policy)")


if __name__ == "__main__":
    main()
