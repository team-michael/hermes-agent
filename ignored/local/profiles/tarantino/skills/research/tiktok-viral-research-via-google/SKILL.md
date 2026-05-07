---
name: tiktok-viral-research-via-google
description: Find viral TikTok videos on a topic by scraping Google site-restricted search instead of TikTok itself. TikTok's web search is gated by captcha + login wall; Google SERPs leak TikTok view counts in snippets, making them the reliable path for ranking viral TikToks without a logged-in session.
tags: [tiktok, research, growth, viral, google, scraping, selenium]
---

# TikTok Viral Research via Google Site-Search

## When to Use
- User asks for viral TikTok videos on a topic (e.g. "couple app", "meditation app", "skincare")
- User wants TikTok video URLs + approximate view counts without logging into TikTok
- App growth / content marketing reconnaissance (competitor analysis, hook mining, ICP discovery)

## Why NOT TikTok directly
`https://www.tiktok.com/search/video?q=...` on headful Chrome (even with the persistent profile from `headful-chrome-vnc`) hits a **slider captcha + login wall**. Observed April 2026:
- `document.querySelectorAll('a[href*="/video/"]').length` returns `0`
- `document.body.innerText` contains `"Drag the slider to fit the puzzle"` and `"Log in"`
- Video cards never render for anonymous sessions

Don't waste cycles on TikTok's own search. Go via Google.

## Don't Bother: Auto-Solving the TikTok Rotation Captcha
Empirically confirmed unreliable (April 2026). The captcha is a 2-puzzle rotation: outer disc 347×347, inner puzzle 211×211, slide button travels 0..284px mapped to 0..360° rotation.

Things tried that **did not work**:
- OpenCV rotation sweep with template-matching + circular mask. Gets close (score ~0.3) but not reliably within ±5°.
- Polar-unroll both images to `(n_r × n_theta)` strips, 2D FFT circular cross-correlation along theta axis. Better mathematically (score 1.2–3.0) but still fails on most captcha instances — inner and outer share too little pixel-level signal.
- Human-ish drag via `selenium.webdriver.common.action_chains.ActionChains` with chunked motion + jitter: detected as bot.
- OS-level X11 drag via `xdotool mousemove/mousedown/mouseup` on `DISPLAY=:1` with easing curve + overshoot: still detected. TikTok appears to run a second trajectory-score layer beyond positional correctness.

Even when the estimated angle was correct, the drag trajectory itself was scored and rejected. 6 attempts × refresh = 0 solves.

**The working fallback**: have a human solve the captcha once via VNC (noVNC port 6080), which establishes session cookies in the `Tarantino` profile that suppress captcha for hours-to-days. Then either:
- Resume TikTok direct search with the warmed profile, OR
- Just use this Google-site-search skill — it's faster and gives you view counts for free.

### VNC-Assisted TikTok Direct-Search Pattern
If you need data only available in TikTok's own UI (e.g. precise likes/comments/shares, current search ranking, poster images), use this poll-loop pattern. Launch Chrome, open a search URL, and BLOCK on a DOM-level captcha detector until the user solves it in VNC. Then iterate through all queries automatically:

```python
def has_captcha():
    return driver.execute_script(
        "return !!document.querySelector('#captcha-verify-container-main-page');"
    )

# Wait up to 10 min for human to solve in VNC
deadline = time.time() + 600
while time.time() < deadline and has_captcha():
    time.sleep(2)
# After solve, cookie/session persists — subsequent driver.get() to other
# search queries usually do NOT retrigger captcha within the same driver.
```

Tell the user explicitly: "VNC에 접속해서 Chrome 창의 회전 퍼즐을 풀어주세요. 풀리는 즉시 자동으로 진행됩니다." Don't block indefinitely — 10-minute timeout keeps the process reapable.

### When to use TikTok direct vs Google
They return different populations and you often want both:
- **Google site-search** → historical hits (includes years-old 23M-view spikes). Good for "what hooks have ever worked"
- **TikTok in-app search** → what's currently ranking for that query NOW (algorithm-picked top ~12 per query). Good for "who is actively competing for this keyword today"

A video appearing in TikTok's top results across 4+ related queries is a strong signal that TikTok has designated it as the canonical answer for the topic — those accounts deserve a profile-level scan regardless of absolute view count.

DOM hooks for reference if someone wants to retry with a paid captcha-solving API (2Captcha, NopeCHA, CapSolver):
- Captcha modal: `#captcha-verify-container-main-page`
- Slider button: `#captcha_slide_button`
- Refresh: `#captcha_refresh_button`
- Two images live inside the container as `<img src="data:image/webp;base64,...">`; the larger one (347×347) is outer, smaller (211×211) is inner.
- Slider track: walk up 3 parents from the button and find the element with class containing both `rounded-full` and `UISheet`. Track width minus button width = max drag pixels.

## The Trick: Google SERP Leaks View Counts
Google's Korean (and other locale) rich results for TikTok embed the view count directly in the snippet text:

```
Best Apps for Couples: Cute Sites & Widgetable ... | TikTok · @abjyy | 조회수 2350만회 이상 · 2년 전 | 0:20 | ...
```

Parse that. No TikTok API, no captcha, no login.

## Procedure

### 1. Setup (depends on `headful-chrome-vnc` skill)
Use the **clix-growth venv Python** (Python 3.11), NOT system `python3.12`. Selenium is installed at `/home/ubuntu/.hermes/venvs/clix-growth/lib/python3.11/site-packages/selenium` — NOT in the tarantino profile's `home/.local/lib/python3.12` path (that directory is empty as of 2026-05-07).

```bash
# Correct interpreter for all scrape scripts:
DISPLAY=:1 /home/ubuntu/.hermes/venvs/clix-growth/bin/python your_script.py

# Verify before running:
/home/ubuntu/.hermes/venvs/clix-growth/bin/python -c "import selenium; print(selenium.__version__)"
# Expected: 4.43.0 or newer
```

If you ever see `ModuleNotFoundError: No module named 'selenium'` from a `python3.12` invocation, that's the wrong interpreter — switch to the venv path above. `hermes_chrome.py` itself works fine under either, but only the venv has selenium.

### 2. Query design
Run ~10 variant queries to widen coverage. Mix generic + specific + competitor names. Template:
```
site:tiktok.com/@ "exact phrase"
```
The `/@` anchors results to user video pages (format `tiktok.com/@<handle>/video/<id>`), filtering out TikTok Shop / music / tag pages.

Example for "couple app":
- `site:tiktok.com/@ "couple app"`
- `site:tiktok.com/@ "couples app"`
- `site:tiktok.com/@ "relationship app"`
- `site:tiktok.com/@ "long distance app"`
- `site:tiktok.com/@ "paired app"` (+ known competitor names)

### Time-restricted search (recent N days/weeks)
Add `&tbs=qdr:X` to the Google URL to restrict by recency:
- `qdr:h` = past hour
- `qdr:d` = past 24 hours
- `qdr:w` = past week ← most common for "what's trending now"
- `qdr:m` = past month
- `qdr:y` = past year

Example: `https://www.google.com/search?q=...&num=30&tbs=qdr:w&hl=ko`

**Important caveat about `qdr:w` behavior**: Google's "past week" filter leaks slightly — results up to ~8 days old can slip through. Don't trust the filter alone; always re-verify with `parse_age_days` and post-filter to `age_days <= 8` (or your target threshold).

**What to expect from a 1-week window**:
- Absolute view counts collapse dramatically vs all-time search. A typical all-time top video is 1M-10M views; a past-week top is usually 10K-500K.
- This is fine and actually useful. The 1-week window is for finding **replicable format machines** (creators who consistently post the same successful format), not megahits.
- Pay extra attention to `share/like ratio` in this mode. A 145K-view video with `259 shares / 381 likes = 68%` is a stronger signal than a 4.6M-view video with 2% share rate — the share-rate outlier is the true viral engine.

### 3. Scrape script
```python
import sys, time, json, urllib.parse
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/tarantino/bin')
from hermes_chrome import create_driver

driver = create_driver(width=1440, height=900)
results = {}
for q in QUERIES:
    url = f"https://www.google.com/search?q={urllib.parse.quote(q)}&num=30"
    driver.get(url); time.sleep(4)
    items = driver.execute_script("""
        const out = [], seen = new Set();
        document.querySelectorAll('a[href*="tiktok.com/@"][href*="/video/"]').forEach(a => {
            let href = a.href;
            try {
                const u = new URL(href);
                if (u.hostname.includes('google') && u.searchParams.get('q')) href = u.searchParams.get('q');
            } catch(e) {}
            const m = href.match(/https:\\/\\/www\\.tiktok\\.com\\/@[^\\/]+\\/video\\/\\d+/);
            if (!m || seen.has(m[0])) return;
            seen.add(m[0]);
            const card = a.closest('div[data-hveid], div.MjjYud, div.g') || a.parentElement;
            const snippet = card ? (card.innerText||'').slice(0,300).replace(/\\n+/g,' | ') : '';
            out.push({url: m[0], snippet});
        });
        return out;
    """)
    results[q] = items
driver.quit()
```

### 4. Parse Korean view counts from snippets
```python
import re
def parse_views(text):
    # 조회수 2350만회 이상 / 조회수 41.3만회 이상 / 조회수 210만회 이상 / 조회수 9.5천회 / 조회수 120회
    m = re.search(r'조회수\s*([0-9.,]+)\s*(만|천|억)?\s*회', text)
    if not m: return 0
    num = float(m.group(1).replace(',', ''))
    mult = {'만': 10000, '천': 1000, '억': 100000000, None: 1}[m.group(2)]
    return int(num * mult)

def parse_age_weeks(text):
    m = re.search(r'(\d+)\s*(주|개월|년|일)\s*전', text)
    if not m: return 9999
    n, unit = int(m.group(1)), m.group(2)
    return {'일': n/7, '주': n, '개월': n*4.3, '년': n*52}[unit]

# For 1-day precision (needed with qdr:w filter):
def parse_age_days(text):
    m = re.search(r'(\d+)\s*(일|주|개월|년)\s*전', text)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return {'일': n, '주': n*7, '개월': n*30, '년': n*365}[unit]
    m = re.search(r'(\d+)\s*(hour|day|week|month|year)s?\s*ago', text, re.I)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        return {'hour': 0, 'day': n, 'week': n*7, 'month': n*30, 'year': n*365}[unit]
    # "14시간 전" / "3 hours ago" / "30분 전" → same day
    if re.search(r'(\d+\s*(hour|시간|분))\s*전?', text, re.I):
        return 0
    return 999999
```

### 4b. Noise filtering for target-market focus
Google site-search returns ALL locales for a Latin-alphabet keyword. A query like `"locket app"` will return Vietnamese, Indonesian, K-pop fandom, and jewelry-commerce videos that are irrelevant to a North American college ICP. Post-filter with both handle blocklists and snippet keyword blocklists:

```python
NOISE_HANDLES = {'cortis_bighit', 'locketcameravn', 'locketgold',
                 'pthanamjewellersbahau', 'charmr_app', ...}  # spam/irrelevant accounts
NOISE_SNIPPET = ['cortis', 'vietnam', 'việt nam', 'bahau', 'indonesia',
                 'bighit', 'pt hanam', 'jewellers']  # lowercase substring match

def passes_filter(v):
    if v['handle'].lower() in NOISE_HANDLES: return False
    snip_lower = v['best_snippet'].lower()
    if any(n in snip_lower for n in NOISE_SNIPPET): return False
    return True
```

Build `NOISE_HANDLES` iteratively — after the first scrape, scan the top 30 results manually and add any handle that's clearly off-ICP (non-target-country, unrelated business, K-pop mega-fandom that just happened to name-drop the app).

### 5. Deduplicate + rank
Same video can appear under multiple queries (good signal: `len(queries)` = topic-centrality). Sort by `(-views, age_weeks)` primarily.

### 6. Verify URLs return 200
```python
import urllib.request
req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
urllib.request.urlopen(req, timeout=10).status  # expect 200
```

## Extending to Instagram / YouTube Shorts / Reddit
The same `site:<domain>` Google SERP trick extends to other platforms. Use these regexes to extract URLs from aggregated SERP items:

```python
TIKTOK_VIDEO_RE = re.compile(r"https?://(?:www\.)?tiktok\.com/@[^/\s?#]+/video/\d+")
YT_SHORTS_RE    = re.compile(r"https?://(?:www\.)?youtube\.com/shorts/[A-Za-z0-9_-]{6,}")
IG_POST_RE      = re.compile(r"https?://(?:www\.)?instagram\.com/(?:p|reel|reels)/[A-Za-z0-9_-]{5,}")
REDDIT_POST_RE  = re.compile(r"https?://(?:www\.|old\.)?reddit\.com/r/[A-Za-z0-9_]+/comments/[A-Za-z0-9]+(?:/[^\s)]*)?")
```

Query templates that work:
- TikTok: `site:tiktok.com/@ "<keyword>"` (the `/@` anchor filters out TikTok Shop / music pages)
- Instagram: `site:instagram.com/reel "<keyword>"` or `site:instagram.com/p "<keyword>"`
- YouTube Shorts: `site:youtube.com/shorts "<keyword>"`
- Reddit: `site:reddit.com "<keyword>"` or `site:reddit.com/r/<sub> <keyword>`

### Why Reddit must go through Google too
Reddit's public `.json` endpoints (both `www.reddit.com/r/X/search.json` and `/r/X.json`) return **HTTP 403 "Blocked"** from cloud server IPs (observed 2026-04-27 on this Hermes host — curl with polite User-Agent still 403s, `old.reddit.com` also 403s). Do NOT waste cycles on direct JSON fetches from shared hosting. Go via `site:reddit.com` on Google and dedupe with URL normalization — `/comments/<id>/.../comment/<id2>` fragments all collapse to the parent thread:

```python
def normalize_url(url: str) -> str:
    u = url.split("#")[0].split("?")[0].rstrip("/")
    # Collapse /comments/<thread>/<slug>/comment/<comment_id> -> thread root
    u = re.sub(r"(/comments/[a-z0-9]+)/[^/]+/comment/[a-z0-9]+$", r"\1", u)
    return u
```

### English SERP snippet parsers (Korean equivalents already above)
English Google SERPs leak metrics slightly differently from Korean. These patterns cover ~90% of scraped TikTok / Instagram / YouTube / Reddit items:

```python
def parse_en_views(text: str) -> int:
    # "3.4K+ views · 2 weeks ago", "82.1K+ views", "1.9K+ likes", "610+ views"
    m = re.search(r"([\d.,]+)\s*([KkMmBb])\+?\s*(?:views|plays|likes)", text)
    if m:
        return int(float(m.group(1).replace(",", "")) *
                   {"k":1e3,"m":1e6,"b":1e9}[m.group(2).lower()])
    m = re.search(r"([\d,]+)\s*(?:views|plays|likes)", text, re.I)
    if m:
        return int(m.group(1).replace(",", ""))
    return 0

def parse_reddit_signal(text: str) -> dict:
    # "20+ comments", "29 answers", "3 comments"
    out = {"comments": 0, "answers": 0}
    m = re.search(r"(\d+)\+?\s*comments", text, re.I)
    if m: out["comments"] = int(m.group(1))
    m = re.search(r"(\d+)\s*answers?", text, re.I)
    if m: out["answers"] = int(m.group(1))
    return out
```

The `\+?` in the regex is critical — Google often renders `82.1K+` rather than `82100`; the `+` is a floor-indicator, not a typo. Missing that one char drops view-count extraction from ~11/15 to ~1/15.

### Keyword pollution from single-word competitor names
Short competitor names that are also common English words cause massive noise. Observed examples (2026-04-27, couple-app run):
- `"Between"` → Atsuko comedy ("Nothing Comes Between Me and My Ranch", 82K views), country song cover, unrelated dating-show poll
- `"Couple"` / `"Raft"` / `"Retro"` / `"Lapse"` all have similar problems

**Fix**: Always wrap short/ambiguous competitor names with `app` disambiguator, e.g. `site:tiktok.com/@ "Between app"` instead of `"Between"`. For truly unique names (`Locket Widget`, `BondBeyond`, `Widgetable`, `SumOne`) the bare name is fine.

### TikTok keyword-cluster pollution
Some keyword clusters are owned by non-app content on TikTok and produce 60%+ noise regardless of competitor wrapping:
- `"relationship diary"` → reality-TV confessional format (Perfect Match Xtra, Big Brother diary room clips)
- `"couple diary"` → same
- `"journal"` (bare) → bullet journal / planner content
- `"lapse app"` → construction-site timelapse + study-timelapse creators (e.g. `@snitchcam`, `@uyumiez`). Almost zero real Lapse-the-social-app content. For Lapse research, use `"lapse social app"` or `"lapse photo dump"` instead.
- `"saturn app"` → **Samsung lock-screen widget tutorial accounts** dominate (`@carterpcs`, `@sstech00`, `@ahmedmaherr11`). These are phone-tips channels that use Saturn as one of many widget examples, not Saturn-app promotion. High view counts (715K+) but **format template only applies if you're teaching widget setup** — don't mistake the traffic for Saturn ICP interest. For Saturn-the-social-app research use `"saturn app college"` or `"saturn time zones"`.
- `"bereal"` → 2026-era BeReal content is dominated by nostalgia/decline framing ("remember when BeReal was everyone's highlight of the day"). Useful as a **reverse ICP signal** (what not to become) but not as a replicable format for a live growing app.
- `"find my friends app"` → (observed as a captcha-skipped query 2026-04-29; anticipated pollution: Apple Find My stock-app content + location-tracking couple content, not social-graph app discovery)

When your SERP is dominated by reality-TV, crafting, phone-tips, or nostalgia content, you've hit a polluted cluster. Pivot to more specific queries (`"relationship diary app"`, `"daily couple photo app"`, `"lapse social app"`) or accept the cluster is dead for app-discovery purposes and report it as a warning. **Action item at report time**: list the polluted clusters you detected — next run can pre-emptively swap them.

## Pitfalls
- **Do NOT use `/home/ubuntu/.hermes/hermes-agent/venv/bin/python`** — selenium isn't installed there.
- **Do NOT use bare `python3.12`** either — the skill's original claim that selenium lives at `~/.hermes/profiles/tarantino/home/.local/lib/python3.12/site-packages` is **stale/incorrect** (directory is empty as of 2026-05-07). The working interpreter is `/home/ubuntu/.hermes/venvs/clix-growth/bin/python` (Python 3.11, selenium 4.43.0). Verify before every cron run: `/home/ubuntu/.hermes/venvs/clix-growth/bin/python -c "import selenium"`.
- **Google redirect URLs**: sometimes `a.href` starts with `/url?q=...`. The JS above extracts the real TikTok URL via regex on the href text; don't rely on `a.href` alone.
- **Locale matters**: Korean SERPs give `조회수 X만회`. English SERPs show `X views` differently — adapt the regex if running with different `&hl=` param.
- **View count is approximate**: "조회수 2350만회 이상" is a rounded floor. Treat rankings as ordinal, not precise.
- **Age heuristic is rough**: `2년 전` could be 24-35 months. Use only for tiebreaking.
- **Likes fallback is noisy**: some snippets only show likes ("3673 Likes"). A 20x likes→views heuristic exists in the script but is unreliable; prefer videos where `조회수` is explicitly parsed.
- **Google rate limiting**: ~10 queries back-to-back is fine. If you go heavier, add randomized sleeps or rotate IPs.
- **Google CAPTCHA on qdr:w heavy runs**: observed 2026-04-27 — after ~14 consecutive `tbs=qdr:w` queries the Selenium session redirects to `/sorry/` captcha page. Detect via `'unusual traffic' in body.lower()` or `'/sorry/' in driver.current_url` and skip+log the failed query instead of crashing. In headless/cron contexts, just record which queries were skipped and note it in the delivered report. Confirmed again 2026-04-29 (`hl=ko`, 18-query college-app run): 12 queries completed, 6 tail queries skipped on `/sorry/`. Treat **12–14 queries as the realistic ceiling per driver session on `hl=ko`** and **order your query list so the highest-value / hardest-to-re-cover ones run first** — the tail of the list is the part you'll lose.
- **English-locale (`hl=en&gl=us`) burn rate is ~40% faster**: observed 2026-04-28 — `/sorry/` hit after only 9 consecutive `qdr:w` queries (vs ~14 on `hl=ko`). Treat **8 queries as the soft ceiling per driver session on `gl=us`**. A 45-second cool-down + retry in the same session does NOT work; Google remembers the session-level signal. Either (a) accept partial coverage and ship, or (b) rotate the Chrome profile and wait hours before re-attempting. Per Soomin's error-halt rule, do NOT loop retries — halt and report.
- **Partial-coverage reports are usually decision-grade**: if 5/14 queries captcha but you already have 30+ past-week candidates and have run the direct-TikTok engagement scrape on the top 15, the virality conclusion (share/like winners, format clusters, creator repetition) is strong enough to ship. Flag the missing queries explicitly so the user can choose to unblock them via VNC, but **do not block the deliverable** waiting for full coverage. Missed queries tend to be adjacent sub-niches (e.g. `date night ideas app`, `shared calendar for couples`, `relationship app` missed on a couple-app run → married/cohabiting sub-segment), worth noting as a coverage gap in the report rather than as a pipeline failure.
- **NA-college social-app noise handles** (add to `NOISE_HANDLES`/snippet blocklist when running college-app queries): `marymarketingirlie` (Italian), `locketgold6.0pro` (mod spam), `johnleggottcollege` (UK sixth-form), `techrosen`/`jisuinparis` (UK/FR), `cymru` (Wales), `mediamarkt_hb_weserpark` (German Saturn retail), `somnia.plus` (dorm-bed product, not social), admissions-coach handles (`vibrantcollegeadvising`, `experthan`, `collegexpert`, `essayhelpbyhollee`, `misterjensen`, `saraharberson`) — these hit the keyword but are off-ICP for NA-college-social-app targeting. **Added 2026-05-06**: `play_and_win_telenor` (Pakistan Telenor quiz ride-along on "SumOne"), `plantslapstime1` (gardening timelapse — wins `"lapse social app"` cluster), `rubix_learning` (Australian ATAR study-coach, wrong country), `atraccioninterpersonal` (Spanish-language relationship-psychology), `iamthatenglishteacher` (K-12 grammar channel, wrong age-segment).
- **TikTok captcha vs genuine failure**: if you do try TikTok directly and get 0 video anchors, check `document.body.innerText` for `"Drag the slider"` — that confirms captcha, not a query problem.

## Creator-as-Format-Factory Rule (how to operationalize "cluster ≥ 3")

Soomin's principle #2 says "single viral video ≠ trend, require clustering ≥ 3 as evidence." On TikTok the strongest instantiation is **same creator + same format repeated across the top-N window**:

- **Strong signal**: one handle appears 3+ times in the top-15-by-share/like with consistent s/l ratio (e.g. `@haileylovesss15` hit top-15 five times in couple-app run, s/l 33.9 / 31.7 / 10.6 / 8.1 / 6.2). That's a replicable format machine, not a lucky hit.
- **Weak signal**: one 1M+ view outlier from a handle that never repeats. Interesting as a hook reference but not a template to copy.
- **Medium signal**: same format pattern appearing across 3+ different creators (harder to detect from Google SERP alone; requires per-video caption/hashtag comparison).

When writing the report, rank formats by (creator-repetition count × median s/l) rather than raw max-views. A format that produced 5× s/l>15% videos from one creator beats a format that produced one 1.8M-view one-hit-wonder. It's also the right input for action-item writing: the replicable format is the one worth instructing UGC creators to copy.

## Query-Design Rule: Semantic-Family Overlap

Observed 2026-05-06 (NA-college-social-app run, 18 queries, 167 raw results): **top-10-by-DOM-likes had 9/10 videos at q=1** (matched by exactly one query). Only `@limmytalks` hit q=4. That's a query-design failure, not a data failure — each of the 18 queries probed a different sub-niche (`roommate finder` / `dorm life` / `college freshman` / `find friends college` / `anonymous college` all sound similar to humans but Google tokenizes them as disjoint), so the cross-query intersection signal the skill relies on for "format worth copying" was dead on arrival.

**Fix**: design queries in **semantic-family clusters of 3-5 near-synonyms** so a genuinely central video can plausibly land in ≥3 of them:

- Friend-discovery cluster: `"college friend app"`, `"find friends college app"`, `"meet people college app"`, `"campus friend app"`, `"college social app"`
- Dorm-life cluster: `"dorm life app"`, `"college dorm app"`, `"roommate app college"`, `"dorm room app"`
- Anonymity cluster: `"anonymous college app"`, `"college confession app"`, `"anon campus app"`, `"yik yak college"` (rather than `"Yik Yak"` alone which pulls brand-agnostic posts)

Avoid spending budget on single-word competitor names that produce 1 result (`"BondBeyond"` returned 1 in this run — no leverage). Either wrap with disambiguator or drop.

**Diagnostic**: if your final Top 10 is >80% q=1, you lost the centrality signal. Report it as a coverage warning AND pre-emptively redesign the query list for the next run. Don't treat the Top 10 as bias-free ranking in that state.

## Output Template
Deliver as a table (rank, views, URL, one-line hook) plus a pattern-analysis section that surfaces:
- dominant content format (listicle / single-app tutorial / comparison / couple-game)
- ICP concentration (e.g. LDR-heavy vs general)
- competitor app names mentioned (for landscape mapping)
- concrete next-step content experiments derived from the pattern

The raw aggregated JSON should be saved to `/tmp/tiktok_top.json` so the user can request deeper slices.

## Virality Scoring: Share/Like Ratio > View Count
When you move from ranking to deep-dive analysis (per-video page scraping via TikTok direct), don't stop at absolute views/likes. The highest-leverage metric is **Share / Like ratio**:

- TikTok baseline average share rate: **1–3% of likes**
- Organic "sender" content (viewers forwarding to a partner/friend): **15–30%**
- Observed examples from couple-app research (Apr 2026):
  - `@hearttalksle` 7582109919596252430 → 99.3K / 421.1K = **23.6%**
  - `@abjyy` 7470942080618040594 → 100.9K / 369.8K = **27.3%**
  - `@ri.hira` 7248163338956393734 → 54.5K / 307.2K = **17.7%**

High share rate is the FYP amplifier — the algorithm reads "people send this to other people" as a strong distribution signal. A 100K-view video with 20% share rate is a better template to copy than a 1M-view video with 2% share rate.

When reporting, compute share/like per video and flag the outliers. Recommend `share/like ≥ 5%` as the minimum success bar for app-growth content experiments — this bar means the creative is actually doing distribution work, not just getting shown.

Per-video TikTok DOM selectors for likes/comments/shares (as of Apr 2026):
```javascript
document.querySelector('[data-e2e="like-count"], [data-e2e="browse-like-count"]').innerText
document.querySelector('[data-e2e="comment-count"], [data-e2e="browse-comment-count"]').innerText
document.querySelector('[data-e2e="share-count"], [data-e2e="browse-share-count"]').innerText
// caption
document.querySelector('[data-e2e="browse-video-desc"], [data-e2e="video-desc"]').innerText
// hashtags
Array.from(document.querySelectorAll('a[href*="/tag/"]')).map(a => a.innerText)
```

## Verification Step
After ranking, hit the top 10 URLs with a HEAD/GET to confirm 200 OK. TikTok occasionally takes down or privates videos; dead links in the final table are worse than fewer results.
