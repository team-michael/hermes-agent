# SERP Fallback Matrix

Full test log from 2026-05-07 when this Hermes host (`43.200.138.23`) got IP-flagged by Google. Exhaustive probe of alternative search engines as `site:tiktok.com "<keyword>"` sources.

## Test setup
- Host: `43.200.138.23` (AWS-hosted Hermes instance)
- Browser: headful Chrome via `hermes_chrome.create_driver()` on `DISPLAY=:1`
- User profile: both `Tarantino` persistent profile and fresh ephemeral profiles tested
- Probe query (small, typical): `site:tiktok.com "Fizz app" college` or `site:tiktok.com "Fizz app"`

## Results by engine

### Google (`google.com/search`)
- **Status: HARD BLOCKED**
- First query `q=tiktok` → immediate redirect to `/sorry/index?continue=...`
- Body: *"Our systems have detected unusual traffic from your computer network. This page checks to see if it's really you sending the requests, and not a robot."*
- Confirmed on three attempts spanning ~8 minutes including one fresh profile + 3-minute cooldown
- Raw cURL (no Selenium) to `/search` returns HTTP 200 but body contains zero result anchors — the raw HTML is a redirect page, not actual results
- **This is distinct from the per-session `/sorry/` after 14 queries** documented elsewhere — here even query #1 is blocked, which indicates IP reputation penalty rather than session rate limit

### Ecosia (`ecosia.org/search`)
- **Status: WORKING (preferred fallback)**
- 42 queries run sequentially, **0 skips**, 66 unique TikTok URLs extracted
- No captcha, no rate limit observed in the test window
- Caveats:
  - `site:tiktok.com/@ "x"` tokenizes poorly — drop the `/@` anchor, use `site:tiktok.com "x"` and filter post-hoc in regex
  - First call without prior homepage visit → intercepted by cookie-consent modal (ecosia.org shows this before first search). Workaround: `driver.get("https://www.ecosia.org/")` + `time.sleep(2)` to prime
  - Recency parameter doesn't work — results are all-time, average age in observed run was 500+ days
  - No rich result snippets (no "조회수" / "views" substring in card text). Must DOM-verify every URL on TikTok directly
  - Sparser per-query (1-10 items typical). Compensate by 2× query-count budget
- Recommended result-card selector: `a.closest('article, div.result, div.mainline-result, section')`

### DuckDuckGo HTML (`html.duckduckgo.com/html/`)
- **Status: DOES NOT WORK** for site-restricted searches
- No captcha, page loads cleanly
- Body: *"No results found for site:tiktok.com/@ \"Fizz app\""*
- DDG's site: operator either doesn't index TikTok video pages or silently ignores the directive
- Tried `site:tiktok.com "Fizz app" college` (without `/@`) — same "No results found"

### Brave Search (`search.brave.com/search`)
- **Status: BLOCKED**
- Body: *"Confirm you're a human being. This will only take a few seconds. I'm not a robot. Switch to traditional captcha. Learn more about Proof of Work Captcha."*
- First two queries slipped through briefly before the PoW captcha activated. Not reliable for any sustained scrape from this host

### Bing (`bing.com/search`)
- **Status: BLOCKED**
- Body: *"Skip to content. Accessibility Feedback. Rewards. Mobile. One last step. Please solve the challenge below to continue."*
- Same wall on every variant query tested

### Mojeek (`mojeek.com/search`)
- **Status: 403 FORBIDDEN**
- Body: *"Sorry your network appears to be sending automated queries so we can't process your search at this time."*
- Hard block at the HTTP level — not a captcha, no path forward without IP change

### Yandex (`yandex.com/search`)
- **Status: BLOCKED**
- Body: *"Please confirm that you and not a robot are sending requests. SmartCaptcha by Yandex Cloud."*
- Offers Yandex Search API v2 for automated use — not wired up, would need API key

### Startpage (`startpage.com/do/search`)
- **Status: BLOCKED**
- Body: *"CAPTCHA Verification. To continue using Startpage, please enter in the characters you see below."*
- Classic text captcha, no automated path

## Summary decision tree

1. Try Google first with a **canary query** (e.g. `q=tiktok`). If `/sorry/` on that → do NOT iterate through the real query list, skip to Ecosia.
2. Ecosia is the only working fallback from this host. Plan for:
   - 2× query-count budget (each query returns fewer items)
   - No recency filter → results are historical, not past-week
   - Mandatory DOM verification on TikTok for every URL (no snippet metrics)
3. Flag the degraded coverage explicitly in the final report: "Google hard-blocked, Ecosia historical-only."
4. Out-of-band remediation (not runnable from a cron): VNC session to warm Google cookies, or IP/profile rotation to shed the reputation penalty.

## Pitfalls discovered during testing

- Do NOT chain-iterate through all engines looking for a winner. Each blocked engine burns 2-4 seconds and adds no value once one of them works. The matrix above IS the cached test — start with Ecosia directly if Google canary fails.
- `html.duckduckgo.com` specifically: the silent "No results" is easy to mistake for "too specific a query". Confirmed by testing both with and without the `/@` anchor — the problem is DDG's handling of `site:tiktok.com`, not the query.
- Selenium detection matters less than IP reputation. A pristine fresh profile hits the same `/sorry/` on Google as the Tarantino profile. That points the cause at the IP, not at webdriver fingerprinting.
