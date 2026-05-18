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
- `GET /user-state/{pid}/{uid}` → `"projectId ... does not exist"` (invalid/stale project ID from mobile SDK)
- `POST /track-event` → `401` (`"Invalid Authorization Token"`)

These are handled service responses, not unhandled exceptions or data-loss events.

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

## Pitfall — log ingestion lag hides current trigger

The `api-service` log group receives very high traffic. During a spike, CloudWatch Logs indexing can lag behind the metric-filter evaluation, so `filter-log_events` may return zero results even when the metric has demonstrably breached. If this happens during triage, do not conclude no logs exist. Instead, verify the exact 5-minute `Sum` datapoints via `get_metric_statistics` on the `ConsoleErrors` metric (`/aws/ecs/notifly-services-prod/api-service 4xx error`) for the alarm window, and compare the daily recurrence pattern for 16:50–17:20 UTC. The metric is the ground truth; empty log search is a lag artifact for this high-volume service.

## Classification guidance

- **`no_action`** (default): when the alarm-window breakdown shows ≥ 90 % `/authenticate` 400 from `Apache-HttpClient/5.3.1 (Java/17.0.19)` with `"Missing required fields"`, and the logs are `level: warn`. No customer-facing impact; the `api-service` is correctly rejecting malformed auth requests. Use this even when `filter-log_events` returns empty because the daily recurrence and metric datapoints alone are sufficient evidence.
- **`needs_fix`**: only if `/authenticate` is not the dominant signature, if a new non-authenticate 4xx path spikes outside the weekday 17:00 UTC window, or if the `level` field shows `error` rather than `warn` indicating an unhandled exception path.

## Long-term remediation options

1. **Metric filter refinement**: change the metric filter to exclude `$.path = "/authenticate"` if this path is accepted noise, or require `$.level = "error"` so handled `warn` rejections do not increment the alarm.
2. **Log-level audit**: verify that `/authenticate` validation rejections should remain `WARN` (they are handled) and that any genuinely unexpected 4xx paths stay `ERROR`.
3. **Separate alarm**: if `/authenticate` client errors need monitoring, create a dedicated lower-priority alarm for that single path so the general 4xx alarm retains signal for real issues.
