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
- **State transition history**: ~44 OK→ALARM transitions in 30 days, typically resolving within 3–5 minutes.

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

On weekdays around **17:00 UTC (KST 02:00)**, a burst of requests hits `POST /authenticate`:

- **User-Agent**: `Apache-HttpClient/5.3.1 (Java/17.0.19)`
- **Status**: `400`
- **Response body**: `{"error":"Missing required fields"}`
- **IP origin**: various Korean IPs behind Cloudflare
- **Volume**: typically 500–1000 events in a 10-minute window, enough to breach `Sum > 100` across 3 consecutive 5-minute periods.

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
| Weekday ~02:11 KST (17:11 UTC) | ~980 | ~1000 |
| Weekend 16:50–17:10 UTC | ~1–5 | ~500–600 (other sources) |
| Daily total (metric Sum) | — | ~3900–5300 |

The weekday **~02:11 KST** spike is a clockwork pattern with tight timing (±2 minutes). If the alarm fires outside this window, investigate the dominant signature immediately; it may be a different root cause.

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

Check weekday vs weekend auth volume for the last N days:

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

Result: consistent with the known weekday **~02:11 KST** `Apache-HttpClient/5.3.1 (Java/17.0.19)` authentication rejection burst.

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

Result: consistent with the known weekday **~02:11 KST** `Apache-HttpClient/5.3.1 (Java/17.0.19)` authentication rejection burst.

## Logs Insights query note — `parse` field collision

When writing manual aggregate queries for `api-service` `error-response` logs, prefer auto-extracted JSON fields (`status`, `message`) directly. Do not add `parse @message '\"status\":*' as status` because `status` is already a top-level JSON field; this raises `MalformedQueryException: Ephemeral field is already defined: status`. Use the auto-extracted field directly, or rename the parsed alias (e.g., `as parsed_status`) when extraction is required.

## Pitfall — log ingestion lag hides current trigger

The `api-service` log group receives very high traffic. During a spike, CloudWatch Logs indexing can lag behind the metric-filter evaluation, so `filter-log_events` may return zero results even when the metric has demonstrably breached. If this happens during triage, do not conclude no logs exist. Instead, verify the exact 5-minute `Sum` datapoints via `get_metric_statistics` on the `ConsoleErrors` metric (`/aws/ecs/notifly-services-prod/api-service 4xx error`) for the alarm window, and compare the daily recurrence pattern for 16:50–17:20 UTC. The metric is the ground truth; empty log search is a lag artifact for this high-volume service.

## Classification guidance

- **`no_action`** (default): when the alarm-window breakdown shows ≥ 90 % volume from a known false-positive signature and all logs are `level: warn`. This covers:
  - `/authenticate` 400 from `Apache-HttpClient/5.3.1 (Java/17.0.19)` with `"Missing required fields"`
  - `POST /projects/{pid}/campaigns/{cid}/send` 400 with `"Bad request: campaign <id> does not exist"` from a single client IP
  Use this even when `filter-log_events` returns empty because the daily recurrence and metric datapoints alone are sufficient evidence.
- **`needs_fix`**: only if the dominant signature is outside the known false-positive families, if a new non-authenticate 4xx path spikes outside the weekday 17:00 UTC window, or if the `level` field shows `error` rather than `warn` indicating an unhandled exception path.

## Long-term remediation options

1. **Metric filter refinement**: change the metric filter to exclude `$.path = "/authenticate"` if this path is accepted noise, or require `$.level = "error"` so handled `warn` rejections do not increment the alarm.
2. **Log-level audit**: verify that `/authenticate` validation rejections should remain `WARN` (they are handled) and that any genuinely unexpected 4xx paths stay `ERROR`.
3. **Separate alarm**: if `/authenticate` client errors need monitoring, create a dedicated lower-priority alarm for that single path so the general 4xx alarm retains signal for real issues.
