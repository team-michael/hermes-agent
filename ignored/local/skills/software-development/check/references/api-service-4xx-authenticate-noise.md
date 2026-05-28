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
- **State transition history**: ~47 OK→ALARM transitions in 30 days (2026-04-26 through 2026-05-25), typically 2 transitions per day resolving within 3–5 minutes. Some days produce back-to-back transitions within 5 minutes when a high-volume 5-minute bucket continues contributing to the rolling evaluation after a brief OK recovery. Always derive from actual `describe-alarm-history` output using `HistoryData | fromjson | .oldState.stateValue` / `.newState.stateValue` rather than the `StateValue` field, which can be `null` for older entries.

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

- **User-Agent**: primarily `Apache-HttpClient/5.3.1 (Java/17.0.19)`; also `python-requests/2.32.3`, `axios/1.13.6`
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

## Long-term remediation options

1. **Metric filter refinement**: change the metric filter to exclude `$.path = "/authenticate"` if this path is accepted noise, or require `$.level = "error"` so handled `warn` rejections do not increment the alarm.
2. **Log-level audit**: verify that `/authenticate` validation rejections should remain `WARN` (they are handled) and that any genuinely unexpected 4xx paths stay `ERROR`.
3. **Separate alarm**: if `/authenticate` client errors need monitoring, create a dedicated lower-priority alarm for that single path so the general 4xx alarm retains signal for real issues.
