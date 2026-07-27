# api-service 4xx Authenticate Noise

Recurring false-positive pattern for the `[api-service] 4xx error response is greater than 300 in 5m` CloudWatch alarm.

## Alarm metadata

- **Alarm name**: `[api-service] 4xx error response is greater than 300 in 5m`  
- **Namespace**: `ConsoleErrors`  
- **Metric name**: `/aws/ecs/notifly-services-prod/api-service 4xx error`  
- **Statistic**: `Sum`  
- **Period**: 300s
- **Threshold**: 100
- **EvaluationPeriods**: 4 (DatapointsToAlarm: 3)
- **Note on name drift**: The alarm name says "greater than 300" but the actual CloudWatch threshold is **100**. Do not rely on the numeric value embedded in the alarm name when estimating severity margin.
- **State transition history**: ~50–57 OK→ALARM transitions in 30 days, typically 2 transitions per day resolving within 1–5 minutes. Some days produce back-to-back transitions within 5 minutes when a high-volume 5-minute bucket continues contributing to the rolling evaluation after a brief OK recovery. Always derive from actual `describe-alarm-history` output using `HistoryData | fromjson | .oldState.stateValue` / `.newState.stateValue` rather than the `StateValue` field, which can be `null` for older entries.

## Pitfall — metric filter discovery via namespace/name may return empty

The `api-service` log group has metric filters that do not necessarily surface when querying by `metricNamespace` + `metricName` alone. When `aws logs describe-metric-filters --region ap-northeast-2 --query 'metricFilters[?metricNamespace==\`ConsoleErrors\`]'` returns empty, fall back to the log-group-scoped query:

```bash
aws logs describe-metric-filters --region ap-northeast-2 \
  --log-group-name /aws/ecs/notifly-services-prod/api-service \
  --output json | jq -c '.metricFilters[] | {metricTransformations:.metricTransformations, filterPattern}'
```

Note: the AWS CLI nests `metricName` and `metricNamespace` under `.metricTransformations[0]`, not at the top level. Querying `.metricName` directly returns `null` even when the filter exists.

**Pitfall — `describe-metric-filters` rejects combined parameters**: passing both `--log-group-name` and `--metric-name`/`--metric-namespace` to `aws logs describe-metric-filters` (or both kwargs to boto3) raises `InvalidParameterException: Describe Metric Filters request must contain either logGroupName or metricName and metricNamespace`. Use exactly one of:
- `--log-group-name <name>` (then filter client-side), or
- `--metric-name <name> --metric-namespace <namespace>` (then filter by log group client-side).

## Metric filter

```json
{
  "filterPattern": "{ $.message = \"error-response\" && $.status >= 400 }",
  "logGroupName": "/aws/ecs/notifly-services-prod/api-service"
}
```

The filter increments on every structured log where `message` is exactly `error-response` and `status` is ≥ 400.  
**Important**: the underlying `api-service` code emits these lines at `WARN` level (`"level":"warn"`) for handled validation/business rejections. The alarm metric does not distinguish `warn` from `error`.

## Dominant trigger pattern

A daily burst of requests hits `POST /authenticate` around **02:11 KST (17:11 UTC)**:

- **User-Agent**: primarily `Apache-HttpClient/5.3.1 (Java/17.0.19)`; also `python-requests/2.32.3`, `ReactorNetty/1.1.13`, `axios/1.13.6`, `node`
- **Status**: `400`
- **Response body**: `{"error":"Missing required fields"}` (or `{"data":null}` for access-key-bearing requests that still fail validation)
- **IP origin**: various Korean IPs behind Cloudflare
- **Volume**: typically 500–1,900 events in a 10-minute window, enough to breach `Sum > 100` across 3 consecutive 5-minute periods.
- **Recurrence**: daily including weekends; timing is tight (±2 minutes).

The projectId for these lines is `"unknown"`; there is no campaign or user-journey scope.

## Secondary (non-authenticate) 4xx

A small minority (~20–30 per alarm window) are real business rejections scoped to actual projects:

- `DELETE /projects/{pid}/messages/text-message/blockservice/recipients/removes` → `"Unregistered recipientNo."` (NHN Cloud block-service rejection)
- `POST /projects/{pid}/campaigns/{cid}/send` → `"INVALID_RECIPIENTS"` / `"MISSING_PHONE_NUMBER"` (client-provided malformed recipient)
- `POST /projects/{pid}/campaigns/{cid}/send` → `"Bad request: campaign <id> does not exist"` (client retry burst against deleted/non-existent campaign; see Variant B below)
- `GET /user-state/{pid}/{uid}` → `"projectId ... does not exist"` (invalid/stale project ID from mobile SDK)
- `POST /track-event` → `401` (`"Invalid Authorization Token"`)

These are handled service responses, not unhandled exceptions or data-loss events.

## Variant B — Campaign send non-existent campaign burst

On some days the dominant signature shifts from `/authenticate` to repeated `POST /projects/{pid}/campaigns/{cid}/send` returning `400` with body `"Bad request: campaign <id> does not exist"`.

Characteristics:
- **Source**: a single client IP (e.g. `54.180.113.161`) behind Cloudflare
- **User-Agent**: often `Apache-HttpClient/5.5 (Java/21.0.11)` or similar Java HTTP client
- **Volume**: 500–900 requests in a 30-minute window from one IP to one campaign ID
- **Level**: `warn` (handled validation rejection)
- **Project scope**: tied to a real project (e.g. `lookpin`) and a specific campaign ID (e.g. `uAApo3`); the campaign does not exist in `campaigns_<project_id>` table
- **Recurrence**: first-seen within 7 days for the specific campaign; the broader alarm still has the 30-day baseline because other 4xx patterns fire on different days

This is a client-side retry or misconfiguration, not a service regression. The `api-service` is correctly rejecting the request. Cross-check `AWS/ApplicationELB` or `AWS/ApiGateway` 5xx metrics to confirm no server-side failure is present.

## Variant C — User journey batch-enter validation rejection (`POST /projects/{pid}/user-journeys/{journeyId}/enter`)

On some alarm windows the current-trigger-context sample (not the 7d/30d top signature) is dominated by repeated `400` responses on `POST /projects/{pid}/user-journeys/{journeyId}/enter`, even while the historical top signature for the alarm is still `/authenticate`. Treat the *current window's* dominant repeated line as the actual trigger for that specific ALARM transition; do not assume `/authenticate` fired every time just because it's the historical baseline.

Characteristics:
- **Response**: `{"code":400,"success":false,...}`, `level: "warn"`, `duration: 11–16ms` (fast — no DB round trip, rejected in early input validation before `getUserJourney()` is called)
- **Code path**: `services/server/api-service/lib/api/user-journeys.js` → `enterUserJourney(token, projectId, userJourneyId, body)`. The relevant early-return validation branches (lines ~30-59) are, in order:
  - `!projectId` → `400 Invalid project ID`
  - `!userJourneyId` → `400 Invalid user journey ID`
  - `!body?.users` → `` 400 `users` field is required` ``
  - `body.users.length > maxUsers` → `` 400 Maximum of ${maxUsers} users can be entered at once `` (default cap 1000; project `031b18009978590188e49e6777447fc2` / munice has an extended cap of 3000 via `EXTENDED_MAX_ENTER_USERS_PROJECT_ID`)
  - A ~15ms duration with no DB call rules out `getUserJourney()` returning null (`404 User journey not found`, which is a different code path/status) — it's one of the four cheap pre-DB checks above, most likely the batch-size cap given repeated identical calls from the same caller.
- **Scope**: fully attributable — `projectId` and `userJourneyId` (e.g. `user-journeys/ab711m/enter`) both appear directly in the structured log line, so this is not a "campaign/user journey unknown" case.
- **Classification**: `no_action` — handled input-validation rejection from a caller sending oversized/malformed batches to the user-journey enter API; server behavior is correct and no data loss occurs (caller can retry with a valid batch).

## Variant D — Single-project `/track-event` 401 `Invalid Authorization Token` (client token expiry, hourly recurrence)

Distinct from the daily ~17:11 UTC `/authenticate` burst. First confirmed 2026-07-02 with **4 discrete alarm firings at hourly cadence** (05:51, 07:51, 08:51, 09:51 UTC) instead of the usual ~2/day baseline — a **frequency deviation is itself a classification signal**, not just the signature.

**Update — same incident, later same-day session (2026-07-02, project `regather` / `b57754a9497a545ab9b0e4aadd6f53b6`)**: a follow-up triage on the same alarm/day found this was not 4 isolated spikes but a **continuous escalating flood spanning ~6 hours (05:00–11:40 UTC)**, with hourly `ConsoleErrors` sums climbing 7,603 → 7,865 → 8,138 → 7,946 → 20,069 → 22,647, then dropping to near-zero within one minute at 11:40 UTC (clean client-side stop, not a gradual recovery). Use `get_metric_statistics` with `Period=3600` over the full day (not just the alarm datapoint window) to see whether an "hourly recurrence" alarm is actually one continuous incident that just keeps re-tripping the same alarm as it evaluates — the per-alarm-firing view understates the real duration/severity.

Characteristics:
- **Dominant trigger**: `POST /track-event` returning `401` with body `{"data":null,"error":"Invalid Authorization Token"}`
- **Code path**: `services/server/api-service/lib/api/track-event.js:31-42` — `verifyToken(token)` returns falsy; not a service bug, the token itself is invalid/expired/revoked. **Pitfall — do not cite `lib/api/v1/auth.js`**: a plain string search for `"Invalid Authorization Token"` also matches `lib/api/v1/auth.js`'s `unauthenticatedError()`, but that file backs the versioned `/v1/**` route auth middleware, which `/track-event` (a legacy unversioned route) does not use. When multiple files match an error-string search, confirm which one is actually on the invoked route's code path (check the route registration, e.g. `lib/app.js` / `lib/api/track-event.js` itself) before citing a file in the final answer.
- **Scope**: overwhelmingly (~99%, 990-997 of 1000-event samples across all 4 windows) a **single project** — confirm via `projectId` field, which IS populated here (unlike `/authenticate` which logs `"unknown"`).
- **User-Agent**: `undici` and `node` dominate (server-side SDK/backend client, not browser) — consistent with one customer's backend integration retrying with a stale credential in a loop.
- **Volume per window**: 1000+ (paginator cap) `Invalid Authorization Token` hits inside each 15-minute alarm datapoint window — this is a tight retry loop, not sporadic failed calls.

Bounded verification command (anchor to exact `StateReasonData.startDate`/datapoint window in epoch ms, not Slack message time):
```python
resp = logs.filter_log_events(
    logGroupName='/aws/ecs/notifly-services-prod/api-service',
    startTime=<epoch_ms_window_start>, endTime=<epoch_ms_window_end>,
    filterPattern='"Invalid Authorization Token"',
    limit=1000
)
# then Counter() over json.loads(e['message'])['projectId'] to confirm single-project dominance
```

**Classification**: `needs_fix`, not `no_action` — even though the server-side behavior is correct (properly rejecting a bad token), this differs from the daily-baseline `/authenticate` noise in two ways: (1) recurrence is hourly and worsening vs. the ~2/day baseline, and (2) it is fully attributable to one paying customer's integration silently failing to send events for an extended period (real customer-side data loss risk, not just alarm noise). Action item is customer-facing (ask the project owner to check their SDK token/API key rotation), not a code or Terraform change — do not force a generic "optimize" action item when the fix is external.

**Second update — same day, later recurrence (2026-07-02, ~15:36–15:51 UTC)**: after the 05:00–11:40 UTC flood described above dropped to near-zero, the *same* alarm fired again hours later for the *same* project (`regather` / `b57754a9497a545ab9b0e4aadd6f53b6`) with the identical `POST /track-event` 401 `Invalid Authorization Token` signature (3-of-4 datapoints: 1698/1823/423 over 15:36–15:51 UTC). Combined with the earlier flood, `regather` triggered this alarm **9 times in one calendar day** (2026-07-02) vs. the ~2/day baseline — confirming this is not a single self-resolving incident but an intermittent, recurring failure across many hours. **Lesson**: when the current alarm-window trigger matches a documented single-project variant (Variant D), always pull the full-day `daily_alarm_counts` from the helper's `history` block (not just the current 5-minute datapoints) before deciding whether the incident already ended. A quiet period between bursts does not mean resolved — check for a later same-day recurrence before downgrading urgency. This reinforces `needs_fix` (customer-facing action: ask `regather` to check SDK token refresh/rotation logic) rather than `no_action` on the reasoning "it already recovered."

**Third update — multi-day continuous escalation (2026-07-02 21:00 UTC through 2026-07-03 17:11 UTC, still active at triage time)**: the `regather` (`b57754a9497a545ab9b0e4aadd6f53b6`) integration failure did not resolve after the second update. Hourly `POST /track-event` 401 counts for `regather` climbed into tens of thousands per hour overnight (23:00 UTC 07-02: 36,049/hr; 00:00 UTC 07-03: 24,310/hr; 03:00 UTC 07-03: 20,224/hr) before tapering to a lower but still nonzero steady state (300–2,500/hr) through at least 17:00 UTC on 07-03 — i.e. **the retry loop has been running essentially continuously for 20+ hours** rather than firing in discrete bursts. Total `/track-event` 401 volume for `regather` on 2026-07-02 alone was 214,925 (99.7% of all `/track-event` 401s that day), driving the alarm's 30-day daily-count baseline from ~2/day to **12 firings on 2026-07-02**. The same project also dominates `POST /set-user-properties` 401 (1,467 of ~2,174 total, 2026-07-02–03) — confirming the broken client is retrying with the same stale/invalid token across at least two endpoints (`/track-event`, `/set-user-properties`), not just one. At the 2026-07-03 17:11 UTC alarm firing (the trigger for this specific ticket), `/authenticate` 400 was still the largest single signature in the 5-minute window (1,422, 78%, known daily baseline noise) but `/track-event` 401 for `regather` (296, 16%) is the abnormal contributor riding on top of it. **Classification remains `needs_fix`**: this is no longer a self-resolving spike, it is a sustained ~24h continuous failure with real data loss for one paying customer (dropped `track-event` and `set-user-properties` calls), and the volume is large enough to be a material fraction of total `api-service` request load. Action item: reach out to `regather` about SDK token refresh/rotation, since this is a customer-side integration bug, not a service defect — `api-service` is correctly rejecting the invalid token every time.

**Fourth update — confirmed still ongoing at hour ~40+ (2026-07-03, later same-day session, alarm window 16:56–17:11 UTC)**: a separate later triage on the *same calendar alarm firing window* (16:56–17:06 UTC datapoints 332/1044/381) reconfirmed the exact same shape: `/authenticate` 400 = 1,429 (79% of 1,807 total `error-response ≥400` lines in the 15-minute window), `/track-event` 401 for `regather` = 296 of 307 total `/track-event` 401s (96% of that path, ~17% of the whole window) via `userAgent: undici`/`node`, plus a small `handys` (`80fd28969702573797f4d7f77063e47b`) `DELETE .../blockservice/recipients/removes` secondary (12). Full-day hourly trend for `regather` `/track-event` 401 on 2026-07-03 (`00:00→24288, 01:00→8524, 02:00→7112, 03:00→20193, 04:00→1416, 05:00→2493, 06:00→128, 07:00→946, 08:00→666, 09:00→1052, 10:00→1400, 11:00→1687, 12:00→1380, 13:00→1291, 14:00→1409, 15:00→1581, 16:00→878, 17:00→300`) shows the incident is still running at a lower non-zero steady state and has **not** self-resolved — confirms the "check the full day before downgrading" lesson from the second update still applies days later, not just hours later. **Takeaway for future sessions**: when the current alarm-window breakdown shows `/authenticate` in the ~75–85% range (lower than the historical 93–99% baseline) with `/track-event` 401 as the second-largest signature, immediately suspect a still-active Variant D `regather`-style single-project token-expiry incident riding on top of the daily noise, rather than treating the lower `/authenticate` share as itself anomalous — group by `projectId`+`userAgent` on the `/track-event` 401 slice to confirm before classifying.

**Fifth update — still ongoing at day 3 (2026-07-05, alarm window 16:56–17:11 UTC)**: `regather` (`b57754a9497a545ab9b0e4aadd6f53b6`) `/track-event` 401 continues at a non-zero steady state 3 days after first detection (2026-07-02). In the 24h preceding this alarm firing, hourly counts ranged ~236–3,981 (never reaching zero), confirming this is a durable ongoing customer-side integration failure, not a self-resolving spike — do not downgrade to `no_action` just because volume is lower than the original 20,000+/hr flood. `/authenticate` share in this window was back up to 84% (1,771/2,111), `/track-event` 401 for `regather` was 11% (239, of which 213 `undici` + 16 `node` = 229/239 ≈ 96% single-project). `undici`/`node` UA confirms server-side SDK, consistent with prior updates. Classification remains `needs_fix`: customer-facing action item is unchanged (ask `regather` to check SDK token refresh/rotation), and this should be tracked as an open ticket rather than re-investigated fresh each time the daily `/authenticate` alarm fires. Consider filing a dedicated internal ticket for the `regather` integration so this alarm's daily noise doesn't have to re-surface it.

## Variant E — isolated single-firing `/track-event` + `/set-user-properties` 401 (distinguish from Variant D flood)

Confirmed 2026-07-04 (project `arooo` / `597a8ca3385559f09b485058bdc1eabd`): a single ALARM→OK cycle (17:16→~17:16, back in OK within the same evaluation) where the current-window trigger was `POST /track-event` and `POST /set-user-properties` returning `401 "Invalid Authorization Token"` from one client IP/project, `level: warn` throughout. Daily count that day was only 2 (matches the ~2/day baseline), with a minor bump to 4 and 12 on the two preceding days — well short of Variant D's tens-of-thousands-per-hour, 20+ hour continuous flood.

**Do not auto-escalate every single-project `/track-event` 401 signature to `needs_fix` just because it matches Variant D's error string.** The distinguishing signal is volume/duration, not the signature alone:
- Isolated firing(s), daily count within/near the ~2/day baseline, no multi-hour hourly-climbing trend → `no_action` (same class as `/authenticate` noise: handled, correctly-rejected invalid token).
- Sustained hourly recurrence, daily count spiking to 5-10x+ baseline, and/or hours-long continuous non-zero volume for the same project → `needs_fix` per Variant D (customer-facing token-refresh follow-up).

Before classifying, always pull `history.daily_alarm_counts` for the last 3-7 days for the specific project in the current trigger — a lone spike day surrounded by baseline days is noise; a climbing multi-day trend is the Variant D incident pattern.

## Variant F — `POST /set-user-properties` 401 `Invalid Authorization Token`, single project, exponentially climbing (distinct from Variant D/E `/track-event`)

Confirmed 2026-07-09 (project `weatherstone` / `9156042e17c3560ab9c5717c75b1f5d6`). Same root string (`Invalid Authorization Token`) as Variant D/E but on `/set-user-properties` instead of `/track-event`, and with a materially different shape: the current-window signature was **dominant** (297/300 sampled lines, ~99%) rather than riding on top of `/authenticate` noise, and the metric datapoints were still climbing at alarm time (256 → 4,538 → 11,383 → 15,643 across consecutive 5-min buckets), not a single spike.

Code path: `services/server/api-service/lib/api/set-user-properties.js:101-108` — `verifyToken(token)` falsy → 401. Same auth-gate-only failure shape as Variant D (`duration: 0-1ms`, no DB call reached).

Full write-up, sizing method (how to tell "customer-side broken retry loop, needs_fix" apart from "capacity-threatening, urgent"), and classification decision tree: see `references/api-service-4xx-set-user-properties-invalid-token.md`.

Quick rule: apply the same Variant D/E volume-based test (isolated single firing near baseline → `no_action`; sustained multi-day 5x+ baseline elevation and/or still-climbing at alarm time → `needs_fix`; large enough fraction of total sampled requests to threaten other tenants, or multiple unrelated projects simultaneously → `urgent`), regardless of which specific endpoint (`/track-event`, `/set-user-properties`, or a future one) carries the 401.

## Fast classifier — `level` field

All known false-positive patterns for this alarm emit structured logs with `"level":"warn"`. A single Logs Insights query can separate handled rejection noise from real errors:

```
fields @timestamp, status, path, level, userAgent
| filter message == "error-response" and status >= 400
| stats count() as cnt by status, path, level, userAgent
| sort cnt desc
| limit 20
```

- If ≥ 90 % of the volume is `level: warn` → handled rejection noise → `no_action`
- If any non-trivial volume is `level: error` → unhandled exception path → investigate as real error

## Recurrence characteristics

| Window | `/authenticate` 400 count | Total 4xx count |
|---|---|---|
| Daily ~02:11 KST (17:11 UTC) | ~1,200–1,900 | ~1,250–1,950 |
| Off-window (other times) | ~1–15 | ~100–300 (other sources) |
| Daily total (metric Sum) | — | ~3,900–7,500 |

The daily **~02:11 KST** spike is a clockwork pattern with tight timing (±2 minutes). If the alarm fires outside this window, investigate the dominant signature immediately; it may be a different root cause.

## Helper gap — bracket-prefix fallback

The helper cannot parse alarm names that start with `[api-service]` because:
1. Its **text detector** breaks on the bracket prefix (brackets confuse word-boundary heuristics), returning `detected.alarm_name: null`.
2. Its internal `describe-alarms --alarm-names` call treats the leading `[` as JSON array syntax, so passing `--alarm-name '[api-service] ...'` also fails.

The helper does **not** expose `--alarm-name-prefix`; skip it entirely. The helper does **not** fail fast on bracket-prefixed names — it may **hang for 30+ seconds** (likely entering a slow fallback path such as listing all 7,000+ alarms) before timing out. Do not attempt the helper with `--alarm-name '[api-service] ...'`; go straight to direct boto3 or AWS CLI.

```bash
aws cloudwatch describe-alarms --region ap-northeast-2 \
  --query 'MetricAlarms[?contains(AlarmName, `api-service`) && contains(AlarmName, `4xx`)].{Name:AlarmName,Namespace:Namespace,MetricName:MetricName,Statistic:Statistic,Period:Period,Threshold:Threshold,ComparisonOperator:ComparisonOperator,StateValue:StateValue,StateReason:StateReason,StateReasonData:StateReasonData}' \
  --output json | jq '.[0]'
```

Alternative: Python `boto3` paginator + client-side substring filter (the SDK does not have the JSON-parsing quirk).

## Bounded trace commands

**Top signatures by status + path** (alarm window, UTC):
```bash
aws logs start-query --region ap-northeast-2 \
  --log-group-name '/aws/ecs/notifly-services-prod/api-service' \
  --start-time $(date -d 'YYYY-MM-DD HH:MM:SS UTC' +%s) \
  --end-time   $(date -d 'YYYY-MM-DD HH:MM:SS UTC' +%s) \
  --query-string 'fields @timestamp, status, path, method, level, message, userAgent
| filter message == "error-response" and status >= 400
| stats count() as cnt by status, path, method, level, userAgent
| sort cnt desc
| limit 20'
```

**Verify `error` level count** (should be 0 for the noise pattern):
```bash
aws logs start-query --region ap-northeast-2 \
  --log-group-name '/aws/ecs/notifly-services-prod/api-service' \
  --start-time $(date -d 'YYYY-MM-DD HH:MM:SS UTC' +%s) \
  --end-time   $(date -d 'YYYY-MM-DD HH:MM:SS UTC' +%s) \
  --query-string 'fields @timestamp
| filter message == "error-response" and status >= 400 and level == "error"
| stats count() as cnt'
```

Then: `aws logs get-query-results --region ap-northeast-2 --query-id <queryId>`

**Faster synchronous alternative — per-datapoint-window path breakdown without Logs Insights polling**: when you already have the alarm's `recentDatapoints` (from `StateReasonData`) and just need to confirm which 5-minute bucket the dominant signature shifted into (e.g., early buckets still mixed, later buckets flip to ≥90% `/authenticate`), `filter-log-events` + local `grep -oE` is faster than `start-query`/`get-query-results` round-trips because it returns synchronously with no polling:

```bash
for w in "<start_ms1> <end_ms1>" "<start_ms2> <end_ms2>" "<start_ms3> <end_ms3>"; do
  read s e <<< "$w"
  echo "== window $s-$e =="
  aws logs filter-log-events --region ap-northeast-2 \
    --log-group-name '/aws/ecs/notifly-services-prod/api-service' \
    --start-time $s --end-time $e \
    --filter-pattern '"error-response"' \
    --limit 1000 \
    --query 'events[].message' --output text | tr '\t' '\n' \
    | grep -oE '"normalizedPath":"[^"]*"' | sort | uniq -c | sort -rn | head -5
done
```

Align each window to one `recentDatapoints`/`evaluatedDatapoints` timestamp (5-min buckets) to see exactly when the dominant path flips — this caught a case where the two buckets before the breach were still mixed (`text-message`, `set-user-properties`, `campaigns/.../send`) and only the two breaching buckets were >90% `/authenticate`, which is expected and not itself a deviation worth a new dated entry.

## Consolidated verification (2026-05-16 through 2026-06-22, 40+ sessions)

**Do not add new daily entries unless the pattern materially deviates.** New entries should only be added when: new dominant signature, `level: error` present, peak volume outside 800–1,000/bucket, or time-of-day shift beyond ±5 minutes from 17:01 UTC.

This pattern has been confirmed on **30+ separate daily alarm windows** spanning 2026-05-16 through 2026-06-22 with consistent characteristics:

- `/authenticate` 400 accounts for 93–99% of all `error-response` logs in the alarm window
- `level: "warn"` on 100% of lines; explicit `level == "error"` query returns 0
- `projectId: "unknown"` on all `/authenticate` lines (validation occurs before project resolution)
- User-Agent rotates between `Apache-HttpClient/5.3.1 (Java/17.0.19)`, `python-requests/2.32.3`, `axios/1.13.6`, `node`, `ReactorNetty` — all are part of the same daily burst
- Metric datapoints consistently peak at ~850–900 in the 17:01 UTC 5-minute bucket
- 30-day OK→ALARM transition count stable at ~47–57 (1.6–1.9/day)
- Back-to-back transitions within 5–10 minutes are sliding-window evaluation artifacts from the 17:01 peak bucket still contributing after brief ALARM→OK recovery

**2026-06-22 alarm window** (latest confirmation):
- Metric datapoints: 180.0 (16:56), 897.0 (17:01), 656.0 (17:06); threshold 100.0, 3 of 4 required
- Top: 1,735 `POST /authenticate` 400 (98.2%), all `level: warn`, `projectId: "unknown"`
- UA: `Apache-HttpClient/5.3.1 (Java/17.0.19)` + `python-requests/2.32.3`
- Secondary: 17 `DELETE .../blockservice/recipients/removes` 400, 7 `POST /track-event` 401, 3 `POST /projects/b2b4a8f8.../campaigns/5Qnugu/send` 400, 3 `POST /projects/b2b4a8f8.../campaigns/icKePI/send` 400
- 30d/7d/1d/10m: 57/14/2/1

## Logs Insights daily trend query (full UTC day)

When the narrow 16:50–17:10 UTC window is already well understood, use this query to verify whether overall `/authenticate` 400 volume is drifting outside the daily baseline band:

```bash
aws logs start-query --region ap-northeast-2 \
  --log-group-name '/aws/ecs/notifly-services-prod/api-service' \
  --start-time $(date -d '14 days ago 00:00:00 UTC' +%s) \
  --end-time   $(date -d 'now 00:00:00 UTC' +%s) \
  --query-string 'fields @timestamp
| filter message == "error-response" and status >= 400 and path = "/authenticate"
| stats count() as cnt by datefloor(@timestamp, 1d) as day
| sort day desc
| limit 14'
```

Interpretation:
- Stable narrow band (~±25% day-to-day) → no trend shift; classify from the alarm-window signature only.
- Sudden jump to > 6,000/day for ≥ 2 consecutive days → investigate for a new client integration or retry loop.

## Pitfall — `INSUFFICIENT_DATA → ALARM` undercounts in transition history

This alarm uses `TreatMissingData: missing`. During low-traffic periods (midnight KST), the `ConsoleErrors` metric may have no data points, so the alarm state drops to `INSUFFICIENT_DATA`. The daily ~02:11 KST burst then transitions `INSUFFICIENT_DATA → ALARM`, not `OK → ALARM`.

`describe-alarm-history` parsers that only count `oldState.stateValue == "OK" && newState.stateValue == "ALARM"` **undercount actual alarm firings**. For alarms with `TreatMissingData: missing`, rely on the **metric datapoint breach densities** (`recentDatapoints` from `StateReasonData`) and daily recurrence pattern as the ground truth, not just OK→ALARM transition counts. Counting `INSUFFICIENT_DATA → ALARM` requires inspecting `HistoryData` for both transition directions:

```python
data = json.loads(item.get('HistoryData', '{}'))
old = data.get('oldState', {}).get('stateValue')
new = data.get('newState', {}).get('stateValue')
if old in ('OK', 'INSUFFICIENT_DATA') and new == 'ALARM':
    count += 1
```

## Pitfall — null `error.message` and `userAgent` on `/authenticate` 400 samples

When sampling individual `/authenticate` 400 log lines with `limit N` in Logs Insights, both `error.message` and `userAgent` may be `null`. This occurs because:
- The validation middleware rejects the request before `error.message` is populated.
- The client does not send a `User-Agent` header.

Do not rely on `error.message` content or `userAgent` presence to classify the rejection reason for `/authenticate` 400s. The classification should be based on the aggregate pattern (`POST /authenticate`, `400`, `level: warn`, `projectId: "unknown"`) and daily recurrence, not on per-sample message text.

## Pitfall — Logs Insights `stats by` with hyphenated nested JSON field names

When writing Logs Insights aggregate queries for `api-service` structured logs, nested JSON keys containing hyphens (e.g., `request.headers["user-agent"]`) cause `MalformedQueryException` when used in a `stats by` clause with quoted field access. Workarounds:
1. Use the auto-extracted flattened field name (hyphen stripped): `request.headers.useragent`
2. Use `fields` + `as` to rename first, then aggregate: `fields request.headers."user-agent" as ua | stats count() by ua`
3. For `filter` and `fields` clauses, the quoted syntax `request.headers."user-agent"` works fine; the restriction applies only to `stats by`.

## Pitfall — log ingestion lag hides current trigger

The `api-service` log group receives very high traffic. During a spike, CloudWatch Logs indexing can lag behind the metric-filter evaluation, so `filter-log_events` may return zero results even when the metric has demonstrably breached. If this happens during triage, do not conclude no logs exist. Instead, verify the exact 5-minute `Sum` datapoints via `get_metric_statistics` on the `ConsoleErrors` metric for the alarm window, and compare the daily recurrence pattern for 16:50–17:20 UTC. The metric is the ground truth; empty log search is a lag artifact for this high-volume service.

## Pitfall — Logs Insights auto-extracted field collision

CloudWatch Logs Insights auto-extracts top-level JSON keys as query fields. If a log line contains `"status":400`, then `status` is already available without parsing. Adding `parse @message '"status":*' as status` in the same query raises `MalformedQueryException: Ephemeral field is already defined: status`. Remove redundant `parse` clauses for fields already present as top-level JSON keys, or rename the alias (e.g., `as parsed_status`).

## Pitfall — `logs.current_error_details` may sample a minor signature, not the dominant one

The helper's `logs.current_error_details` list is built from a fixed small sample of trigger-centered log lines and can end up entirely populated with a low-count secondary signature (e.g., 3 samples of `POST /projects/{pid}/user-journeys/.../enter` 400) even when `logs.current_top_signatures` shows a completely different pattern dominating the alarm window by volume (e.g., `POST /authenticate` 400 at 293/300 lines, ~98%). Do not let `current_error_details` alone decide the root cause for this alarm family. Always cross-check `logs.current_top_signatures[].count_in_current_alarm_window`: the signature with the highest count in the current window is the actual trigger, and `/authenticate` at ≥90% is the known noise pattern regardless of what `current_error_details` happened to sample.

## Classification guidance

- **`no_action`** (default): when the alarm-window breakdown shows ≥ 90 % volume from a known false-positive signature and all logs are `level: warn`. This covers:
  - `/authenticate` 400 from `Apache-HttpClient/5.3.1 (Java/17.0.19)` with `"Missing required fields"`
  - `POST /projects/{pid}/campaigns/{cid}/send` 400 with `"Bad request: campaign <id> does not exist"` from a single client IP
  Use this even when `filter-log_events` returns empty because the daily recurrence and metric datapoints alone are sufficient evidence.
- **`needs_fix`**: only if the dominant signature is outside the known false-positive families, if a new non-authenticate 4xx path spikes outside the daily ~02:11 KST window, or if the `level` field shows `error` rather than `warn` indicating an unhandled exception path.

2026-06-22 alarm window (16:50–17:20 UTC / 2026-06-23 01:50–02:20 KST):
- **Alarm transitions**: OK→ALARM at 17:11 UTC, ALARM→OK at 17:15 UTC; OK→ALARM at 17:16 UTC, ALARM→OK at 17:20 UTC (2 back-to-back, sliding-window artifact)
- Metric datapoints: 13.0 (16:50), 12.0 (16:55), 887.0 (17:00), 835.0 (17:05), 8.0 (17:10), 9.0 (17:15); threshold 100.0, 3 of 4 datapoints required
- Total `error-response` with status ≥ 400 (Logs Insights): **1,764**
- `/authenticate` 400: **1,732** (98.2%)
  - User-Agent: `Apache-HttpClient/5.3.1 (Java/17.0.19)` **1,707**, `python-requests/2.32.3` **17**, `node` **8**
  - Level: **100% `warn`**; explicit `level == "error"` count: **0**
  - `projectId`: **`"unknown"`** on all `/authenticate` lines
- Secondary signatures (all `warn`): `DELETE /projects/80fd28969702573797f4d7f77063e47b/.../recipients/removes` 400×18, `POST /track-event` 401×9, `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/campaigns/icKePI/send` 400×3 (`class101`), `POST /projects/0c61d690f3425c13875c2c4902616b40/campaigns/CJDzWt/send` 400×1 (`sconn`), `GET /user-state/2b9f5a6685ba5b839803f1338a539724/...` 400×1
- 30d/7d/1d/10m OK→ALARM counts (HistoryData): **57 / 14 / 2 / 0**

**2026-07-08 alarm window (16:56–17:16 UTC / 07-09 01:56–02:16 KST, Slack subscription automated path)**:
- Metric datapoints: 319.0 (16:56), 1014.0 (17:01), 700.0 (17:06); threshold 100.0
- `logs.current_top_signatures` reported **exactly one** signature this time — `/authenticate` 400, `level: warn`, `projectId: "unknown"` — at `count_in_current_alarm_window: 300` (100% of the sampled window, no secondary signature detected at all, unlike most days which show a small tail of `blockservice`/`campaigns/.../send`/`track-event` noise).
- 30d/7d/1d/10m: 71/27/2/2 — still matches the ~2/day baseline cadence.
- Confirms the pattern is stable at day 40+ of observation; still `no_action` when the window is a clean single-signature `/authenticate` match with no `level: error` and no single-project 401 anomaly (contrast with Variant D/E, which need per-project breakdown of any `/track-event` 401 slice before ruling out an incident).

Result: identical to the known daily ~02:11 KST `/authenticate` authentication rejection burst. All signals are handled `warn` validation rejections; no customer impact.

## Long-term remediation options

1. **Metric filter refinement**: change the metric filter to exclude `$.path = "/authenticate"` if this path is accepted noise, or require `$.level = "error"` so handled `warn` rejections do not increment the alarm.
2. **Log-level audit**: verify that `/authenticate` validation rejections should remain `WARN` (they are handled) and that any genuinely unexpected 4xx paths stay `ERROR`.
3. **Separate alarm**: if `/authenticate` client errors need monitoring, create a dedicated lower-priority alarm for that single path so the general 4xx alarm retains signal for real issues.
