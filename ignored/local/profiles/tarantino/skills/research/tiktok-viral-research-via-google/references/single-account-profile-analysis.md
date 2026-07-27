# Analyzing a SINGLE ACCOUNT (not a topic)

When the user gives you ONE handle (e.g. `https://www.tiktok.com/@maheshowbout`) and asks
"analyze this account / why does it get views / what hashtags & keywords drive it", do NOT
lean on Google site-search — it indexes only a handful of an account's posts and you'll
miss the breakout videos. Use three layers, cheapest first.

## Layer 1 — Profile stats via direct curl (no browser, no captcha)

TikTok's profile HTML embeds a full SSR JSON blob. A mobile UA gets it cleanly from a cloud IP:

```bash
tmp=$(mktemp)
curl -fsS -A "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15" \
  "https://www.tiktok.com/@HANDLE" -o "$tmp"
```

Parse `<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">…</script>` →
`__DEFAULT_SCOPE__["webapp.user-detail"]["userInfo"]`:

```python
import re, json
html = open(tmp, encoding="utf-8", errors="ignore").read()
m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
data = json.loads(m.group(1))
ud = data["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]
user, stats = ud["user"], ud["statsV2"]
# user: uniqueId, nickname, signature (bio = product/positioning tell), region, language,
#       verified, privateAccount, bioLink
# stats: followerCount, heartCount, videoCount, friendCount
avg_likes = stats["heart"] / int(stats["videoCount"])
```

- The **bio (`signature`) is usually the product/positioning tell** — e.g. "just a girl and her
  shared calendar 💝" = a shared-calendar app's disguised marketing account.
- A **low-follower / high-video-count / high-heart** account is a *single-concept content
  machine* living off search + FYP, not follower reach. (Observed: 351 followers, 465 videos,
  282K hearts → avg 607 likes/post, but two posts carried 22.8% of all-time hearts.)
- `itemList` is **empty** in the anonymous SSR blob — it does NOT give per-video stats. Use
  layers 2/3 for those.

## Layer 2 — Per-post captions + hashtags + likes via DDG snippets

`site:tiktok.com/@HANDLE` on `https://html.duckduckgo.com/html/?q=...` returns result blocks
whose snippet text carries `"NN.N K Likes, NN Comments"` + the full caption + inline `#hashtags`.
This is where you read WHY a post worked.

```python
import re, html as ihtml, urllib.parse
raw = open("ddg.html", encoding="utf-8", errors="ignore").read()
blocks = re.findall(r'result__snippet"\s+href="//duckduckgo\.com/l/\?uddg=([^"&]+)[^>]*>(.*?)</a>', raw, re.S)
for enc_url, snip in blocks:
    real = urllib.parse.unquote(enc_url)
    txt = ihtml.unescape(re.sub(r'<[^>]*>', '', snip)).strip()
    tags = re.findall(r'#(\w+)', txt)
    ml = re.search(r'([\d.,]+)([KMm]?)\s*Likes', txt)
    # ml → likes; real → canonical /video/ or /photo/ url
```

**DDG rate-limits HARD.** A tight loop returns an `anomaly` page (body contains `"anomaly"`
and no `result__snippet`). Space calls ≥6s. Per the user's standing rule, STOP after the first
anomaly (`403`/anomaly/captcha → notify + propose alternatives, don't hammer).

## Layer 3 — Full grid (all N videos) via headful Chrome DOM scroll

TikTok's profile grid renders for anonymous headful sessions (search is walled, profile grid
usually is not). **Ready-to-run**: `scripts/profile_full_scan.py`.

- Scroll to `document.body.scrollHeight` in a loop until the
  `a[href*="/video/"], a[href*="/photo/"]` count stops growing (4 stagnant scrolls = done).
- Extract `{type,id,url,views,caption}` per card. `img[alt]` carries the caption; the
  view-count overlay is `[data-e2e="video-views"]` or a `strong` in the card footer.
- Posts can be `/video/` OR `/photo/` (slideshow/carousel). **Capture both** — slideshows
  often OUTPERFORM videos in tip/listicle niches (carousel = higher dwell + save rate, which
  the algorithm rewards). Observed: the account's two biggest posts (46.4K, 17.8K likes) were
  both photo carousels; its videos topped out in the hundreds-to-thousands.

## Decode post dates with NO API

TikTok post IDs are Snowflake-like — the creation timestamp is the top 32 bits:

```python
import datetime
def post_date(pid): return datetime.datetime.utcfromtimestamp(int(pid) >> 32).strftime("%Y-%m-%d")
```

The `oembed` endpoint (`https://www.tiktok.com/oembed?url=<post_url>`) returns `title` (= caption)
for `/video/` posts but **400s on `/photo/` posts** — don't rely on it for slideshows.

## VNC solve-then-continue: window MUST be screen-fitting

When a profile/grid scan hits the rotation captcha and you hand off to a human via VNC, the
Chrome window **must fit the display**: `create_driver(width=1440, height=900)`. A tall window
(e.g. `height=2200`, used to load more grid per scroll) pushes the puzzle + slider bar BELOW
the visible area — the human can't drag what they can't see, and the handoff silently fails.
Confirmed 2026-06-09: height=2200 cut the slider off; height=900 showed the full puzzle.

Don't park-and-die on captcha for an *interactive* scan. Use a **poll-loop**: block on
`has_captcha(driver)` for up to ~600s, and the moment it clears, reload the profile and continue
scrolling. `scripts/profile_full_scan.py` implements this.

Screenshot the VNC display for the handoff message:

```bash
DISPLAY=:1 XAUTHORITY=/home/...rity ffmpeg -y -f x11grab -video_size 1920x1080 -i :1 -frames:v 1 cap.png
```

`import` / `scrot` / `gnome-screenshot` are typically absent on this host; `xwd` and `ffmpeg`
are present — `ffmpeg x11grab` is the reliable capture. Then `vision_analyze` the PNG to confirm
the puzzle is fully on-screen before telling the user to solve it. Note `browser_vision` captures
a SEPARATE headless agent-browser instance (`/tmp/agent-browser-chrome-*`), NOT the selenium
Chrome on `DISPLAY=:1` — its screenshot will be blank for this purpose. Always use ffmpeg x11grab
for the selenium window.

## What "why does it get views" actually decomposes into

For the answer, separate the three drivers (they are NOT the same thing):
1. **Keyword/hashtag cluster** (the funnel): a broad identity tag (`#girlhood`) for reach +
   a relatable pain tag (`#busywoman`) for resonance + a solution keyword (`#sharedcalendar`)
   for intent. Single broad tags (`#bestfriends` alone) are competition hell and underperform.
2. **Caption pattern** (the real hook): "how to ___" / "the ultimate tips for ___" /
   problem-statement captions ("Hey girl, are you free next month?") are SEO-shaped — TikTok
   search + FYP matches them to query intent. This, not the hashtags, is often the true view driver.
3. **Format**: save-bait slideshows (tip/listicle carousels) vs videos. Test the format that
   drives saves in the niche.
