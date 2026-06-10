# Single-Account Drill-Down (analyze ONE @handle, not a topic)

When the task is "analyze this account / why does it get views / what hashtags work" for a **specific @handle**, the topic-discovery Google loop is the WRONG tool. Use this cleaner, faster path (verified 2026-06-09 on `@maheshowbout`, all via `curl`/`urllib` — no Selenium, no Google needed). Ready-to-run: `scripts/analyze_tiktok_account.py <handle>`.

## The four calls

1. **TikTok profile JSON via curl** — bio, region, follower/heart/video counts. Highest-signal single call.
   ```bash
   curl -fsS -A "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15" \
     "https://www.tiktok.com/@HANDLE" -o profile.html
   # SSR blob: <script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">...</script>
   ```
   Parse: `data["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]` →
   - `["user"]`: `uniqueId, nickname, signature` (BIO = self-positioning, often the whole story), `region, language, verified, privateAccount, bioLink`
   - `["statsV2"]`: `followerCount, heart/heartCount, videoCount, friendCount`
   - **`["itemList"]` is EMPTY for anonymous SSR** — get the video list from step 2, not here.
   - Diagnostic: `heartCount / videoCount` = avg likes/post. Low-follower + high-video-count + low-avg-likes + a few breakout posts = **single-concept content machine** (mini app-marketing account), not an influencer. Views come from search/FYP, not followers.

2. **DDG HTML site-search for captions + hashtags + likes** (the metric leak):
   ```bash
   curl -fsS -A "<desktop UA>" "https://html.duckduckgo.com/html/?q=site%3Atiktok.com%2F%40HANDLE" -o ddg.html
   ```
   Each `result__snippet` block leaks `NN.NK Likes, NN Comments`, the full caption (inline `#hashtags` + original-sound name), and the real URL (uddg-encoded, both `/video/` AND `/photo/`). Parse:
   ```python
   blocks = re.findall(r'result__snippet"\s+href="//duckduckgo\.com/l/\?uddg=([^"&]+)[^>]*>(.*?)</a>', raw, re.S)
   # urllib.parse.unquote the url; html.unescape + strip tags from snippet
   # likes: r'([\d.,]+)([KMm]?)\s*Likes' ; hashtags: re.findall(r'#(\w+)', snip)
   ```
   This CONTRADICTS the 2026-05-07 `serp-fallback-matrix.md` claim that DDG "does not work" for `site:tiktok.com`. It does, and richly — see that file's appended 2026-06-09 correction.

3. **oEmbed for per-post caption** (clean public endpoint, no auth):
   `https://www.tiktok.com/oembed?url=<encoded post url>` → JSON `title` = full caption. Returns **400 for `/photo/` slideshow posts** (only `/video/` works); fall back to the DDG snippet caption for photo posts.

4. **Post date from the TikTok ID** (no network): top 32 bits of the 64-bit numeric ID = unix seconds.
   ```python
   datetime.datetime.utcfromtimestamp(int(tid) >> 32)  # -> post date
   ```

## When you need ALL posts + VIEW counts (not just DDG's handful) — headful grid scroll

The 4 curl calls above are fast but limited: DDG only surfaces the ~5-15 posts it has indexed, and it leaks **likes**, not **views**. For a full-account analysis ("scan all 465 posts, rank by views, find every breakout") you must scroll the profile grid in **headful Chrome** (TikTok renders the grid for anonymous sessions even though in-app *search* is captcha-walled). Verified 2026-06-09 on `@maheshowbout` → got all 465 posts with view-count overlays + captions.

Procedure (full script pattern lived at `~/.hermes/tmp/cron_tiktok_mahes/profile_scan.py` that session):
1. `create_driver(width=1440, height=900)` — **screen-fitting size so a VNC captcha is fully visible** (do NOT use a tall window like 2200px; it pushes the slider puzzle off-screen and you can't hand it off cleanly).
2. `driver.get("https://www.tiktok.com/@HANDLE")`, sleep 6.
3. **Captcha → VNC-solve-then-continue** (do NOT auto-bypass — see SKILL.md §"VNC-Assisted" and user no-hammer rule). Poll `has_captcha()` (`document.querySelector('#captcha-verify-container-main-page, #captcha_slide_button')`) until the human solves the slider in noVNC:6080; then reload + continue. Screenshot the parked window for handoff with `DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority ffmpeg -y -f x11grab -video_size 1920x1080 -i :1 -frames:v 1 shot.png` (host has `xwd`+`ffmpeg`, NOT scrot/import/maim).
4. Scroll-to-bottom loop: `window.scrollTo(0, document.body.scrollHeight)`, sleep ~2.2s, count `a[href*="/video/"], a[href*="/photo/"]`; stop after count stagnates 4 iterations (≈32 scrolls loaded 465 posts).
5. Extract per card: `{type, id, url}` from the anchor, **views** from `card.querySelector('[data-e2e="video-views"], strong').innerText` (e.g. `"478.4K"` → parse K/M/B), **caption** from `a img[alt]`.
6. Decode dates from IDs (step 4 above), then rank by views and analyze hashtags by **median** views (min-5-uses) to split reach-tags from conversion-tags.

Expect a power-law: on `@maheshowbout` top-1 post = 14.6% of all views, top-10 = 52%, and **61% of posts were sub-2K flops**. The model is "post daily, most die, 1-2/month are home runs" — so the real levers are trending **sound** (chart songs >> no-name original sounds: the 478K hit rode Travis Scott), a curiosity **caption hook** ("i was shocked", not "this is your sign to..."), and **volume**. Cleanup after: enumerate-kill Chrome tied to the Tarantino profile + sweep `Singleton{Lock,Cookie,Socket}` (NEVER broad `pkill -9 -f chrome` — it can kill the agent's own bash wrapper and unrelated headless browser-tool Chromes under `/tmp/agent-browser-*`).

## Why view attribution = keyword CLUSTERS + caption intent, NOT bare hashtags

Breakout posts repeat a *funnel* of tags — a big identity/reach tag (`#girlhood`), a relatable pain-point tag (`#busywoman`), and a narrow solution/intent keyword (`#sharedcalendar`). Big tag = reach, pain tag = resonance, solution tag = conversion intent. The real hook is usually a **problem-statement / search-intent caption** ("how to ___", "when your friend says ___") that TikTok search matches to queries — not the hashtags alone. Also check **format**: photo-carousel "tips" slideshows often out-perform video in save-driven niches (cheap, high dwell, save-bait). On `@maheshowbout` the two top posts were both photo carousels (46.4K + 17.8K likes = 22.8% of all-time hearts from a 351-follower account).

## DDG is a THIN SAMPLE -- escalate to grid scan for full-population analysis

The four `curl` calls above are fast and block-resistant, but DDG site-search only
indexes a FRACTION of an account's posts. Verified 2026-06-09: `@maheshowbout` has
**465** posts; the clean DDG call surfaced only **~5**. That sample is enough to read
positioning + top hashtags + a couple of breakouts — NOT enough to rank hashtags by
performance, find winning sounds, or see the view distribution.

For the WHOLE account (real per-post VIEW counts, not just DDG likes), use the headful-Chrome
grid scroll: **`scripts/profile_full_scan.py`** (full recipe + the VNC-solve-then-continue
captcha pattern, screen-fitting-window pitfall, and ffmpeg x11grab handoff screenshot all live
in `references/single-account-profile-analysis.md` — don't duplicate them here).

## Analysis depth: how to attribute views once you have the full grid (verified 2026-06-09)

The canonical reference says "separate the three drivers". Here is the concrete METHOD to do it
on `profile_items.json` (the analysis snippet at the bottom of `scripts/profile_full_scan.py`
runs these):

1. **Rank hashtags by MEDIAN views, not appearance count or mean.** Mean is wrecked by one
   478K outlier. Median (min ~5 uses) separates real drivers from base tags. On `@maheshowbout`
   this exposed the funnel: drama tags (`#breakup`/`#ex`/`#cheating`) had modest medians but the
   HIGHEST maxes (116K) = "variability bombs" you sprinkle for occasional blowups; the identity
   tag (`#girlhood`, on 368/465 posts) is a low-median but ubiquitous reach BASE, not a driver alone.
2. **Sound is usually the #1 lever.** Breakouts rode CHART/trending sounds (Travis Scott, Taylor
   Swift, Zara Larsson); no-name `original sound` posts mostly flopped. Extract sound from the
   caption tail `created by <nick> with <SOUND>$` and rank by median views.
3. **Caption hook beats hashtags for the click.** Winners open with a curiosity/emotion one-liner
   ("i was shocked", "should i laugh or cry"), NOT a description ("this is your sign to get a
   shared calendar" sat at median). Problem-statement / search-intent captions get matched by search.
4. **Report the power-law honestly.** Compute top-1 / top-10 share of total views and the "% flops
   under 2K". `@maheshowbout`: top-10 = 52% of all views, 61% of posts under 2K. The lesson is
   "daily-mass-post + monthly-homerun, views = volume x luck (raised by sound/hook/tag choices)",
   not "every post pops".
5. **Brand/intent tag often outs the true product.** `#howbout` (147 uses) outed the account as
   marketing for the **Howbout** shared-calendar app — a near-zero-follower account posting one
   concept daily for 8 months with a few breakouts = single-concept content MACHINE (the clean
   reference for an app-growth content motion), not an influencer.

## No-hammer rule on blocks (user standing directive)

If Google `/sorry/` AND DDG `anomaly` page both fire in one session (common after a topic scrape used up the good-standing window — DDG throws an `anomaly` page with NO `result__snippet` when hit too fast / too many times), STOP. Do not loop retries. Report the specific block, note the IP cools in hours, and ship the partial analysis you already have. Profile-JSON + one clean DDG call is usually enough for an account drill-down even when everything else is blocked. The script makes exactly ONE DDG call and returns `[]` on anomaly rather than retrying.
