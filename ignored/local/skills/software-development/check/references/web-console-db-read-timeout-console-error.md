# web-console DB Read Timeout → Console Error False Positive

Pattern where a `Query read timeout` on a large sharded `delivery_result_<project_id>` table is logged as `Error: ...` by the `pg` driver in web-console, tripping the coarse `%ERROR|Exception%` metric filter.

## Alarm manifestation

- **Alarm name**: `/aws/ecs/notifly-services-prod/web-console console error`
- **Namespace**: `ConsoleErrors`
- **Metric filter**: `%ERROR|Exception%`
- **Current trigger log signature** (from `get_log_events` on the active stream):
  ```
  Error: select "campaign_id", event_name AS metric_name, TO_CHAR(DATE_TRUNC('hour', created_at), 'YYYY-MM-DD_HH24') AS collected_from, TO_CHAR(DATE_TRUNC('hour', created_at) + interval '1 hour', 'YYYY-MM-DD_HH24') AS collected_to, COUNT(*) AS count from "delivery_result_<project_id>" where "campaign_id" = $1 and "created_at" >= $2 and "created_at" <= $3 group by "campaign_id", "event_name", DATE_TRUNC('hour', created_at) - Query read timeout
      at Timeout._onTimeout (/app/node_modules/.pnpm/pg@8.11.3/node_modules/pg/lib/client.js:536:21)
      at listOnTimeout (node:internal/timers:585:17)
      at process.processTimers (node:internal/timers:521:7)
  ```
- **SQL fingerprint**: `SELECT campaign_id, event_name, COUNT(*) FROM delivery_result_<project_id> WHERE campaign_id = $1 AND created_at >= $2 AND created_at <= $3 GROUP BY campaign_id, event_name, DATE_TRUNC('hour', created_at)`

## Classification

This is **not** a web-console code bug. It is a read-replica query timeout on an oversized sharded delivery result table, surfaced through the `pg` driver as an `Error` log. The console user sees a slow/failed campaign statistics request, but there is no service-side unhandled exception.

## Triage flow

### 1. Recover the trigger log when current_trigger_contexts is empty

As with other ECS console-error alarms, the helper may fail to find the current trigger because the log stream is still active or ingestion is delayed. Use `get_log_events` on the most recent stream instead:

```bash
aws logs describe-log-streams \
  --region ap-northeast-2 \
  --log-group-name '/aws/ecs/notifly-services-prod/web-console' \
  --order-by LastEventTime --descending --limit 5 \
  --output json | jq '.logStreams[] | {logStreamName, lastEventTimestamp: (.lastEventTimestamp / 1000 | todate)}'
```

Then read recent events and grep for `Error:` inside the alarm window:

```bash
start_ms=$(date -d '<alarm_start>' +%s)000
end_ms=$(date -d '<alarm_end>' +%s)000
aws logs get-log-events \
  --region ap-northeast-2 \
  --log-group-name '/aws/ecs/notifly-services-prod/web-console' \
  --log-stream-name '<most_recent_stream>' \
  --start-time "$start_ms" --end-time "$end_ms" --limit 200 \
  --output json | jq '.events[] | select(.message | test("Error:"; "i")) | {timestamp: (.timestamp / 1000 | todate), message: .message}'
```

### 2. Identify the table and project

Extract `delivery_result_<project_id>` from the error message, then map via DynamoDB `project`:

```bash
python3 - <<'PY'
import boto3, json
ddb = boto3.resource('dynamodb', region_name='ap-northeast-2')
project_id = '<project_id>'
item = ddb.Table('project').get_item(Key={'id': project_id}, ProjectionExpression='id, product_id, #n', ExpressionAttributeNames={'#n': 'name'}).get('Item')
print(json.dumps(item, ensure_ascii=False))
PY
```

### 3. Check table size and indexes

```bash
PGPASSWORD="$POS...RD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "
SELECT pg_size_pretty(pg_total_relation_size('delivery_result_<project_id>'));
"
```

```bash
PGPASSWORD="$POS...RD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "
SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'delivery_result_<project_id>' ORDER BY indexname;
"
```

If the table is large (e.g. 50+ GB) and the composite index on `(campaign_id, created_at, event_name)` is missing, the aggregation query will repeatedly time out on the reader.

### 4. Assess recurrence

Run a bounded Logs Insights query for `Query read timeout` in the web-console log group over the last 7 days:

```bash
python3 - <<'PY'
import boto3, json, time
from datetime import datetime, timedelta
logs = boto3.client('logs', region_name='ap-northeast-2')
query = 'fields @timestamp, @message\n| filter @message like \"Query read timeout\"\n| limit 100'
resp = logs.start_query(logGroupNames=['/aws/ecs/notifly-services-prod/web-console'],
    startTime=int((datetime.utcnow() - timedelta(days=7)).timestamp()),
    endTime=int(datetime.utcnow().timestamp()), queryString=query)
query_id = resp['queryId']
for _ in range(10):
    time.sleep(2)
    results = logs.get_query_results(queryId=query_id)
    if results['status'] != 'Running': break
for r in results.get('results', []):
    print(json.dumps({f['field']: f['value'] for f in r}, ensure_ascii=False))
PY
```

- 7일 내 3–4회 이상 반복되고 동일 프로젝트/테이블로 집중되면 추적 대상.
- 일회성 또는 여러 프로젝트에 무작위로 분산되면 Aurora reader 일시 부하로 분류.

## Scope attribution

- **Project**: known via `<project_id>` extracted from `delivery_result_<project_id>`.
- **Campaign**: usually unknown because the timeout log does not include the actual `campaign_id` parameter value; only `$1` placeholder appears.
- If access logs around the same stream show `POST /api/projects/<project_id>/campaigns/click_counts` or similar, the campaign list/statistics endpoint was the user-facing trigger.

## Classification guidance

| Pattern | Condition | Status | Rationale |
|---|---|---|---|
| **Single/random occurrence** | One timeout in 7 days, no concentrated recurrence | `no_action` | Aurora reader transient pressure or single heavy query. User may retry and succeed. |
| **Repeating on same table** | 3+ timeouts in 7 days on the same `delivery_result_<project_id>` | `needs_fix` | Missing composite index or oversized shard causing persistent query failure. Impacts console UX for that project. |
| **Mixed with other ERRORs** | The alarm window also contains unhandled exceptions, provider errors, or other failures | `needs_fix` | Do not dismiss the whole alarm as DB timeout noise; classify by the dominant pattern or provide separate counts. |

## Distinction from other web-console ERROR patterns

- **External provider error** (`FailedToUploadImageException`, `InvalidImageFormatException`, `maximum number of registered templates`) — handled business rejections, code path ends normally. See `references/web-console-kakao-image-upload-validation-error.md`.
- **LiquidJS `abort_message()`** — intentional template abort, logged as `RenderError`. See `references/web-console-liquidjs-abort-message-false-positive.md`.
- **get_url 403** — benign external link check failure. See `references/web-console-get-url-http-403-false-positive.md`.
- **Sentry pipeline** — intentional ERROR-level proxy, not a service bug. See `references/sentry-email-alert-pipeline-false-positives.md`.
- **This pattern** — infrastructure-level DB read timeout surfaced through driver ERROR logging. The query itself is legitimate but the table/index shape makes it too slow for the reader timeout.

## Action items when `needs_fix`

1. **Index audit** — Add `CREATE INDEX ... ON delivery_result_<project_id> (campaign_id, created_at, event_name)` if missing.
2. **Query review** — Check whether the campaign statistics aggregation needs `DATE_TRUNC('hour', created_at)` grouping or if a pre-aggregated/cache layer can reduce reader load.
3. **Log-level audit** — Consider wrapping the `pg` query timeout in a custom logger that emits `WARN` instead of `Error` for known read-timeouts, so the coarse `%ERROR|Exception%` metric filter does not page on infrastructure hiccups.
