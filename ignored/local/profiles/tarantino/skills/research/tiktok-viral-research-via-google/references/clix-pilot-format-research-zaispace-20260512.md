# Clix Pilot Format-Research — Zaispace (2026-05-12)

Anchor case for the "Clix Pilot Format-Research Workflow" section of the
parent skill. Preserved so the next pilot research can compare methodology
+ realized share/like benchmarks.

## Customer context
- App: Zaispace (Zaisland Inc.) — iOS-only, Stanford StartX Spring 2026, social app built around AI-generated shared experiences ("Zai" avatars do Hangouts with other people's Zais, stories pipe into DMs).
- Pilot KPI: **Top 12 uploaded videos average ≥ 1,000 views** during pilot window. Platform: TikTok primary, Reels possible. Accounts: Clix chooses.
- Existing Yeti weekly report: `https://just-went-viral.com/r/zaispace/2026-W19/`. Category framing per Yeti: "rewarding raw vulnerability about friendship difficulty." Six format clusters: Adult Friendship How-To, Friendship Struggle Confession, Community FOMO Showcase, Storytime, Friendship Blocker Listicle, Introvert College Survival Guide.

## Pipeline executed (stages per parent skill's Clix workflow section)

1. Read Yeti W19 report → extracted 6 format clusters + 5 proposed experiments P1-P5. Used as emotional baseline hypotheses, NOT as the final answer.
2. Designed 18 queries in 5 semantic-family clusters: friendship_pain, storytime, ai_social_cat (Character.AI / Replika / AI companion), anxiety_wedge, avatar_customization, direct_brand.
3. Ran Google SERP loop (`hl=ko`, `qdr:m`, `num=30`, jittered 2/3/4 sleeps). **13/18 clean, Q14 `"rate my avatar"` `/sorry/` blocked** — predicted by skill's pitfalls section. Tail loss = avatar_customization cluster.
4. Parsed + deduped + cluster-tagged → 112 unique videos, 90 with view signal.
5. Took top 10 by SERP-leaked views, DOM-verified all 10 with zero TikTok captcha (warm Tarantino profile).
6. Computed share/like and save/like ratios, re-ranked.
7. Deep-read top 5 share/like winners' snippets to label actual hook structure.
8. Mapped each winning format to Zaispace app mechanics (alcohol→Hangout, reveal→Switch-to-Reality toggle, etc.).

## Final DOM-verified Top 10 (ranked by share/like DESC)

| # | s/l% | save% | views | likes | shares | age | handle | title |
|---|---:|---:|---:|---:|---:|---:|---|---|
| 1 | 44.7 | 31.3 | 32K | 2,104 | 940 | 26d | @helpmeharlan | Lonely College Plan: Choosing Your Path |
| 2 | 16.3 | 3.9 | 36K | 6,113 | 995 | 7d | @thelilytran | Cherish Your College Friend Group Memories |
| 3 | 3.5 | 8.9 | 406K | 50,300 | 1,750 | 12d | @jabberssuckingdihzanka | Character.AI review (negative) |
| 4 | 2.6 | 7.0 | 163K | 26,100 | 676 | 24d | @orangeejulius | Social Anxiety ruined a date, then an app fixed it! |
| 5 | 2.4 | 20.1 | 33K | 1,647 | 39 | 23d | @sabrina.zohar | Anxious Texting: A Life-Changing Dating Tip |
| 6 | 2.1 | 28.3 | 428K | 24,500 | 526 | 13d | @better.social.skills | 4 Reasons You Might Struggle to Make Friends |
| 7 | 1.7 | 43.2 | 88K | 8,127 | 135 | 9d | @thejennamillion | Replying to @val: this is how I made friends as adult |
| 8 | 1.4 | 5.7 | 109K | 20,800 | 284 | 26d | @remythelegend | college is lonely |
| 9 | 1.0 | 4.2 | 110K | 14,600 | 140 | 11d | @emilys.mind | Senior Year Loneliness: It's Okay If You Feel Alone |
| 10 | 0.3 | 3.0 | 107K | 5,777 | 16 | 5d | @ashatvs | How I Make Friends in Cape Town |

## Insights the data revealed (and where it contradicted Yeti)

**Yeti said**: pure emotional confession wins. P1 experiment was literally "Friendship Struggle Confession → Zai reveal."

**DOM-verified data shows**: emotional confession is a click magnet (100K+ views at @emilys.mind and @remythelegend) but a share-poor s/l ~1%. The actual share/like winners are:
- **Plan/framework format** (@helpmeharlan 44.7% s/l, @thelilytran 16.3% s/l) — a structural solution wrapped around the emotional pain
- **Before-after app reveal** (@orangeejulius 2.6% s/l at 163K views) — single strongest positioning template, hook: "Social Anxiety ruined X, then an app fixed it"
- **"Replying to @"** format (@thejennamillion save 43.2%, @ashatvs save 28%) — dominates SAVE rate (the app-interest signal). Also generates 1→N compound content: one seed video's comments spawn 3-5 reply videos.

**Yeti had no per-video share/like data, which is why it overweighted view-count winners.** The skill's "share/like > raw views" rule made the corrective reading obvious.

## Adjacent opportunity discovered

`@jabberssuckingdihzanka` video (406K, 50K likes, s/l 3.5%) is a Character.AI negative review. The AI-companion-app user base is frustrated — this is a cross-sell audience for any app positioned as "AI connects real people instead of replacing them." Zaispace's on-site copy ("AI fundamentally reshape the way people express themselves and form meaningful bonds with one another — NOT with AI") fits this audience directly. Adjacent format proposed: "AI Companion dissatisfaction → Zai alternative," worded indirectly to avoid named-competitor suppression.

## Format recommendations shipped

| Format | Reference | Expected avg | Expected KPI |
|---|---|---|---|
| α Lonely-Plan (framework-shaped confession) | helpmeharlan 44.7% s/l | 2-5K views | save rate ≥ 15% |
| β Anxiety-Fixed (before-after reveal) | orangeejulius 2.6% s/l | 2-8K (hit: 30K+) | share rate ≥ 5% |
| γ Replying-to (derivative from α/β seeds) | thejennamillion save 43% | 1-3K | save rate ≥ 20% |
| δ AI-Companion dissatisfaction pivot | jabberssuckingdihzanka 3.5% s/l | hit-or-miss | comment volume |
| ε Numbered listicle | better.social.skills save 28% | 800-2K | save rate |

Volume plan: 22 videos over 14 days across 3 accounts, distributed 6/6/4/3/3. Math check: if α/γ deliver steady 1.5-3K baseline and β produces one hit in the 20K+ range, Top 12 average lands comfortably above 1K.

## Coverage gaps / methodology warnings shipped to customer

- Q14 `/sorry/`-blocked → avatar_customization cluster uncaptured. Known next-day tail-recovery path.
- Reels not included this session — separate pipeline run needed for Reels engagement numbers (no SERP share-leak path yet).
- Raw JSONs kept at `/home/ubuntu/.hermes/profiles/tarantino/work/zai/scrape/` for reruns.

## What worked (keep for next pilot)

- Semantic-family clustering (5 clusters × 3-4 queries each = 18) gave solid cluster_count tagging even though cross-query overlap was 1 (same diagnostic issue as prior NA-college runs — narrow ICPs produce disjoint query-matches; centrality signal is weak)
- Yeti report as hypothesis baseline + DOM data as reality check was the right integration shape. Always name the Yeti→DOM divergence in the deliverable.
- Top-10 DOM verify was enough to build format proposals; did not need top-25 or multi-cluster pool for this deliverable

## What to fix next time

- Run a second cluster specifically for "plan/framework" shaped videos (`"college plan"`, `"how to" guide` variants) once we know that format beats pure confession — currently we got @helpmeharlan somewhat accidentally via the friendship_pain cluster.
- Add Reels parallel pass (Instagram SERP site-search + DOM) so KPI coverage matches the customer's "TikTok + possibly Reels" scope.
- For Zaispace specifically, queue a follow-up run on the `avatar_customization` cluster — next-day tail recovery after the Q14 block, not in the same session.
