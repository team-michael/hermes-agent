# api-service 4xx alarm: /track-event & /set-user-properties 401 (invalid/expired token)

## Distinguishing signature

Not every `[api-service] 4xx error response is greater than 300 in 5m` alarm is the
`/authenticate` "Missing required fields" noise pattern (see
`api-service-4xx-authenticate-noise.md` / `notifly-api-auth-failure-case-2026-06-16.md`).
A second, materially different pattern exists:

- Dominant status: **401** (not 400)
- Dominant paths: `POST /track-event`, `POST /set-user-properties`
- `userAgent`: `undici` or `node` (server-side SDK/integration client, not a browser)
- Source IP is usually dominated by one origin, but **can legitimately be a fleet of
  several distinct origin IPs** all sharing the same invalid/expired token (behind
  Cloudflare, so `ip` field shows `<origin>, <cf-edge-ip>`)
- Single `projectId` — this pattern is almost always scoped to one customer project,
  unlike the `/authenticate` noise pattern which is often scope-unknown.

**Pitfall — do not require a single dominant IP to confirm this pattern.** Confirmed
case 2026-07-02 (`regather` project): after de-fragmenting Cloudflare edge IPs (see
below), the top origin IP accounted for only ~69% of the hour's 401s
(5,293 of ~7,680), with 9 other distinct origin IPs each contributing 75–580 hits, all
`userAgent: node`. This is a customer's server fleet (multiple app instances) all
presenting the same now-invalid token — not a single misbehaving script. Treat
"single `projectId` + `node`/`undici` userAgent + no single successful auth" as the
confirming signature; a merely-dominant-but-not-exclusive top IP does not disqualify
the classification.

## Root cause (code-level)

`verifyToken(token)` returns falsy and the handler returns 401 with body
`{"error":"Invalid Authorization Token"}` (or `"No token provided"` if the header is
missing entirely):

- `services/server/api-service/lib/api/track-event.js:18-42`
- `services/server/api-service/lib/api/set-user-properties.js:~90-105`

This means the client is presenting a token that no longer validates — expired,
revoked, rotated on the Notifly side without the client updating, or a client bug
sending a stale/malformed token. It is a client-credential problem, not a service
defect, but it causes real data loss (dropped track-event / user-property calls) for
that customer project if the client keeps retrying without success.

## Fast triage technique: is this NEW or BASELINE?

Alarm history alone (`alarm_count_7d/30d`) tells you the *alarm* recurred, but not
whether *this specific project's* 401 volume is new. Run a bounded Logs Insights
query scoped to the detected `projectId` across the prior 24h in 1h buckets:

```
fields @timestamp, status
| filter projectId = "<project_id>" and status = 401 and (path = "/track-event" or path = "/set-user-properties")
| stats count() as cnt by bin(1h) as bucket
| sort bucket asc
```

**Always alias `bin(...)` with `as bucket` (or similar) and refer to that alias in
`sort` — repeating the bare `bin(1h)` call in a later clause raises
`MalformedQueryException`. See `logs-insights-bin-datefloor-malformed.md` for the
full explanation. Confirmed working end-to-end on 2026-07-02 with this aliased form
for a `regather` project 24h/7d baseline check (24h hourly buckets: 7273/5/7390/5648;
7d daily buckets showed 0 on all prior days and 20,491 on the alarm day only,
confirming fresh same-day onset).

If every bucket before the alarm hour is empty/zero and the alarm hour alone shows a
large count, this is a fresh onset for that project, not routine noise — even if the
alarm *name* has fired on a stable ~2/day cadence for 30 days (that cadence is driven
by other projects/paths sharing the same coarse metric filter).

## Identifying the dominant client behind the spike

```
fields @timestamp, ip, userAgent, path, status, projectId
| filter status = 401 and (path = "/track-event" or path = "/set-user-properties")
| stats count() as cnt by ip, userAgent, projectId
| sort cnt desc
| limit 10
```

A single IP + single userAgent + single projectId dominating the results (e.g. >90%
of the window) confirms one integration retry-storming against one project's
now-invalid token, rather than diffuse traffic.

**Pitfall — Cloudflare edge IP fragments the "single origin IP" signal when grouping
by the raw `ip` field.** The logged `ip` value is `"<origin_ip>, <cf_edge_ip>"`, and
the edge IP varies per request (different PoP/connection). `stats count() by ip,
userAgent` therefore splits one real client into many rows — e.g. a single origin
`43.200.115.9` client appeared as 8 separate rows (2191, 2006, 1559, 1525, 934, 858,
570, 432) purely because of edge-IP variation, none of which individually looked like
90%+ dominance. Before concluding "no single client dominates," extract/group by the
substring before the comma (the origin IP) instead of the full field:

```
fields @timestamp, ip, userAgent, projectId
| filter status = 401 and path = "/track-event" and projectId = "<project_id>"
| parse @message '"ip":"*,*"' as originIp, edgeIp
| stats count() as cnt by originIp, userAgent
| sort cnt desc
| limit 10
```

If Logs Insights `parse` on the raw ip field is awkward, summing the fragmented rows
by hand (grouping same origin IP prefix) is an acceptable manual substitute — just
don't stop at "the top row is only 20%" and declare diffuse traffic without doing
that rollup first.

## Classification guidance

- `needs_fix` when: prior-24h baseline for that project/path/status combo was ~0,
  the current-window count is large and escalating across consecutive 5-min
  datapoints (e.g. 382 → 1,763 → 1,827), and the client is clearly retrying without
  backoff (sustained real data loss for that customer).
- `no_action` when: the project has intermittent/sporadic 401s at low volume with no
  escalation and no dominant single-client signature — likely a one-off expired
  session token that will self-resolve.

## Pitfall — check for repeat storms within the same day before calling it a one-off

A single alarm evaluation only proves the storm crossed threshold once. Before
concluding "self-resolving, no_action", run a 15-minute-bucket count over the
preceding several hours (not just the alarm's own 5-min window):

```
fields @timestamp, status, projectId, ip, userAgent
| filter status = 401 and path = "/track-event"
| stats count() as cnt by bin(15m) as bucket
| sort bucket asc
```

If the same project/IP/userAgent tuple shows **two or more separate spike-and-recover
cycles** in the same day (e.g. a burst at 05:30–05:45 UTC that fell back to baseline,
then a second unrelated-looking burst at 07:30–07:45 UTC that tripped the actual
alarm), the client is retrying persistently across a multi-hour window, not failing
once and quietly giving up. This is stronger evidence for `needs_fix` than a single
spike alone, even if each individual burst "recovered" on its own — the underlying
invalid-token condition was never fixed between bursts, only the retry pressure
fluctuated. Confirm dominance with the `stats count() by projectId, ip, userAgent`
query from above scoped to each burst window; the same tuple reappearing in both
windows confirms one unresolved client, not two unrelated incidents.

## Same-day repeat-alarm escalation tracking

This alarm can fire multiple separate times in one day for the *same* ongoing
incident (same `project_id`, same 401/`track-event` signature) as the retry
storm continues. Before re-deriving root cause from scratch on a repeat
firing, check whether this reference already documents a "Confirmed case"
for today's date — if so, this is very likely a continuation, not a new
incident.

When it is a continuation, compare against the last recorded numbers to judge
trend, not just re-confirm "fresh onset, needs_fix" mechanically:

- 2026-07-02 first documented check (~07:xx UTC alarm): 24h hourly buckets
  7273/5/7390/5648, ~10 distinct origin IPs, cumulative ~20,491 for the day at
  that point.
- 2026-07-02 second check (11:11 UTC alarm, same incident, same project
  `b57754a9497a545ab9b0e4aadd6f53b6`): hourly buckets extended to
  7273/5/7390/7792/7631/19761/9255 (05:00-11:00 UTC), cumulative 59,183 for
  the day — nearly 3x growth since the first check, with a fresh escalation
  spike to 19,761/hr in the most recent full hour. Origin IP count grew from
  ~10 to 14 distinct origins, still led by `43.200.115.9` (`undici`, ~72% of a
  2h sample).

**Classification guidance for repeats**: a second (or later) same-day
`needs_fix` confirmation for an incident that is still escalating and has
already run 6+ hours with cumulative failed requests in the tens of
thousands (real, uncorrected customer data loss) is a signal that `needs_fix`
alone may not be getting timely engineering action. On the 2nd+ repeat of the
*same* incident within one day, if the trend is still climbing (not
flattening/recovering) and there is no evidence the project owner has been
contacted yet, prefer escalating to `urgent` with `@engineers` rather than
issuing another quiet `needs_fix` — a single unresolved credential/token
issue causing tens of thousands of dropped events over half a day for one
customer is exactly the "repeated customer impact / real failed work"
condition the `urgent` tier exists for, even though no individual 5-minute
alarm evaluation looks catastrophic on its own.

- 2026-07-02 third check (~12:11-12:45 UTC alarm, same incident, same
  project `b57754a9497a545ab9b0e4aadd6f53b6`): 5-min metric datapoints
  peaked at 2340/2215/467 right at the ALARM transition, then the alarm
  flipped back to `OK` by 12:45 UTC as the 5-min rate dropped below
  threshold (18/41). Cumulative day-total kept climbing to 90,644 (up from
  59,183 at the second check), with ~68K attributable to the same origin
  `43.200.115.9` (`undici`). **This check was mis-classified as `no_action`**
  solely because the discrete CloudWatch alarm had already transitioned back
  to `OK` — the day-level trend (still climbing, same unresolved token, same
  customer) was not weighed against that single recovered 5-min window
  before finalizing.

**Pitfall — do not equate "alarm state is currently OK" with "issue
resolved."** This alarm's 5-minute `Sum > 100` threshold is noisy relative to
the underlying incident: the retry-storm client does not send at a constant
rate, so the metric naturally dips below threshold between bursts even while
the customer's token is still invalid and events are still being dropped.
Before defaulting to `no_action` because `describe-alarms` shows `OK`,
re-run the same-day cumulative/baseline comparison this reference already
describes (7d daily counts, dominant-origin-IP breakdown). If the day-total
for the known project/path/status signature is still far above the ~700-820/day
baseline and still growing versus the last documented check above, classify
per the escalation-tracking guidance (repeat `needs_fix` or `urgent`), not
`no_action`, regardless of the alarm's momentary state.

- 2026-07-02 fourth check (13:11 UTC alarm, same incident, same project
  `b57754a9497a545ab9b0e4aadd6f53b6`): hourly total-4xx sums 10:00-12:00 UTC
  were 20,069/22,670/18,862 (up from the ~7-9K/hr range seen at earlier
  checks), cumulative day-total (all `api-service` 4xx, dominated by this
  incident) reached 101,803 by 13:15 UTC. Incident has now run 8+ consecutive
  hours (onset ~05:00 UTC) with no sign of flattening. Classified `urgent`
  with `@engineers` escalation on this checkpoint — this is the correct
  application of the escalation-tracking guidance above: 4th same-day
  confirmation, still climbing, tens of thousands of dropped events for one
  paying customer, no evidence of contact/fix yet.

- 2026-07-02 fifth check (13:11-13:45 UTC ALARM->OK transition, same incident,
  same project `b57754a9497a545ab9b0e4aadd6f53b6`): 5-min datapoints for this
  cycle were 461/2587/2291 at the ALARM transition then dropped to 982/40/15/30
  by 13:44 UTC, and the alarm auto-recovered to `OK` at 13:50 UTC. This is the
  same retry-storm client (`43.200.115.9`, `undici`, `/track-event` 401)
  continuing to cycle above/below the 5-min `Sum>100` threshold — consistent
  with the "alarm OK != issue resolved" pitfall above. Treat this as a
  recovery *notification* for the incident already escalated `urgent` at the
  13:11 UTC checkpoint, not a new independent event. If this is the only new
  information (no fresh escalating trend beyond what was already reported),
  a short acknowledgment referencing the already-escalated urgent incident is
  sufficient rather than a full fresh 5-field re-analysis.

- 2026-07-02 sixth check (14:11 UTC alarm, same incident, same project
  `b57754a9497a545ab9b0e4aadd6f53b6`): day-total `api-service` 4xx logs reached
  119,347 by 14:11 UTC (up from 101,803 at the 13:15 UTC checkpoint), with the
  breaching datapoints again in the thousands (471/2051/2266 across the three
  5-min evaluation windows). This is the 8th `OK->ALARM` transition of the day
  for this alarm (vs. a ~2/day 30-day baseline), and the incident has now run
  9+ consecutive hours since ~05:00 UTC onset with no flattening. Classified as
  a continuation of the already-escalated `urgent` incident (first escalated at
  the 13:11 UTC / fourth checkpoint) rather than a fresh independent event —
  per the escalation-tracking guidance below, kept `urgent` with `@engineers`
  because the trend is still climbing and there is no evidence of a fix/contact
  yet, not because the discrete 5-min alarm looked catastrophic on its own.

- 2026-07-02 seventh check (14:11 UTC alarm -> OK by 15:05 UTC, same incident,
  same project `b57754a9497a545ab9b0e4aadd6f53b6`): breaching datapoints
  471/2051/2266 (max 4541 seen in the 7d window scan), alarm auto-recovered
  to OK at 15:05 UTC with 2 consecutive sub-threshold datapoints (24.0/15.0).
  This is the 9th `alarm_count_1d`/10th `alarm_count_7d`-style transition
  reported by the helper for today (`alarm_count_1d: 10`, `daily_alarm_counts
  2026-07-02: 8` OK->ALARM transitions vs ~2/day 30-day baseline). Dominant
  signature remains unchanged: `POST /track-event` 401,
  `projectId=b57754a9497a545ab9b0e4aadd6f53b6` (regather), origin IP
  `43.200.115.9` (undici), 0-1ms duration (fails at token-validation, no DB
  hit). Treated as a continuation of the already-escalated `urgent` incident
  (first escalated at the 13:11 UTC / fourth checkpoint) — reuse root
  cause/scope framing, report only the delta and current alarm state
  (recovered vs still climbing) rather than re-deriving from scratch.

- 2026-07-02 eighth check (17:11 UTC alarm, same incident, same project
  `b57754a9497a545ab9b0e4aadd6f53b6`): breaching datapoints 294/1573/1482
  (3 of 4, 5-min Sum), 7d metric scan max=4604 (new peak, up from 4541 at the
  seventh check), current alarm-window top signature is `/track-event` 401
  (170 of ~300 sampled lines, ~57%) vs `/authenticate` 400 noise (129, ~43%) —
  first checkpoint today where the two signatures are close in volume rather
  than `/track-event` clearly dominating, but `/track-event`/401/regather is
  still the larger and the only project-attributable one. `daily_alarm_counts
  2026-07-02: 10` (up from 8), `alarm_count_1d: 11`. Incident has now run
  12+ hours since ~05:00 UTC onset with a clear dip-then-respike pattern
  (17.0/16.0 at 16:44-16:51 UTC then straight back to 1534/1937 at 16:58-17:05
  UTC) — consistent with the established "alarm OK != resolved" pattern, not
  a new incident. Treated as a continuation of the already-escalated `urgent`
  incident; kept `urgent` because the metric hit a new 7d peak and the
  dip-respike cadence shows no sign of the client backing off.

**Reusable pattern confirmed across 6 checkpoints today**: for a still-open,
already-escalated incident, do the full helper run each time (cheap, one-pass),
but skip re-deriving the root cause from scratch — check whether this
reference already has a "Confirmed case" entry for today's date and same
`project_id`, then report only the delta (day-total growth, whether the trend
is still climbing vs. flattening) and reuse the existing `원인`/`범위` framing.
Only write a fresh full 5-field analysis when the project_id, path, or error
signature differs from what's already documented for the day.

- 2026-07-02 ninth check (21:25-21:45 UTC alarm window, same incident, same
  project `b57754a9497a545ab9b0e4aadd6f53b6`): hourly `ConsoleErrors` Sum
  dipped to 103 at 19:00 UTC (near-baseline quiet spell) then respiked to
  5808 (20:00 UTC) and 14902 (21:00 UTC) — same dip-then-respike cadence as
  every prior checkpoint. Breaching datapoints this cycle were 2096/2183
  (21:30-21:35 UTC) dropping to 16/4 by 21:45 UTC, and the alarm auto-recovered
  to `OK`. Sampled log signature unchanged: 1988/2000 (~99%) `POST
  /track-event` 401 `"Invalid Authorization Token"`, `userAgent: undici`,
  dominant origin IP `43.200.115.9` behind Cloudflare edge nodes. This is the
  16+ hour mark since ~05:00 UTC onset with no durable resolution — each
  "OK" is a threshold dip, not a fix. Treat as continuation of the
  already-escalated incident; do not downgrade to `no_action` on an
  auto-recovered datapoint alone when the hourly trend the same day shows a
  fresh respike higher than the prior lull.

- 2026-07-02 tenth check (23:11 UTC alarm, same incident, same project
  `b57754a9497a545ab9b0e4aadd6f53b6`): breaching datapoints 550/2322/2531,
  dominant signature still `/track-event` 401 (5,774 of ~5,900 sampled 4xx
  lines, ~98%), same origin IP `43.200.115.9` (undici). Hourly bucket count
  dipped to 5 at 22:00 UTC (brief lull) then respiked to 5,873+ by 23:00-23:12
  UTC. 18+ hours since ~05:00 UTC onset, still unresolved. Kept `urgent`,
  continuation of already-escalated incident — do not re-derive root cause.

- 2026-07-02 eleventh check (23:11 UTC alarm, same incident, same project
  `b57754a9497a545ab9b0e4aadd6f53b6`): breaching datapoints 550/2322/2531
  (22:56-23:11 UTC), day-total `api-service` 4xx logs reached 223,657 for
  2026-07-02 (up from 119,347 at the sixth checkpoint), with 24,576 already
  logged into 2026-07-03 within minutes of midnight UTC — confirms the
  incident has crossed the day boundary with no resolution. Alarm dropped to
  9.0/27.0 (well under threshold) and auto-recovered to `OK` by ~23:56 UTC.
  Sampled current-alarm-window signature was ~100% `/track-event` 401 (300 of
  300 sampled lines). A neighboring log line in the same stream carried
  `Campaign ID: 8MnfdL` but that line was an unrelated SSE/push-scheduling
  event, not the 401 trigger itself — do not attach that campaign ID to this
  incident's scope. Treated as continuation of the already-escalated `urgent`
  incident (originally escalated at the 13:11 UTC / fourth checkpoint);
  reused root cause/scope framing and reported only the delta per the
  established reusable pattern.

- 2026-07-03 twelfth check (01:51 UTC alarm, same incident, same project
  `b57754a9497a545ab9b0e4aadd6f53b6`): breaching datapoints 452/2066/2004
  (01:36-01:46 UTC). 2026-07-02 day-total closed at 223,657 (up from 119,347
  at the sixth checkpoint) — incident ran the entire rest of the day without
  resolution. 2026-07-03 already logged 30,754 hits within the first ~1h51m
  past midnight, confirming zero backoff/recovery across the day boundary.
  `daily_alarm_counts`: 2026-07-02=12 transitions (final), 2026-07-03=1 so far.
  `rapid_recurrence.status: normal` (160 min since previous alarm) — consistent
  with the established dip-then-respike cadence, not a new pattern. Sampled
  current-window signature 299/300 (~99.7%) `/track-event` 401. This is now
  20+ hours since ~05:00 UTC onset on 2026-07-02 with no evidence of
  contact/fix. Continuation of the already-escalated `urgent` incident
  (first escalated at the 13:11 UTC / fourth checkpoint on 2026-07-02); kept
  `urgent`, reported only the delta per the established reusable pattern.

- 2026-07-03 최근 10분 확인 (01:5x-02:0x UTC, 동일 인시던트, 동일 프로젝트
  `b57754a9497a545ab9b0e4aadd6f53b6`): 최근 10분 `ConsoleErrors` 5분 datapoint
  452/2066/2004/2029 — 계속 임계값(100) 초과, 회복 신호 없음. 400건 샘플 중
  397건(99.25%)이 여전히 `/track-event` 401, origin IP 여전히 `43.200.115.9`
  (undici) 지배적(333/400, ~83%), 나머지 origin 9개 분산. 동일 시그니처
  지속 확인, 새로운 패턴 없음.

## Action items

- Check DynamoDB `project` table for the affected `project_id`'s `cognito_api_auth` /
  token config; confirm whether it was rotated recently.
- Contact the project owner to verify their SDK/integration is using a current token.
- Improvement candidate (not urgent by itself): `track-event.js` / `set-user-properties.js`
  401 responses have no `Retry-After` or distinct error code, so misbehaving clients
  have no signal to back off — worth flagging as a hardening item, not a blocking fix.
