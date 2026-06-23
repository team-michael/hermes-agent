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

Result: identical to the known daily ~02:11 KST `/authenticate` authentication rejection burst. All signals are handled `warn` validation rejections; no customer impact.

## Long-term remediation options

1. **Metric filter refinement**: change the metric filter to exclude `$.path = "/authenticate"` if this path is accepted noise, or require `$.level = "error"` so handled `warn` rejections do not increment the alarm.
2. **Log-level audit**: verify that `/authenticate` validation rejections should remain `WARN` (they are handled) and that any genuinely unexpected 4xx paths stay `ERROR`.
3. **Separate alarm**: if `/authenticate` client errors need monitoring, create a dedicated lower-priority alarm for that single path so the general 4xx alarm retains signal for real issues.
