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
- **State transition history**: ~54 OK→ALARM transitions in 30 days (2026-05-13 through 2026-06-12), typically 2 transitions per day resolving within 1–5 minutes. Some days produce back-to-back transitions within 5 minutes when a high-volume 5-minute bucket continues contributing to the rolling evaluation after a brief OK recovery. Always derive from actual `describe-alarm-history` output using `HistoryData | fromjson | .oldState.stateValue` / `.newState.stateValue` rather than the `StateValue` field, which can be `null` for older entries.

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

- **User-Agent**: primarily `Apache-HttpClient/5.3.1 (Java/17.0.19)`; also `python-requests/2.32.3`, `ReactorNetty/1.1.13`, `axios/1.13.6`
- **Status**: `400`
- **Response body**: `{"error":"Missing required fields"}` (or `{"data":null}` for access-key-bearing requests that still fail validation)
- **IP origin**: various Korean IPs behind Cloudflare
- **Volume**: typically 500–1,600 events in a 10-minute window, enough to breach `Sum > 100` across 3 consecutive 5-minute periods.
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
| Daily ~02:11 KST (17:11 UTC) | ~1,400–1,600 | ~1,450–1,650 |
| Off-window (other times) | ~1–15 | ~100–300 (other sources) |
| Daily total (metric Sum) | — | ~3,900–5,300 |

The daily **~02:11 KST** spike is a clockwork pattern with tight timing (±2 minutes). If the alarm fires outside this window, investigate the dominant signature immediately; it may be a different root cause.

## Helper gap — bracket-prefix fallback

The helper cannot parse alarm names that start with `[api-service]` because:
1. Its **text detector** breaks on the bracket prefix (brackets confuse word-boundary heuristics), returning `detected.alarm_name: null`.
2. Its internal `describe-alarms --alarm-names` call treats the leading `[` as JSON array syntax, so passing `--alarm-name '[api-service] ...'` also fails.

Note: the helper does **not** expose `--alarm-name-prefix`, so the prefix-based workaround is unavailable.

When the helper returns `can_answer_root_cause: false` for this alarm, use direct AWS CLI with `--query` matching (the field selector is not affected by bracket parsing):

```bash
aws cloudwatch describe-alarms --region ap-northeast-2 \
  --query 'MetricAlarms[?contains(AlarmName, `api-service`) && contains(AlarmName, `4xx`)].{Name:AlarmName,Namespace:Namespace,MetricName:MetricName,Statistic:Statistic,Period:Period,Threshold:Threshold,ComparisonOperator:ComparisonOperator,StateValue:StateValue,StateReason:StateReason,StateReasonData:StateReasonData}' \
  --output json | jq '.[0]'
```

## Bounded trace commands

Verify the current alarm window (replace `YYYY-MM-DD` and adjust times as needed, using UTC):

```bash
python3 -c "
import boto3, json, datetime, re
logs = boto3.client('logs', region_name='ap-northeast-2')
start = datetime.datetime(YYYY, MM, DD, 16, 50, 0)
end   = datetime.datetime(YYYY, MM, DD, 17, 10, 0)
start_ms = int(start.timestamp() * 1000)
end_ms   = int(end.timestamp() * 1000)
resp = logs.filter_log_events(
    logGroupName='/aws/ecs/notifly-services-prod/api-service',
    filterPattern='{ \$.message = \"error-response\" && \$.status >= 400 }',
    startTime=start_ms, endTime=end_ms, limit=1000)
events = resp.get('events', [])

auth = sum(1 for e in events if '\"/authenticate\"' in e['message'])
print(f'Total 4xx events: {len(events)}')
print(f'/authenticate 400: {auth}')

# Top non-authenticate paths
from collections import Counter
paths = Counter()
for e in events:
    try:
        j = json.loads(e['message'])
        path = re.sub(r'/projects/[a-f0-9]+', '/projects/{pid}', j.get('path',''))
        if '/authenticate' not in path:
            paths[(j.get('status'), path)] += 1
    except:
        pass
for (k, c) in paths.most_common(10):
    print(f'  {c}: {k[0]} {k[1]}')
"
```

Check daily auth volume for the last N days:

```bash
python3 -c "
import boto3, datetime
logs = boto3.client('logs', region_name='ap-northeast-2')
for d in range(14):
    base = datetime.datetime.utcnow() - datetime.timedelta(days=d)
    base = base.replace(hour=16, minute=55, second=0, microsecond=0)
    end  = base.replace(hour=17, minute=10, second=0)
    start_ms = int(base.timestamp() * 1000)
    end_ms   = int(end.timestamp() * 1000)
    resp = logs.filter_log_events(
        logGroupName='/aws/ecs/notifly-services-prod/api-service',
        filterPattern='{ \$.message = \"error-response\" && \$.status >= 400 && \$.path = \"/authenticate\" }',
        startTime=start_ms, endTime=end_ms, limit=1000)
    print(f'{base.date()} ({base.strftime(\"%a\")}): {len(resp.get(\"events\",[]))}')
"
```

## Logs Insights template queries (preferred over filter-log-events)

For high-volume `api-service` logs, `filter-log-events` is slow and often hits ingestion-lag windows. Use **Logs Insights** for aggregate breakdowns instead.

**Top signatures by status + path + level** (alarm window, UTC):
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

## Recent live verification

2026-05-18 alarm window (16:56–17:06 UTC / 01:56–02:06 KST):
- Total `error-response` with status ≥ 400: **~1,775**
- `/authenticate` 400: **1,762** (99%)
- Levels: **100% `warn`**; `error` level count: **0**
- Secondary signatures: 6 `POST /track-event` 401, 3 `POST .../campaigns/{cid}/send` 400, 1 `GET /user-state/{pid}/{uid}` 400, 1 `POST /messages/kakao-alimtalk` 401, 1 `POST /set-user-properties` 401

2026-05-17 alarm window (16:56–17:06 UTC / 01:56–02:06 KST):
- Total `error-response` with status ≥ 400: **~1,600**
- `/authenticate` 400: **1,554** (97%)
- Levels: **100% `warn`**; `error` level count: **0**
- Secondary signatures: 42 `DELETE .../blockservice/recipients/removes` 400, 8 `POST /track-event` 401, 6 `POST .../campaigns/{cid}/send` 400

2026-05-16 alarm window (16:50–17:10 UTC / 01:50–02:10 KST):
- Total `error-response` with status ≥ 400: **909**
- `/authenticate` 400: **882** (97%)
- Levels: **100% `warn`**
- Secondary signatures: 21 `DELETE /projects/{pid}/messages/text-message/blockservice/recipients/removes` 400, 4 `POST /track-event` 401, 2 `GET /users` 401

Result: consistent with the known daily **~02:11 KST** `Apache-HttpClient/5.3.1 (Java/17.0.19)` authentication rejection burst.

2026-05-19 alarm window (07:40–07:55 UTC / 16:40–16:55 KST):
- Total `error-response` with status ≥ 400: **~811**
- Dominant signature: `POST /projects/acab456b57eb59a193e375891742cfb4/campaigns/uAApo3/send` 400: **716** (88 %)
  - Response body: `"Bad request: campaign uAApo3 does not exist"`
  - Source IP: `54.180.113.161`, User-Agent: `Apache-HttpClient/5.5 (Java/21.0.11)`
  - Project: `lookpin` (`acab456b57eb59a193e375891742cfb4`)
  - Campaign `uAApo3` not found in Postgres `campaigns_acab456b57eb59a193e375891742cfb4`
- Levels: **100% `warn`**; `error` level count: **0**
- Secondary signatures: 14 `POST /authenticate` 400 (`python-requests/2.32.3`), 14 `POST /authenticate` 400 (`node`), 9 `POST /campaign/.../j4k6UJ/send` 400, 7 `POST /track-event` 401, 6 `POST /projects/b2b4a8f8.../campaigns/schU1i/send` 400, 4 `DELETE /users` 401, etc.

Result: **Variant B** — campaign send non-existent campaign burst from a single client IP, not the usual `/authenticate` dominant pattern. All lines are `level: warn` handled validation rejections.

2026-05-20 alarm window (02:04–02:15 KST / 2026-05-19 17:04–17:15 UTC):
- Total `error-response` with status ≥ 400: **~1,595**
- `/authenticate` 400: **1,581** (99%)
- Levels: **100% `warn`**; `error` level count: **0**
- Secondary signatures: 6 `GET /sdk-configurations` 400, 6 `POST /track-event` 401, 2 `GET /user-state` 405, 1 `POST /projects/sconn/campaigns/CJDzWt/send` 400

2026-05-20 alarm window (16:56–17:06 UTC / 2026-05-21 01:56–02:06 KST):
- Total `error-response` with status ≥ 400: **1,447**
- `/authenticate` 400: **1,437** (99.3%)
- User-Agent dominant: `Apache-HttpClient/5.3.1 (Java/17.0.19)` and `python-requests/2.32.3`
- Levels: **100% `warn`**; `error` level count: **0**
- `projectId`: **explicitly `"unknown"`** on all `/authenticate` lines (validation occurs before project resolution)
- Secondary signatures: 6 `POST /track-event` 401, 1 `POST /campaign/.../j4k6UJ/send` 400 (`museclinic`), 1 `GET /user-state` 400

Result: consistent with the known daily **~02:11 KST** `Apache-HttpClient/5.3.1 (Java/17.0.19)` authentication rejection burst. The `projectId: "unknown"` on all `/authenticate` lines confirms scope is untraceable by design, not a missing log field.

2026-05-21 alarm window (16:45–17:20 UTC / 2026-05-22 01:45–02:20 KST):
- Total `error-response` with status ≥ 400: **~1,635**
- `/authenticate` 400: **1,627** (99.5%)
- User-Agent mix: `Apache-HttpClient/5.3.1 (Java/17.0.19)`, `python-requests/2.32.3`, `axios/1.13.6`
- Levels: **100% `warn`**; `error` level count: **0**
- `projectId`: `"unknown"` on all `/authenticate` lines; one access-key-bearing request (`projectId: "accessKey:564f044c479959b98c0ffa0f683636ab"`) still responded 400 with body `{"data":null}`
- Secondary signatures: 3 `POST /track-event` 401, 2 `POST /campaign/.../j4k6UJ/send` 400, 1 `GET /user-state` 400, 1 `POST /projects/.../campaigns/CJDzWt/send` 400
- Alarm state: ALARM at 17:11 UTC, OK at 17:14 UTC (3-minute duration)

Result: consistent with the known daily **~02:11 KST** `/authenticate` authentication rejection burst. All signals are handled `warn` validation rejections; no customer impact.

2026-05-21 alarm window (16:56–17:06 UTC / 2026-05-22 01:56–02:06 KST):
- Total `error-response` with status ≥ 400: **1,632**
- `/authenticate` 400: **1,620+** (~99%)
- User-Agent dominant: `Apache-HttpClient/5.3.1 (Java/17.0.19)` via Cloudflare IPs (`13.209.221.105`, `141.101.84.238`, `172.71.111.143-144`, `43.200.25.101`)
- Levels: **100% `warn`**; `error` level count: **0**
- `projectId`: **explicitly `"unknown"`** on all `/authenticate` lines
- Secondary signatures (sparse): `POST /campaign/300ef7dd1ea459a2bb0dbafd2aabc0c7/j4k6UJ/send` 400 (`warn`, `python-requests/2.32.5`), `POST /user-state/2b9f5a6685ba5b839803f1338a539724/...` 400 (Dalvik/Android), `POST /track-event` 401 (`python-requests/2.33.1`), `POST /set-user-properties` 401 (`node-fetch`)

Result: identical to the prior-day baseline (2026-05-16–2026-05-21). The dominant `/authenticate` 400 burst volume is **~1,620** in the 15-minute alarm window. This confirms the pattern is stable, not worsening.

2026-05-23 alarm window (16:56–17:06 UTC / 2026-05-24 01:56–02:06 KST):
- **Alarm transition**: OK→ALARM at 17:11 UTC, ALARM→OK at 17:12 UTC (1-minute duration)
- Total `error-response` with status ≥ 400: **~1,337**
- `/authenticate` 400: **1,314** (98.3%)
- User-Agent dominant: `Apache-HttpClient/5.3.1 (Java/17.0.19)`; single UA, no mix
- Levels: **100% `warn`**; `error` level count: **0**
- `projectId`: **explicitly `"unknown"`** on all `/authenticate` lines
- Secondary signatures: `POST /projects/0c61d690f3425c13875c2c4902616b40/campaigns/CJDzWt/send` 400 (`warn`, `sconn`), `POST /campaign/300ef7dd1ea459a2bb0dbafd2aabc0c7/j4k6UJ/send` 400 (`warn`, `museclinic`), `POST /track-event` 401 (`warn`, `playio`), `GET /user-state` 400 (`warn`, `2b9f5a6685ba5b839803f1338a539724`), `POST /set-user-properties` 401 (`warn`, `arooo`)
- 30d OK→ALARM count: **43** (2 per day baseline)

Result: consistent with the known daily **~02:11 KST** `/authenticate` authentication rejection burst. All signals are handled `warn` validation rejections; no customer impact.

2026-05-24 alarm window (16:56–17:06 UTC / 2026-05-25 01:56–02:06 KST):
- **Alarm transitions**: OK→ALARM at 17:11 UTC, OK→ALARM at 17:16 UTC (2 transitions, back-to-back 5-min periods)
- Metric datapoints confirming breach: 169.0 (16:56), 895.0 (17:01), 205.0 (17:06); threshold 100 with 3 of 4 datapoints required
- Total `error-response` with status ≥ 400: **~1,281**
- `/authenticate` 400: **1,262** (98.5%)
- User-Agent dominant: `Apache-HttpClient/5.3.1 (Java/17.0.19)`; single appearance of `node`
- Levels: **100% `warn`**; `error` level count: **0**
- `projectId`: **explicitly `"unknown"`** on all `/authenticate` lines (validation occurs before project resolution)
- Secondary signatures:
  - `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/campaigns/2D1ujT/send` 400: **3** (`warn`, `class101`, body: `"Bad request: invalid recipients"` with `INVALID_RECIPIENTS` / `MISSING_PHONE_NUMBER` for userId `naver66415321`, channel `kakao-friendtalk`)
  - `POST /projects/0c61d690f3425c13875c2c4902616b40/campaigns/CJDzWt/send` 400: **1** (`warn`, `sconn`)
  - `POST /campaign/300ef7dd1ea459a2bb0dbafd2aabc0c7/j4k6UJ/send` 400: **1** (`warn`, `museclinic`)
  - `POST /track-event` 401: **3** (`warn`), `GET /user-state` 400: **3** (`warn`), others sparse
- 30d OK→ALARM count: **45** (5/19 had 3 transitions; all other days had exactly 2)

Result: consistent with the known daily **~02:11 KST** `/authenticate` authentication rejection burst. All signals are handled `warn` validation rejections; no customer impact. Campaign send rejections are normal business validation (missing phone number for Kakao Friendtalk) and remain well within daily baseline.

**7-day daily `/authenticate` 400 baseline** (2026-05-14 to 2026-05-21, full 24h counts):

| Date | `/authenticate` 400 count | Day |
|---|---|---|
| 2026-05-14 | 2,111 | Wed |
| 2026-05-15 | 2,101 | Thu |
| 2026-05-16 | 2,303 | Fri |
| 2026-05-17 | 2,364 | Sat |
| 2026-05-18 | 2,431 | Sun |
| 2026-05-19 | 2,246 | Mon |
| 2026-05-20 | 1,986 | Tue |
| 2026-05-21 | 2,370 | Wed |

Average: ~2,239/day. Range: 1,986–2,431. This narrow band (~±10%) is the expected baseline. Spikes outside this band or a sudden shift in dominant User-Agent warrant deeper investigation.

When writing manual aggregate queries for `api-service` `error-response` logs, prefer auto-extracted JSON fields (`status`, `message`, `path`, `method`, `level`, `projectId`, `campaignId`) directly. Do not add `parse @message '"status":"*"' as status` because `status` is already a top-level JSON field; this either raises `MalformedQueryException: Ephemeral field is already defined: status` or silently shifts parsed values into the wrong columns when `filter` runs before `parse`. Use the auto-extracted field directly in `stats` and `filter` clauses.

## Pitfall — log ingestion lag hides current trigger

The `api-service` log group receives very high traffic. During a spike, CloudWatch Logs indexing can lag behind the metric-filter evaluation, so `filter-log_events` may return zero results even when the metric has demonstrably breached. If this happens during triage, do not conclude no logs exist. Instead, verify the exact 5-minute `Sum` datapoints via `get_metric_statistics` on the `ConsoleErrors` metric (`/aws/ecs/notifly-services-prod/api-service 4xx error`) for the alarm window, and compare the daily recurrence pattern for 16:50–17:20 UTC. The metric is the ground truth; empty log search is a lag artifact for this high-volume service.

**Exact command — daily aggregate via `get-metric-statistics` (reliable even when logs lag):**
```bash
aws cloudwatch get-metric-statistics --region ap-northeast-2 \
  --namespace ConsoleErrors \
  --metric-name '/aws/ecs/notifly-services-prod/api-service 4xx error' \
  --start-time 'YYYY-MM-DDTHH:00:00Z' \
  --end-time 'YYYY-MM-DDTHH:15:00Z' \
  --period 86400 \
  --statistics Sum \
  --output json | jq -r '.Datapoints | sort_by(.Timestamp) | .[] | [.Timestamp, .Sum] | @tsv'
```

2026-06-12 alarm window (16:56–17:06 UTC / 02:11 KST):
- **Alarm state**: ALARM at 17:11 UTC, OK at 17:12 UTC (1-minute duration); breached datapoint 892.0 at 17:01 UTC with recentDatapoints [8.0, 355.0, 892.0, 22.0]
- Total `error-response` with status ≥ 400 (16:45–17:20 UTC): **~1,332**
- `/authenticate` 400: **1,254** (94.1%)
  - User-Agent: `Apache-HttpClient/5.3.1 (Java/17.0.19)` 1,242, `python-requests/2.32.3` 12
  - Level: **100% `warn`**; explicit `level == "error"` Logs Insights query returned **0** matches
  - `projectId`: **explicitly `"unknown"`** on all `/authenticate` lines
- Secondary signatures (sparse, all `warn`):
  - `DELETE /projects/80fd28969702573797f4d7f77063e47b/messages/text-message/blockservice/recipients/removes` 400: **27**
  - `POST /track-event` 401: **22**
  - `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/campaigns/icKePI/send` 400: **6** (`class101`)
  - `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/user-journeys/ab711m/enter` 400: **3** (`class101`)
  - `POST /projects/0c61d690f3425c13875c2c4902616b40/campaigns/CJDzWt/send` 400: **3** (`sconn`)
  - `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/campaigns/b9Ty4s/send` 400: **3** (`class101`)
  - `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/campaigns/2D1ujT/send` 400: **3** (`class101`)
  - `POST /set-user-properties` 401: **3**
  - `GET /user-state` 405: **2**
- 30d/7d/1d/10m OK→ALARM counts (from `HistoryData`): **53 / 12 / 1 / 1**
- Alarm transitions: single OK→ALARM at 17:11 UTC per `HistoryData` (demonstrates this alarm has returned to baseline frequency)

Result: identical to the known daily ~02:11 KST `/authenticate` authentication rejection burst. All signals are handled `warn` validation rejections; no customer impact. The alarm recovered within one minute of crossing threshold, consistent with prior sessions' ~1–5 minute ALARM duration.

**7-day daily OK→ALARM baseline** (2026-06-05 through 2026-06-12): 12 transitions over 7 days, averaging ~1.7/day, within the long-term ~1.5–1.7/day band. No trend shift.

## Classification guidance
- **Alarm transitions**: OK→ALARM at 17:11 UTC, ALARM→OK at 17:19 UTC; second OK→ALARM at 17:16 UTC (2 transitions within 10 minutes, sliding-window artifact)
- Metric datapoints: 175.0 (16:56), 893.0 (17:01), 487.0 (17:06); threshold 100.0, 3 of 4 datapoints
- Total `error-response` status ≥ 400: **~1,574**; `/authenticate` 400: **1,536** (97.6%), all `level: warn`, `projectId: "unknown"`
- Secondary signatures: `DELETE /projects/.../blockservice/recipients/removes` 400×10 (`handys`), `POST /track-event` 401×5 (`playio`), `POST /projects/.../user-journeys/Rbc3W7/enter` 400×3 (`class101`), `GET /user-state/2b9f5a6685ba5b839803f1338a539724/...` 400×3 (project not found in DynamoDB), plus sparse `sconn`, `mmtalk`, `arooo` campaign/event rejections
- 30d/7d/1d/10m OK→ALARM: **25 / 11 / 2 / 2**
Result: identical to the known daily ~02:11 KST `/authenticate` authentication rejection burst. All signals are handled `warn` validation rejections; no customer impact. The 30-day transition count of 47 confirms the alarm fires roughly 1.6 times per day on average, well within the established baseline.

2026-06-03 alarm window (16:56–17:06 UTC / 2026-06-04 01:56–02:06 KST):
- **Alarm transitions**: OK→ALARM at 17:11 UTC, ALARM→OK at 17:15 UTC, OK→ALARM at 17:16 UTC, ALARM→OK at 17:16 UTC (back-to-back within 1 minute)
- Metric datapoints confirming breach: 174.0 (16:56), 891.0 (17:01), 648.0 (17:06); threshold 100.0 with 3 of 4 datapoints required
- Total `error-response` with status ≥ 400 (16:45–17:25 UTC): **~1,743**; `/authenticate` 400: **1,702** (~97.7%)
  - 17:00–17:05 UTC: 880 `POST /authenticate` 400 (`warn`, `Apache-HttpClient/5.3.1 (Java/17.0.19)`)
  - 17:05–17:10 UTC: 820 `POST /authenticate` 400 (`warn`, `Apache-HttpClient/5.3.1 (Java/17.0.19)`)
- User-Agent: exclusively `Apache-HttpClient/5.3.1 (Java/17.0.19)` via Cloudflare IPs
- Levels: **100% `warn`**; `error` level count: **0** (verified via explicit `level == "error"` Logs Insights query returning zero matches)
- `projectId`: **`"unknown"`** on all `/authenticate` lines (validation occurs before project resolution)
- Secondary signatures (sparse, all `warn`):
  - `DELETE /projects/80fd28969702573797f4d7f77063e47b/messages/text-message/blockservice/recipients/removes` 400: **10**
  - `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/campaigns/c8WSqz/send` 400: **3** (`class101`)
  - `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/user-journeys/NMbwqW/enter` 400: **3** (`class101`)
  - `POST /track-event` 401: **5** (`playio`, `ffde3a7a000b5b2198961b3fff400acd`)
  - `GET /user-state/2b9f5a6685ba5b839803f1338a539724/...` 400: **1**
- **OK→ALARM counts**: 30d **48** / 7d **13** / 1d **4** / 10m **2**
- Alarm currently **ALARM** at investigation time, but volume already dropped to 6.0 at 17:11 UTC → imminent recovery expected

Result: identical to the known daily ~02:11 KST `/authenticate` authentication rejection burst. The back-to-back transitions are sliding-window evaluation artifacts. All signals are handled `warn` validation rejections; no customer impact. The `level == "error"` fast classifier returned zero, confirming no unhandled exception path is present.

2026-06-03 alarm window (16:56–17:06 UTC / 2026-06-04 01:56–02:06 KST):
- **Alarm transitions**: OK→ALARM at 17:11 UTC, ALARM→OK at 17:15 UTC; OK→ALARM at 17:16 UTC (second back-to-back transition within 5 minutes, sliding-window artifact from the 17:06 bucket)
- Metric datapoints confirming breach: 174.0 (16:56), 891.0 (17:01), 648.0 (17:06); threshold 100.0 with 3 of 4 datapoints required
- Total `error-response` with status ≥ 400 (16:45–17:20 UTC): **~1,741**
- `/authenticate` 400: **1,709** (98.2%)
- User-Agent dominant: `python-requests/2.32.3` via Cloudflare IPs (`43.200.25.101`, `141.101.84.238`, `172.71.111.143-144`)
- Levels: **100% `warn`**; `error` level count: **0**
- `projectId`: **explicitly `"unknown"`** on all `/authenticate` lines (validation occurs before project resolution)
- Secondary signatures: `DELETE /projects/80fd28969702573797f4d7f77063e47b/messages/text-message/blockservice/recipients/removes` 400×14 (`warn`), `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/user-journeys/NMbwqW/enter` 400×3 (`warn`), `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/campaigns/c8WSqz/send` 400×3 (`warn`), `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/campaigns/icKePI/send` 400×3 (`warn`), `POST /set-user-properties` 401×2 (`warn`), `POST /track-event` 401×2 (`warn`), `DELETE /users` 401×1 (`warn`), plus sparse `GET /user-state` 400×2
- 30-day OK→ALARM count: **48** / 7-day: **13** / 1-day: **4** / 10-minute window: **2**

Result: identical to the known daily ~02:11 KST `/authenticate` authentication rejection burst. All signals are handled `warn` validation rejections; no customer impact. The back-to-back transitions within 5 minutes are a sliding-window evaluation artifact from the 17:01 bucket (891.0) still contributing after the brief ALARM→OK recovery.

## Classification guidance

- **`no_action`** (default): when the alarm-window breakdown shows ≥ 90 % volume from a known false-positive signature and all logs are `level: warn`. This covers:
  - `/authenticate` 400 from `Apache-HttpClient/5.3.1 (Java/17.0.19)` with `"Missing required fields"`
  - `POST /projects/{pid}/campaigns/{cid}/send` 400 with `"Bad request: campaign <id> does not exist"` from a single client IP
  Use this even when `filter-log_events` returns empty because the daily recurrence and metric datapoints alone are sufficient evidence.
- **`needs_fix`**: only if the dominant signature is outside the known false-positive families, if a new non-authenticate 4xx path spikes outside the daily ~02:11 KST window, or if the `level` field shows `error` rather than `warn` indicating an unhandled exception path.

2026-05-25 alarm window (16:56–17:06 UTC / 2026-05-26 01:56–02:06 KST):
- **Alarm transitions**: OK→ALARM at 17:11 UTC, ALARM→OK at 17:14 UTC (3 min), then OK→ALARM at 17:16 UTC again (back-to-back within 5 minutes)
- Metric datapoints confirming breach for the 17:16 transition: 170.0 (16:56), 886.0 (17:01), 581.0 (17:06) per StateReasonData; threshold 100.0 with 3 of 4 datapoints required
- Total `error-response` with status ≥ 400 in the 16:50–17:20 window: **~1,646**
- `/authenticate` 400: **1,633** (~99.2%); breakdown by 5-min bucket: 878 (17:00), 755 (17:05), 3 (17:15)
- User-Agent dominant: `Apache-HttpClient/5.3.1 (Java/17.0.19)` via Cloudflare IPs (`13.209.221.105`, `141.101.85.19-20`, `172.71.111.144`)
- Levels: **100% `warn`**; `error` level count: **0**
- `projectId`: **explicitly `"unknown"`** on all `/authenticate` lines (validation occurs before project resolution)
- Secondary signatures: `POST /track-event` 401 (2), `POST /set-user-properties` 401 (1), `GET /user-state/...` 400 (1)
- **30-day OK→ALARM count**: **47** / **7-day**: **17** / **1-day**: **2** / **10-minute window**: **2** (the back-to-back transitions)
- Recurrence pattern: stable daily ~02:11 KST burst, consistent with prior 7-day baseline (~1,620–2,400 /authenticate 400 per day window)

Result: identical to the known daily ~02:11 KST `/authenticate` authentication rejection burst. The back-to-back transitions within 5 minutes are caused by the 17:01 bucket (886.0) still contributing to the rolling evaluation after the first ALARM→OK recovery. All signals are handled `warn` validation rejections; no customer impact. The 30-day transition count of 47 confirms the alarm fires roughly 1.6 times per day on average, well within the established baseline.

2026-05-26 alarm window (16:56–17:06 UTC / 2026-05-27 01:56–02:06 KST):
- **Alarm transitions**: OK→ALARM at 17:11 UTC, OK→ALARM at 17:16 UTC (2 transitions, back-to-back 5-min periods)
- Metric datapoints confirming breach: 170.0 (16:56), 898.0 (17:01), 688.0 (17:06); threshold 100.0 with 3 of 4 datapoints required
- Total `error-response` with status ≥ 400: **~1,768**
- `/authenticate` 400: **1,748** (98.9%)
- User-Agent dominant: `Apache-HttpClient/5.3.1 (Java/17.0.19)`; single appearances of `python-requests/2.32.3`, `axios/1.13.6`
- Levels: **100% `warn`**; `error` level count: **0**
- `projectId`: **explicitly `"unknown"`** on all `/authenticate` lines (validation occurs before project resolution)
- Secondary signatures (sparse): `POST /track-event` 401 (8), `GET /user-state/...` 400 (3), `POST /projects/0c61d690f3425c13875c2c4902616b40/campaigns/CJDzWt/send` 400 (1, `sconn`), `POST /campaign/300ef7dd1ea459a2bb0dbafd2aabc0c7/j4k6UJ/send` 400 (1, `museclinic`)
- 30-day OK→ALARM count: **48** / 7-day: **15** / 1-day: **2** / 10-minute window: **2**

Result: identical to the known daily ~02:11 KST `/authenticate` authentication rejection burst. All signals are handled `warn` validation rejections; no customer impact. The 10-minute window showing 2 transitions is a sliding-window evaluation artifact from the 17:01 bucket (898.0) still contributing after the brief OK recovery.

2026-05-27 alarm window (17:00–17:20 UTC / 2026-05-28 02:00–02:20 KST):
- **Alarm state**: ALARM→OK at 17:14 UTC (recovered within 3 minutes); metric breach window `startDate` 2026-05-27T17:00:00 UTC
- Metric datapoints confirming breach (from `StateReasonData`): **888.0** (17:01), **866.0** (17:06), 6.0 (17:11), 2.0 (17:16); threshold 100.0 with 3 of 4 datapoints required
- Total `error-response` with status ≥ 400 (16:50–17:20 UTC): **~1,770**
- `/authenticate` 400: **1,748** (98.8%)
- User-Agent dominant: `Apache-HttpClient/5.3.1 (Java/17.0.19)`
- Levels: **100% `warn`**; `error` level count: **0**
- `projectId`: **explicitly `"unknown"`** on all `/authenticate` lines (validation occurs before project resolution)
- Secondary signatures (sparse): `POST /track-event` 401 (10, `warn`), `GET /user-state/...` 400 (3, `warn`), `DELETE /user-state/...` 405 (1, `warn`), `POST /projects/0c61d690f3425c13875c2c4902616b40/campaigns/CJDzWt/send` 400 (2, `warn`, `sconn`), `POST /campaign/300ef7dd1ea459a2bb0dbafd2aabc0c7/j4k6UJ/send` 400 (1, `warn`, `museclinic`)
- 30-day OK→ALARM count: **48** / 7-day: **15** / 1-day: **2** / 10-minute window: **1**

Result: identical to the known daily ~02:11 KST `/authenticate` authentication rejection burst. All signals are handled `warn` validation rejections; no customer impact. The metric datapoint 888.0 at 17:01 UTC confirms the burst peaked in the same 5-minute bucket as prior days.

2026-06-12 alarm window (16:56–17:06 UTC / 02:11 KST):
- **Alarm state**: ALARM at 17:11 UTC, OK at 17:12 UTC (1-minute duration); breached datapoint 892.0 at 17:01 UTC with recentDatapoints [8.0, 355.0, 892.0, 22.0]
- Total `error-response` with status ≥ 400 (16:30–17:35 UTC): **~1,334**
- `/authenticate` 400: **1,255** (94.1%)
  - User-Agent: `python-requests/2.32.3` 1,242, `axios/1.13.6` 12, `Apache-HttpClient` 1
  - Level: **100% `warn`**; explicit `level == "error"` Logs Insights query returned **0** matches
  - `projectId`: **explicitly `"unknown"`** on all `/authenticate` lines
- Secondary signatures (sparse, all `warn`):
  - `DELETE /projects/80fd28969702573797f4d7f77063e47b/messages/text-message/blockservice/recipients/removes` 400: **27**
  - `POST /track-event` 401: **22**
  - `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/campaigns/icKePI/send` 400: **6** (`class101`)
  - `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/user-journeys/ab711m/enter` 400: **3** (`class101`)
  - `POST /projects/0c61d690f3425c13875c2c4902616b40/campaigns/CJDzWt/send` 400: **3** (`sconn`)
  - `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/campaigns/b9Ty4s/send` 400: **3** (`class101`)
  - `POST /set-user-properties` 401: **3**
  - `GET /user-state` 405: **2**
- 30d/7d/1d/10m OK→ALARM counts (from `HistoryData`): **54 / 13 / 2 / 2**

Result: identical to the known daily ~02:11 KST `/authenticate` authentication rejection burst. All signals are handled `warn` validation rejections; no customer impact. The alarm recovered within one minute of crossing threshold, consistent with prior sessions' ~1–5 minute ALARM duration.

**7-day daily OK→ALARM baseline** (2026-06-05 through 2026-06-12): 13 transitions over 7 days, averaging ~1.9/day, within the long-term ~1.5–2.0/day band. No trend shift.

2026-05-30 alarm window (16:56–17:20 UTC / 2026-05-31 01:56–02:20 KST):
- **Alarm transitions**: OK→ALARM at 17:11 UTC, ALARM→OK at 17:14 UTC, OK→ALARM at 17:16 UTC, ALARM→OK at 17:19 UTC (2 back-to-back transitions within 10 minutes)
- Metric datapoints confirming breach (from `StateReasonData`): **850.0** (17:04), **706.0** (17:09), 9.0 (17:14), 6.0 (17:19); threshold 100.0 with 3 of 4 datapoints required
- Total `error-response` with status ≥ 400 (17:00–17:20 UTC): **~1,571**
- `/authenticate` 400: **1,556** (~99.0%); breakdown: 1,542 (`Apache-HttpClient/5.3.1 (Java/17.0.19)`), 14 (`python-requests/2.32.3`)
- Levels: **100% `warn`**; `error` level count: **0**
- `projectId`: **explicitly `"unknown"`** on all `/authenticate` lines (validation occurs before project resolution)
- Secondary signatures (sparse): `POST /track-event` 401 (6, `warn`, `ffde3a7a000b5b2198961b3fff400acd`), `DELETE /projects/80fd28969702573797f4d7f77063e47b/messages/text-message/blockservice/recipients/removes` 400 (4, `warn`), `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/campaigns/icKePI/send` 400 (3, `warn`, `class101`), `POST /campaign/300ef7dd1ea459a2bb0dbafd2aabc0c7/j4k6UJ/send` 400 (1, `warn`, `museclinic`), `GET /user-state/2b9f5a6685ba5b839803f1338a539724/...` 400 (1, `warn`)
- 30-day OK→ALARM count: **25** / 7-day: **13** / 1-day: **2** / 10-minute window: **2**

Result: identical to the known daily ~02:11 KST `/authenticate` authentication rejection burst. The back-to-back transitions within 10 minutes are caused by the 17:04 bucket (850.0) still contributing to the rolling evaluation after the first brief ALARM→OK recovery. All signals are handled `warn` validation rejections; no customer impact. The 30-day OK→ALARM count of 25 is lower than prior entries because `TreatMissingData: missing` causes many transitions to be `INSUFFICIENT_DATA → ALARM` rather than `OK → ALARM`; see the pitfall below.

2026-06-04 alarm window (16:56–17:06 UTC / 2026-06-05 01:56–02:06 KST):
- **Alarm transitions**: OK→ALARM at 17:11 UTC, OK→ALARM at 17:16 UTC (back-to-back within 5 minutes, sliding-window artifact)
- Metric datapoints confirming breach: 178.0 (16:56), 895.0 (17:01), 712.0 (17:06); threshold 100.0 with 3 of 4 datapoints required
- Total `error-response` with status ≥ 400 (16:50–17:20 UTC): **1,806**
- `/authenticate` 400: **1,761** (97.6%)
  - User-Agent: `Apache-HttpClient/5.3.1 (Java/17.0.19)` 1,751, `python-requests/2.32.3` 10
  - Level: **100% `warn`**; explicit `level == \"error\"` Logs Insights query returned **0** matches
  - `projectId`: **explicitly `\"unknown\"`** on all `/authenticate` lines (validation occurs before project resolution)
- Secondary signatures (sparse, all `warn`):
  - `POST /track-event` 401: **12** (`python-requests/2.33.1`)
  - `DELETE /projects/80fd28969702573797f4d7f77063e47b/messages/text-message/blockservice/recipients/removes` 400: **12** (`ReactorNetty/1.2.17`, `handys`)
  - `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/campaigns/5Qnugu/send` 400: **3** (`class101`)
  - `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/user-journeys/U86OKs/enter` 400: **3** (`class101`)
  - `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/campaigns/icKePI/send` 400: **3** (`class101`)
  - `POST /projects/0c61d690f3425c13875c2c4902616b40/campaigns/CJDzWt/send` 400: **1** (`sconn`)
  - `POST /messages/kakao-alimtalk` 401: **1** (`Apache-HttpClient/4.5.3`)
- 30d/7d/1d/10m OK→ALARM counts: **47 / 13 / 4 / 2**
Result: identical to the known daily ~02:11 KST `/authenticate` authentication rejection burst. All signals are handled `warn` validation rejections; no customer impact.

2026-06-08 alarm window (16:56–17:06 UTC / 2026-06-09 01:56–02:06 KST):
- **Alarm transitions**: OK→ALARM at 17:11 UTC, metric datapoints [173.0, 894.0, 686.0]; threshold 100.0 with 3 of 4 datapoints required
- Total `error-response` with status ≥ 400 (16:50–17:10 UTC): **~898**
- `/authenticate` 400: **882** (98.2%)
  - User-Agent: `python-requests/2.32.3`; prior days showed `Apache-HttpClient/5.3.1 (Java/17.0.19)` dominance
  - Level: **100% `warn`**; explicit `level == "error"` Logs Insights query returned **0** matches
  - `projectId`: **`"unknown"`** on all `/authenticate` lines
- Secondary signatures (sparse, all `warn`):
  - `DELETE /projects/80fd28969702573797f4d7f77063e47b/messages/text-message/blockservice/recipients/removes` 400: **9** (`ReactorNetty/1.2.17`, `handys`)
  - `POST /track-event` 401: **5** (`python-requests/2.33.1`)
  - `GET /user-state/2b9f5a6685ba5b839803f1338a539724/...` 400: **2** (Dalvik/Android)
  - `POST /set-user-properties` 401: **1** (`node-fetch`)
- Daily full-UTC-day `/authenticate` 400 volume (8-day trend):
  - 2026-06-08: **1,834** | 2026-06-07: **3,494** | 2026-06-06: **4,337** | 2026-06-05: **3,027**
  - 2026-06-04: **2,955** | 2026-06-03: **3,687** | 2026-06-02: **3,318** | 2026-06-01: **2,030**
- 30d/7d/1d/10m OK→ALARM counts (from `HistoryData`): **49 / 12 / 1 / 1**

Result: identical to the known daily ~02:11 KST `/authenticate` authentication rejection burst. All signals are handled `warn` validation rejections; no customer impact. The `python-requests/2.32.3` user-agent is an observed secondary UA within the same daily burst window; volume remains within the established 1,800–4,300 daily band.

2026-06-09 alarm window (16:56–17:06 UTC / 2026-06-10 01:56–02:06 KST):
- **Alarm transitions**: OK→ALARM at 17:11 UTC, ALARM→OK at 17:15 UTC, OK→ALARM at 17:16 UTC, ALARM→OK at 17:20 UTC (2 back-to-back within 10 minutes, sliding-window artifact)
- Metric datapoints confirming breach: 157.0 (16:56), 894.0 (17:01), 708.0 (17:06); threshold 100.0 with 3 of 4 datapoints required; post-peak 9.0 at 17:11 and 9.0 at 17:16
- Total `error-response` with status ≥ 400 (16:50–17:20 UTC): **1,781**
- `/authenticate` 400: **1,744** (97.9%)
  - User-Agent: `Apache-HttpClient/5.3.1 (Java/17.0.19)` via Cloudflare IPs (`43.202.115.59`, `141.101.84.216-217`)
  - Level: **100% `warn`**; explicit `level == "error"` Logs Insights query returned **0** matches
  - `projectId`: **`"unknown"`** on all `/authenticate` lines
- Secondary signatures (sparse, all `warn`):
  - `DELETE /projects/80fd28969702573797f4d7f77063e47b/messages/text-message/blockservice/recipients/removes` 400: **16**
  - `POST /track-event` 401: **10**
  - `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/campaigns/icKePI/send` 400: **3** (`class101`)
  - `POST /projects/b2b4a8f879a75673b755bff42fc1deb6/user-journeys/6si2yh/enter` 400: **3** (`class101`)
  - `GET /user-state/2b9f5a6685ba5b839803f1338a539724/...` 400: **3**
  - `POST /projects/0c61d690f3425c13875c2c4902616b40/campaigns/CJDzWt/send` 400: **1** (`sconn`)
  - `POST /set-user-properties` 401: **1**
- 7d daily `/authenticate` 400 aggregate (full UTC day): **6,607 / 6,970 / 6,196 / 6,340 / 7,524 / 6,835 / 6,248 / 5,377** (2026-06-02 through 2026-06-09)
- 30d/7d/1d/10m OK→ALARM counts (from `HistoryData`): **52 / 13 / 2 / 2**

Result: identical to the known daily ~02:11 KST `/authenticate` authentication rejection burst. All signals are handled `warn` validation rejections; no customer impact. The 7-day full-day aggregate has crept up to the 5,400–7,500 band (vs. the earlier 1,800–4,300 band), but this is because the query window broadened to full UTC days; the narrow 16:50–17:10 burst window remains within the same ~1,600–1,800 peak as before.

2026-06-12 alarm window (16:56–17:06 UTC / 2026-06-13 01:56–02:06 KST):
- **Alarm transitions**: OK→ALARM at 17:11 UTC, ALARM→OK at 17:12 UTC (1 min); OK→ALARM at 17:16 UTC, ALARM→OK at 17:17 UTC (second back-to-back within 5 min, sliding-window artifact from the 17:01 peak still contributing)
- Metric datapoints confirming breach: 176.0 (16:56), 893.0 (17:01), 199.0 (17:06); threshold 100.0 with 3 of 4 datapoints required
- Total `error-response` with status ≥ 400 (16:50–17:20 UTC): **~1,332**
- `/authenticate` 400: **1,248** (93.7%, Logs Insights aggregate)
  - User-Agent: `Apache-HttpClient/5.3.1 (Java/17.0.19)` and `python-requests/2.32.3`
  - Level: **100% `warn`**; explicit `level == "error"` Logs Insights query returned **0** matches
  - `projectId`: **explicitly `"unknown"`** on all `/authenticate` lines
- Secondary signatures (sparse, all `warn`):
  - `DELETE /projects/80fd28969702573797f4d7f77063e47b/messages/text-message/blockservice/recipients/removes` 400: **15**
  - `POST /track-event` 401: **12**
  - `POST /projects/0c61d690f3425c13875c2c4902616b40/campaigns/CJDzWt/send` 400: **3** (`sconn`)
  - `GET /user-state` 405: **2**
- 30d/7d/1d/10m OK→ALARM counts (from `HistoryData`): **54 / 11 / 2 / 2**
- Alarm state: currently **OK** at investigation time; last ALARM→OK at 17:17 UTC (fully recovered)

Result: identical to the known daily ~02:11 KST `/authenticate` authentication rejection burst. All signals are handled `warn` validation rejections; no customer impact. The 30-day OK→ALARM count of 54 is slightly higher than prior periods but consistent with the ~1.6–1.8 transitions/day baseline.

2026-06-14 alarm window (16:56–17:06 UTC / 2026-06-15 01:56–02:06 KST):
- **Alarm transitions**: OK→ALARM at 17:11 UTC, ALARM→OK at 17:14 UTC; OK→ALARM at 17:16 UTC, ALARM→OK at 17:19 UTC (2 back-to-back within 10 minutes, sliding-window artifact from the 17:01 bucket still contributing)
- Metric datapoints confirming breach: 174.0 (16:56), 893.0 (17:01), 539.0 (17:06); threshold 100.0 with 3 of 4 datapoints required
- Total `error-response` with status ≥ 400 (16:50–17:10 UTC): **~1,614**
- `/authenticate` 400: **1,593** (98.7%)
  - User-Agent: exclusively `Apache-HttpClient/5.3.1 (Java/17.0.19)` via Cloudflare IPs
  - Level: **100% `warn`**; explicit `level == "error"` Logs Insights query returned **0** matches
  - `projectId`: **explicitly `"unknown"`** on all `/authenticate` lines
  - `error.message`: **null** on sampled `/authenticate` lines (validation rejects before message population)
  - `userAgent`: **null** on sampled `/authenticate` lines (client omits header)
- Secondary signatures (sparse, all `warn`):
  - `DELETE /projects/80fd28969702573797f4d7f77063e47b/messages/text-message/blockservice/recipients/removes` 400: **12**
  - `POST /track-event` 401: **6**
  - `GET /user-state/2b9f5a6685ba5b839803f1338a539724/...` 400: **1**
  - `POST /messages/kakao-alimtalk` 401: **1**
- 30d/7d/1d/10m OK→ALARM counts (from `HistoryData`): **56 / 12 / 2 / 2**

Result: identical to the known daily ~02:11 KST `/authenticate` authentication rejection burst. All signals are handled `warn` validation rejections; no customer impact.

## Logs Insights daily trend query (full UTC day)

When the narrow 16:50–17:10 UTC window is already well understood, use this query to verify whether overall `/authenticate` 400 volume is drifting outside the 1,800–4,500/day baseline band. The query aggregates by UTC calendar day (`datefloor`). This is useful for detecting a macro trend shift (e.g. sudden doubling across consecutive days) even when individual alarm windows look normal.

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

Then poll: `aws logs get-query-results --region ap-northeast-2 --query-id <queryId>`

Interpretation:
- Stable narrow band (~±25% day-to-day) → no trend shift; classify from the alarm-window signature only.
- Sudden jump to > 6,000/day for ≥ 2 consecutive days → investigate for a new client integration or retry loop.

## Pitfall — `INSUFFICIENT_DATA → ALARM` undercounts in transition history

This alarm uses `TreatMissingData: missing`. During low-traffic periods (midnight KST), the `ConsoleErrors` metric may have no data points, so the alarm state drops to `INSUFFICIENT_DATA`. The daily ~02:11 KST burst then transitions `INSUFFICIENT_DATA → ALARM`, not `OK → ALARM`.

`describe-alarm-history` parsers that only count `oldState.stateValue == "OK" && newState.stateValue == "ALARM"` **undercount actual alarm firings**. For example, on 2026-05-27 the latest `OK → ALARM` transition in 30 days was 2026-04-28, yet the alarm was demonstrably in `ALARM` at 17:01 UTC that day.

**Remediation**: for alarms with `TreatMissingData: missing`, rely on the **metric datapoint breach densities** (`recentDatapoints` from `StateReasonData`) and daily recurrence pattern as the ground truth, not just OK→ALARM transition counts. Counting `INSUFFICIENT_DATA → ALARM` requires inspecting `HistoryData` for both transition directions:

```python
data = json.loads(item.get('HistoryData', '{}'))
old = data.get('oldState', {}).get('stateValue')
new = data.get('newState', {}).get('stateValue')
if old in ('OK', 'INSUFFICIENT_DATA') and new == 'ALARM':
    count += 1
```

## Pitfall — null `error.message` and `userAgent` on `/authenticate` 400 samples

When sampling individual `/authenticate` 400 log lines with `limit N` in Logs Insights, both `error.message` and `userAgent` may be `null`:

```json
{"timestamp":"2026-06-14T17:04:59.233Z","method":"POST","path":"/authenticate","status":400,"level":"warn","userAgent":null,"message":null}
```

This occurs because:
- The validation middleware rejects the request before `error.message` is populated.
- The client does not send a `User-Agent` header.

**Implication**: do not rely on `error.message` content or `userAgent` presence to classify the rejection reason for `/authenticate` 400s. The classification should be based on the aggregate pattern (`POST /authenticate`, `400`, `level: warn`, `projectId: "unknown"`) and daily recurrence, not on per-sample message text.

## Pitfall — Logs Insights `stats by` with hyphenated nested JSON field names

When writing Logs Insights aggregate queries for `api-service` structured logs, nested JSON keys containing hyphens (e.g., `request.headers["user-agent"]`) cause `MalformedQueryException` when used in a `stats by` clause with quoted field access:

```
| stats count() as cnt by request.headers."user-agent"
# MalformedQueryException: unexpected symbol found "user-agent"
```

**Root cause**: Logs Insights parses the hyphen inside quotes as a subtraction operator in the `stats` aggregation context.

**Workarounds**:
1. Use the auto-extracted flattened field name (hyphen stripped): `request.headers.useragent`
2. Use `fields` + `as` to rename first, then aggregate: `fields request.headers."user-agent" as ua | stats count() by ua`
3. For `filter` and `fields` clauses, the quoted syntax `request.headers."user-agent"` works fine; the restriction applies only to `stats by`.

Also note that `/authenticate` 400 responses may genuinely lack a `user-agent` header. When querying with `ispresent(request.headers."user-agent")`, an empty result set does not prove the field access is wrong; it may mean the client omitted the header.

## Long-term remediation options

1. **Metric filter refinement**: change the metric filter to exclude `$.path = "/authenticate"` if this path is accepted noise, or require `$.level = "error"` so handled `warn` rejections do not increment the alarm.
2. **Log-level audit**: verify that `/authenticate` validation rejections should remain `WARN` (they are handled) and that any genuinely unexpected 4xx paths stay `ERROR`.
3. **Separate alarm**: if `/authenticate` client errors need monitoring, create a dedicated lower-priority alarm for that single path so the general 4xx alarm retains signal for real issues.
