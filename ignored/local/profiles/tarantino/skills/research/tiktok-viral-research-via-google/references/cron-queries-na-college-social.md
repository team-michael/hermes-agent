# Cron Queries — NA College Social Apps

Query list used by cron job `0d2144c61a4c` ("NA 대학생 Social App TikTok 바이럴 일일 보고서"), registered 2026-05-06, schedule `0 23 * * *` UTC = KST 08:00 daily.

Ordered by priority — the top of the list must be covered before Google `/sorry/` hits around query 12-14. Highest-value competitor intel and core ICP framing go first; speculative/adjacent niches ride the tail and get sacrificed gracefully when captcha lands.

## Query list (hl=ko, tbs=qdr:w, num=30)

1. `site:tiktok.com/@ "college social app"`
2. `site:tiktok.com/@ "campus app" college`
3. `site:tiktok.com/@ "Fizz app"`
4. `site:tiktok.com/@ "Sidechat"`
5. `site:tiktok.com/@ "Yik Yak"`
6. `site:tiktok.com/@ "Saturn app college"`
7. `site:tiktok.com/@ "Locket Widget" college`
8. `site:tiktok.com/@ "BondBeyond"`
9. `site:tiktok.com/@ "SumOne app"`
10. `site:tiktok.com/@ "Widgetable"`
11. `site:tiktok.com/@ "roommate finder app"`
12. `site:tiktok.com/@ "dorm life app"`
13. `site:tiktok.com/@ "college freshman app"`
14. `site:tiktok.com/@ "find friends college app"`
15. `site:tiktok.com/@ "anonymous college app"`
16. `site:tiktok.com/@ "lapse social app"`
17. `site:tiktok.com/@ "NGL app college"`
18. `site:tiktok.com/@ "BeReal college"`

## Why this ordering

- **1-2**: generic ICP framing — always useful, cheap to evaluate.
- **3-10**: direct competitor intel. These are the handles/formats we want to copy or counter-position against. Must survive captcha tail.
- **11-15**: user-intent queries (roommate finder, freshman, dorm life, find friends, anonymous) — these return the "what are students actually searching for" signal, complementary to competitor-brand queries.
- **16-18**: known polluted clusters (per SKILL.md pitfalls — Lapse/NGL/BeReal). Kept because occasionally a clean NA-college result slips through, but these are the first to die to `/sorry/` with minimal loss.

## Expected pollution

Known hits that should be filtered by `NOISE_HANDLES` / `NOISE_SNIPPET`:
- Lapse cluster → construction timelapse, study timelapse
- NGL cluster → non-college NGL usage (middle/high school, international)
- BeReal → 2026-era nostalgia/decline content (reverse ICP signal)
- Saturn → Samsung lock-screen widget tutorial accounts (@carterpcs, @sstech00, @ahmedmaherr11)
- Admissions/essay coaching accounts on college-keyword queries

Blocklist baseline (add to these as new noise appears):
```
NOISE_HANDLES = {'marymarketingirlie', 'locketgold6.0pro', 'johnleggottcollege',
                 'techrosen', 'jisuinparis', 'cymru', 'mediamarkt_hb_weserpark',
                 'somnia.plus', 'vibrantcollegeadvising', 'experthan',
                 'collegexpert', 'essayhelpbyhollee', 'misterjensen', 'saraharberson',
                 'carterpcs', 'sstech00', 'ahmedmaherr11'}

NOISE_SNIPPET  = ['cortis', 'vietnam', 'việt nam', 'bahau', 'indonesia',
                  'bighit', 'pt hanam', 'jewellers', 'admissions',
                  'essay coach', 'sat prep']
```

## Historical baseline (first run, 2026-05-05)

- raw: 110 → cleaned: 20 → icp_final: 9
- Coverage: 13/18 queries completed, 5 queries lost to `/sorry/`
- Top insight that day: `@roannecblo_`, 6-day-old video, s/l 8.3% (views 2,200 / likes 36 / shares 3)
- Dominant pollution: Lapse cluster (construction timelapse) + NGL cluster (international locket-style spam)

## Run log (2026-05-07, headless)

- raw: 165 → cleaned (age≤8, !noise): 112 → ICP qualified: 91 → engagement-scraped: 15
- Coverage: **18/18 completed, zero `/sorry/` captcha**. Headless Chrome + venv interpreter behaved well.
- TikTok direct engagement scrape: 15/15 successful, zero TikTok captcha either. Warmed profile cookies clearly still valid.
- Top s/l: `@marisavasquezz` 36.47% (USC brand-roast, 4d old, 49K views / 10.7K likes / 3.9K shares).
- Dominant format cluster: **brand-roast** (7 videos, 2 of them s/l ≥ 5%). Secondary: dorm-moveout (5 videos, seasonal — finals/move-out week).
- Competitor organic silence: **Fizz=0, Sidechat=0, Yik Yak=1** ICP-qualified mentions in past week. Market is quiet.
- Format repetition winner: `@lucy.erisman × 2` (dorm-hack). Only repeating creator in 91-video pool — weak factory signal, worth re-checking next run.

Drift-detection heuristic: if raw count drops below ~100 or cleaned below ~50 with the same 18-query list, something structural changed (Google filter tightening, ICP keyword drift, or TikTok indexing slowdown). Today's run was well above those floors.

Use this as the baseline to compare against future runs — if a future day drops to raw <60 with same query list, something structural changed (Google filter tightening, ICP keyword drift).

## Interpreter (verified 2026-05-07)

```bash
DISPLAY=:1 /home/ubuntu/.hermes/venvs/clix-growth/bin/python <scrape_script>.py
```

Do NOT use bare `python3.12` — selenium isn't in any system site-packages on this host. See SKILL.md Pitfalls section.
