# Ad-Hoc Niche Concept Research (non-cron)

When the user asks "what concepts go viral / are trending in the <X> niche on TikTok"
as a one-off (NOT the NA-college daily cron), use this leaner playbook. Verified
2026-06-09 on the **bestie / best-friend** niche: 16/16 queries clean, 202 unique
videos, 111 with hard view counts, zero `/sorry/`. Re-verified 2026-06-11 on the
**date** niche: blocked at Q13/18, but 12 queries → 157 unique videos / 96 with views
was MORE than enough to ship the report.

## 0. Partial harvest is a shippable harvest

If Google blocks mid-run, do NOT retry or wait for the parked driver. Check
`google_results.json` first: ~10+ clean queries / ~100+ unique videos / ~60+ with view
counts ⇒ kill the parked driver (it parks in `time.sleep` for VNC handoff), sweep
singletons, and write the report from the partial data. Name the un-collected queries
and their clusters as "under-sampled" in the report instead of padding. Order QUERIES
so the highest-value clusters run FIRST — the tail is what you lose on a block.


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

**Use the ready templates** (added 2026-06-11; don't hunt for old copies in `work/`):

- `templates/scrape_adhoc_niche.py` — copy to `work/<niche>/scrape_<niche>.py`,
  edit `OUT_DIR` + `QUERIES` + (optionally) `URL_TMPL`.
- `templates/parse_rank_concepts.py` — copy alongside, edit `IN`/`OUT` + `CONCEPTS`.
  Handles Korean SERP view parsing, `likes*12` view-proxy, age from
  `video_id >> 32`, per-concept rollup, and the `<=120d` recent band.

All-time concept research drops `tbs=qdr:w`:

```python
URL_TMPL = "https://www.google.com/search?q={q}&num=30&hl=ko"   # all-time
```

**Order QUERIES priority-first** — highest-value clusters at the top. Google can
`/sorry/`-block mid-run (date-niche run 2026-06-11: blocked at Q13/18; bestie run:
16/16 clean) and you keep only what ran before the block. Design so the first
~10-12 queries alone make a shippable report.

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

## 5. Report shape that landed (date-niche run, 2026-06-11)

What got the report accepted with zero corrections: lead with "which cluster is the
LIVE machine now" (recency share, not raw views), then per-cluster **vibe + WHY it
spreads (psych trigger) + real URLs** — never a dry format taxonomy (per jace's
standing 분석 preference). Explicitly split **legacy megahits** (8mo+ old, reference
archetypes, often non-replicable celebrity/pet outliers) from the **≤120d replicable
band** ("지금 돌아가는 머신") and say which one is the copy target. Close with default
bet / risk bet / next step. A `slack-table` rollup (cluster × count × sum views ×
recent count × top URL) carried the evidence cleanly.

## 5. Mid-run `/sorry/` block — partial-ship decision (ad-hoc policy)

The scraper's "park on block" behavior exists for the cron VNC-handoff flow. For
**ad-hoc** runs, do NOT solve the captcha and do NOT retry (user policy: no retry
hammering on 403/captcha). Instead:

1. Check yield: `jq '[.[].items[].url] | unique | length' google_results.json` and
   per-query counts. **>=10 queries collected and >=100 unique videos → kill the
   parked process and ship the partial report.** (Date run: 12/18 queries, 157
   unique, 96 with views — fully shippable.)
2. Kill cleanly: `kill -9 <python_pid>`, then enumerate-kill Tarantino-profile
   chrome + chromedriver pids (never broad `pkill -f chrome`), then
   `rm -f .../Tarantino/Singleton{Lock,Cookie,Socket}`.
3. In the report, NAME the uncollected queries and which concept clusters are
   under-sampled because of them, and offer a follow-up scrape after cooldown.
   Don't silently present partial coverage as complete.

Note: `process(action='kill')` may fail with `No module named 'psutil'` — fall back
to plain `kill -9` of the recorded pids (scrape.out / google_status.json carry
`driver_pid`; the bash wrapper pid is the background session's).

## 6. Report shape that landed well (date-niche run, 2026-06-11)

Per user's standing "분석" preference: vibe/감정 + WHY it spreads (psych trigger)
+ real URLs — not a format taxonomy. The structure that worked:

- Lead: which cluster is the **live machine** (highest recent<=120d share), not
  just highest absolute views.
- Native Slack table for the cluster rollup (concept / n / sum views / recent
  count / top video).
- Per-cluster: one-line psych trigger ("배심원 심리", "wholesome envy",
  "파트너 태그 머신" — save/tag mechanics differ from watch mechanics) + 2-4
  actual video links with views + age.
- Explicit legacy-vs-replicable split: old megahits (often celebrity/pet
  outliers, e.g. a 37M cat video topping "date with me") are archetypes, NOT
  copy targets; the <=120d band is the copy target.
- Close: default bet / save-machine bet / offer to map onto a specific app ICP.
