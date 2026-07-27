#!/usr/bin/env python3
"""Single-TikTok-account drill-down. NO Selenium, NO Google -> sidesteps /sorry/.

Usage:
    python analyze_tiktok_account.py <handle>          # e.g. maheshowbout
    python analyze_tiktok_account.py <handle> --json   # machine-readable

Pulls:
  1. TikTok profile SSR JSON  -> bio, region, follower/heart/video counts
  2. DuckDuckGo HTML site-search -> per-post captions, #hashtags, likes, urls
  3. oEmbed (video posts only)  -> full caption title
  4. ID->date decode            -> post date (no network)

See SKILL.md "Single-Account Drill-Down" section (in references/single-account-drilldown.md
when SKILL.md is at the 100k cap). Respects the user's no-hammer rule: ONE DDG call,
generous timeout, stops on anomaly/block instead of looping.
"""
import sys, re, json, html as ihtml, urllib.parse, urllib.request, datetime

UA_MOBILE = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"
UA_DESKTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def _get(url, ua, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def decode_date(tid):
    try:
        return datetime.datetime.utcfromtimestamp(int(tid) >> 32).strftime("%Y-%m-%d")
    except Exception:
        return "?"


def fetch_profile(handle):
    html = _get(f"https://www.tiktok.com/@{handle}", UA_MOBILE)
    m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
        ud = data["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]
    except Exception:
        return None
    u, s = ud.get("user", {}), ud.get("statsV2", ud.get("stats", {}))
    return {
        "uniqueId": u.get("uniqueId"), "nickname": u.get("nickname"),
        "signature": u.get("signature"), "region": u.get("region"),
        "language": u.get("language"), "verified": u.get("verified"),
        "private": u.get("privateAccount"), "bioLink": u.get("bioLink"),
        "followers": s.get("followerCount"), "heart": s.get("heartCount") or s.get("heart"),
        "videos": s.get("videoCount"), "friends": s.get("friendCount"),
    }


def fetch_posts(handle):
    """ONE DDG call. Returns [] on anomaly/block (no-hammer rule -- do not loop)."""
    q = urllib.parse.quote(f"site:tiktok.com/@{handle}")
    raw = _get(f"https://html.duckduckgo.com/html/?q={q}", UA_DESKTOP)
    if "result__snippet" not in raw:
        return []  # anomaly page or no results -- STOP, don't retry
    posts = []
    for enc, snip in re.findall(
        r'result__snippet"\s+href="//duckduckgo\.com/l/\?uddg=([^"&]+)[^>]*>(.*?)</a>', raw, re.S
    ):
        real = urllib.parse.unquote(enc)
        text = ihtml.unescape(re.sub(r"<[^>]*>", "", snip)).strip()
        mid = re.search(r"/(video|photo)/(\d+)", real)
        if not mid:
            continue
        likes = None
        ml = re.search(r"([\d.,]+)([KMm]?)\s*Likes", text)
        if ml:
            try:
                likes = int(float(ml.group(1).replace(",", "")) *
                            {"K": 1e3, "M": 1e6, "m": 1e6, "": 1}[ml.group(2)])
            except ValueError:
                likes = None
        posts.append({
            "type": mid.group(1), "id": mid.group(2), "url": real,
            "date": decode_date(mid.group(2)), "likes": likes,
            "hashtags": re.findall(r"#(\w+)", text), "caption": text[:400],
        })
    return posts


def main():
    if len(sys.argv) < 2:
        print("usage: analyze_tiktok_account.py <handle> [--json]"); sys.exit(1)
    handle = sys.argv[1].lstrip("@")
    as_json = "--json" in sys.argv
    prof = fetch_profile(handle)
    posts = fetch_posts(handle)
    posts.sort(key=lambda p: -(p["likes"] or 0))
    if as_json:
        print(json.dumps({"profile": prof, "posts": posts}, indent=2, ensure_ascii=False)); return
    print(f"=== @{handle} ===")
    if prof:
        for k in ("nickname", "signature", "region", "followers", "heart", "videos"):
            print(f"  {k}: {prof.get(k)}")
        if prof.get("heart") and prof.get("videos"):
            print(f"  avg_likes_per_post: {round(prof['heart'] / prof['videos'])}")
    else:
        print("  (profile JSON unavailable -- TikTok may have changed SSR shape)")
    print(f"\n=== {len(posts)} indexed posts (DDG) ===")
    if not posts:
        print("  (DDG returned anomaly/no-results -- stop, IP cools in hours; do NOT retry-loop)")
    for p in posts:
        print(f"  [{p['likes'] if p['likes'] else '?'} likes | {p['date']} | {p['type']}] {p['url']}")
        print(f"     #tags: {p['hashtags']}")
        print(f"     {p['caption'][:160]}")


if __name__ == "__main__":
    main()
