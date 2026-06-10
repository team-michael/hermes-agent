# Ad-Hoc Niche Concept Research (non-cron)

When the user asks "what concepts go viral / are trending in the <X> niche on TikTok"
as a one-off (NOT the NA-college daily cron), use this leaner playbook. Verified
2026-06-09 on the **bestie / best-friend** niche: 16/16 queries clean, 202 unique
videos, 111 with hard view counts, zero `/sorry/`.

## 1. Free the profile if the daily cron parked a zombie driver

The NA-college cron parks its driver in `time.sleep(86400)` on block (VNC handoff
policy). If it was never solved overnight, a stale `dom_verify.py` / `scrape_google_loop.py`
Python parent + ~11 Chrome procs are STILL holding the Tarantino `SingletonLock`.
You cannot run a second scrape against the same profile — they deadlock on the lock.

The next cron tick would reap it anyway, so reaping it now to run an ad-hoc scrape is
safe. Recovery sequence (same as the in-skill "stale parked driver" pattern):

```bash
# 1. find the parked python parent + its bash wrapper
ps -eo pid,etime,args | grep -E 'scrape_google|dom_verify|clix-growth/bin/python' | grep -v grep
kill -9 <python_pid> <bash_wrapper_pid>; sleep 1
# 2. enumerate-then-kill (NEVER broad `pkill -9 -f chrome` — can self-kill the agent shell)
for pid in $(ps -eo pid,args | grep -E 'chrome.*--user-data-dir=/home/ubuntu/.hermes/profiles/tarantino/Tarantino|chrome_crashpad|chromedriver-linux64/chromedriver' | grep -v grep | awk '{print $1}'); do kill -9 $pid 2>/dev/null; done
sleep 3
# 3. sweep stale singletons
rm -f /home/ubuntu/.hermes/profiles/tarantino/Tarantino/Singleton{Lock,Cookie,Socket}
# 4. verify clean: expect 0
ps -eo pid,args | grep -E 'chrome|chromedriver' | grep -v grep | wc -l
```

## 2. all-time (no `qdr`) vs `qdr:w` — pick by question shape

This is the key query-design fork the cron path obscures (cron always uses `qdr:w`):

- **"What concepts WORK / go viral in niche X"** → **all-time** (`&num=30&hl=ko`, NO `tbs=qdr`).
  Surfaces the megahit format archetypes (e.g. The Rock 180M `#bestfriend check`,
  Kylie/Stassie 50M "rich best friend check"). These define the replicable format
  families even if the specific video is years old.
- **"What's TRENDING NOW"** → add `&tbs=qdr:w` (and post-filter `age_days <= 8`).
  Collapses absolute views (top all-time 1-10M → top-week 10-500K) but shows live
  format machines.
- **Best of both:** run all-time once, then in analysis post-filter `age_days <= 120`
  to separate "current fresh viral" from "old megahit archetype." Report both bands —
  old megahits are often non-replicable celebrity legacy; the recent band is what to copy.

## 3. Standalone ad-hoc scraper

Copy `scripts/scrape_google_loop.py`, set `OUT_DIR=.../cron_tiktok_<niche>`, replace
`QUERIES` with niche-specific phrases, and **change `URL_TMPL` to drop `tbs=qdr:w`**
for all-time concept research:

```python
URL_TMPL = "https://www.google.com/search?q={q}&num=30&hl=ko"   # all-time
```

Launch with `background=true, notify_on_complete=true`:

```bash
cd <OUT_DIR> && DISPLAY=:1 /home/ubuntu/.hermes/venvs/clix-growth/bin/python scrape_<niche>.py > scrape.out 2>&1
```

For pure concept research you usually only need the Google SERP pass (view counts +
snippet text are enough to read the formats) — you can SKIP the TikTok DOM-verify
stage entirely, which sidesteps the Stage-2 rotation captcha and the VNC handoff.

## 4. Cluster by concept, not just rank by views

The deliverable the user wants is "what CONCEPTS are viral," so after dedupe+parse,
bucket each video into format clusters by keyword-matching the snippet (lowercased):
e.g. "check", "test"/"quiz", "pov", "how we met"/"since", "app"/"widget",
"platonic soulmate", "tag", "reveal", "long distance". Report each cluster with
`(video_count, sum_views, top_video)` so the user sees which FORMAT FAMILY dominates,
then break out the recent (`<=120d`) band and the app/product-specific videos
separately. Close with a default-bet vs risk-bet vs low-cost-spread recommendation.

Query-design note: wrap short/ambiguous phrases to stay on-niche, but for a niche
that is itself the keyword (bestie/best friend) the bare phrase is fine. Quote exact
phrases (`"best friend test"`) to lock the format, and mix generic format names with
identity-signal phrases ("things only best friends do", "platonic soulmate").
Watch for dead clusters — e.g. `"long distance best friend"` returned near-zero
views in the bestie run; drop it from the report rather than pad.
