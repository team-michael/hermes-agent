# cafe24-worker Queue DLQ Pattern

Session-specific reference for `cafe24-worker-queue-dlq` alarms and related investigations.

## Alarm type

CloudWatch alarm name: `cafe24-worker-queue-dlq has been created` (or `ApproximateNumberOfMessagesVisible >= 1` on the DLQ).

## Consumer mechanics

- **Consumer:** `cafe24-worker` Lambda
- **Event source:** SQS `cafe24-worker-queue`
- **Partial batch response:** `ReportBatchItemFailures` enabled
- **Redrive:** `maxReceiveCount=6` (higher than typical Notifly default of 1)

Because the Lambda returns partial batch failures rather than failing the whole invocation, `AWS/Lambda Errors` stays 0 even while individual messages are retried and eventually DLQed.

## Typical trigger: Cafe24 API rate limit

When a specific `mallId` hits Cafe24 API rate limits (HTTP 429), the worker:
1. Logs the rate limit.
2. Sets a Redis backoff key via `lib/redis-rate-limiter.js`.
3. Returns the failed message in `batchItemFailures`.
4. SQS re-queues it for retry.

If a mall remains rate-limited across several receives, or a redrive/traffic burst causes many same-mall messages to run in parallel, messages can exhaust `maxReceiveCount` and land in DLQ despite correct Lambda runtime behavior. This can happen even when the nominal `VisibilityTimeout × maxReceiveCount` window is longer than one 600-second Cafe24 block, because each premature same-mall call can extend the effective backoff window.

### Key log signature

```
[Cafe24 RedisRateLimiter] Backoff set for <mallId>: <ttl>s
```

- `ttl` is not always 600s; some paths back off for 30s per retry while still exhausting the SQS retry budget.
- The most useful scope cue is the mall-specific backoff line, not the numeric TTL alone.

### Observed 2026-07-01 pattern (inertia22 burst)

- `cafe24-worker` Lambda function name matches the worker queue consumer directly.
- Event source mapping: `BatchSize=5`, `MaximumConcurrency=16`, `FunctionResponseTypes=[ReportBatchItemFailures]`.
- Queue settings: `cafe24-worker-queue` has `maxReceiveCount=6` and `VisibilityTimeout=900`.
- Lambda deployed at 05:34 UTC (previous deploy: 2026-03-18, 3.5-month gap). DLQ started filling at 06:20 UTC.
- Burst: `mallId=inertia22`, 17,147 rate-limited events today vs ~80/day 30d average (200x baseline).
- DLQ received 1201 messages at 06:50 UTC, 787 at 08:30 UTC, then stabilized at 385 by 10:05 UTC.
- Lambda runtime `Errors=0` and `Throttles=0`; Duration spikes ~35s (= 30s rate-limit retry wait + API call).
- Main queue depth=0 throughout (draining normally); only DLQ accumulated.
- All DLQ messages were `inertia22` mall, `points_updated` / `shipping_status_batch_changed` commands.
- In this pattern, Lambda runtime `Errors=0` and `Throttles=0` are expected; the decisive signal is sustained backoff + DLQ growth for one mall.

### Key diagnostic metrics for DLQ burst triage

1. **DLQ `NumberOfMessagesReceived`** (not `Sent`): SQS redrive (main→DLQ) shows as `Received` on the DLQ side. `Sent` on the DLQ is for producer-sent messages, not redriven ones. Use this to track when batches of messages were redrived:
   ```python
   cw.get_metric_statistics(
     Namespace='AWS/SQS', MetricName='NumberOfMessagesReceived',
     Dimensions=[{'Name':'QueueName','Value':'cafe24-worker-queue-dlq'}],
     StartTime=..., EndTime=..., Period=300, Statistics=['Sum'])
   ```

2. **Rate-limited daily count comparison**: Use Logs Insights `filter @message like "rate-limited" | stats count(*) by datefloor(@timestamp, 1d)` to compare today's count against 30d baseline. A 200x spike (17,147 vs ~80/day) confirms an anomaly, not baseline noise.

3. **DLQ stabilization check**: If DLQ depth stops growing (flat for 30+ minutes), the burst has passed. The remaining messages need redrive decision, not urgent escalation.

### Pitfall: SQS `get_queue_attributes` attribute name

`sqs.get_queue_attributes` uses `ApproximateNumberOfMessages`, **not** `ApproximateNumberOfMessagesVisible`. The latter throws `InvalidAttributeName`. This differs from the CloudWatch metric name which is `ApproximateNumberOfMessagesVisible`.

### Pitfall: CloudWatch `filter_log_events` hyphen in filterPattern

`filterPattern="rate-limited"` returns 0 results because CloudWatch filter syntax treats hyphens as special characters. Use one of:
- `filterPattern="WARN"` (broader, then filter in code)
- `filterPattern="rate"` (matches both "rate-limited" and "rate limited")
- Logs Insights: `filter @message like "rate-limited"` (handles hyphens correctly)

### Pitfall: mall_id → project mapping via DynamoDB `project` table

The existing scope attribution step mentions a `cafe24_integration` table, but the primary mapping path is through the `project` table's `cafe24_info` attribute (DynamoDB Map type with `mall_id` field):
```python
r = dynamodb.get_item(TableName='project',
  Key={'id':{'S':project_id}},
  ProjectionExpression='cafe24_info')
mall_id = r['Item']['cafe24_info']['M']['mall_id']['S']
```
To reverse-map (mall_id → project_id), scan `project` table and match `cafe24_info.mall_id`. Multiple project items may share the same `name` (e.g., dev and prod variants); filter by `dev=false` for production scope.

### Bounded trace: extract backoff events and mall counts

```bash
python - <<'PY'
import boto3, os, json, datetime, re, collections
session=boto3.Session(
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    aws_session_token=os.environ.get('AWS_SESSION_TOKEN'),
    region_name=os.environ.get('AWS_DEFAULT_REGION','ap-northeast-2'),
)
logs=session.client('logs')

# adjust window to alarm datapoint time
start_ms=int(datetime.datetime(2026,6,2,20,0,tzinfo=datetime.timezone.utc).timestamp()*1000)
end_ms=int(datetime.datetime(2026,6,2,22,0,tzinfo=datetime.timezone.utc).timestamp()*1000)

kwargs=dict(
    logGroupName='/aws/lambda/cafe24-worker',
    startTime=start_ms,
    endTime=end_ms,
    filterPattern='"Backoff set for"'
)
events=[]
while True:
    resp=logs.filter_log_events(**kwargs)
    events.extend(resp.get('events', []))
    token=resp.get('nextToken')
    if not token or token==kwargs.get('nextToken'):
        break
    kwargs['nextToken']=token

backoff_re=re.compile(r'Backoff set for ([^:]+): (\d+)s')
by_mall=collections.Counter()
max_ttl=0
for e in events:
    m=backoff_re.search(e['message'])
    if m:
        mall=m.group(1)
        ttl=int(m.group(2))
        by_mall[mall]+=1
        if ttl>max_ttl:
            max_ttl=ttl
print(json.dumps({'max_ttl_s': max_ttl, 'by_mall': by_mall.most_common()}, ensure_ascii=False, indent=2))
PY
```

**Interpretation:**
- High `by_mall` count for a single mall → that mall is persistently rate-limited.
- `max_ttl >= 600` → Redis backoff is set to the typical Cafe24 rate-limit window.
- If backoff logs cluster within the alarm window, the DLQ entries are likely from that same rate-limit episode.

### Bounded trace: batchItemFailures evidence

Search for partial batch failure responses in the Lambda end log:

```bash
aws logs filter-log-events --region ap-northeast-2 \
  --log-group-name /aws/lambda/cafe24-worker \
  --start-time <alarm_start_epoch_ms> --end-time <alarm_end_epoch_ms> \
  --filter-pattern '"batchItemFailures"'
```

If `batchItemFailures` appears repeatedly with message IDs while `Errors=0`, this confirms the `ReportBatchItemFailures` retry exhaustion pattern.

## Scope attribution

1. **From DLQ body:**
   ```bash
   aws sqs receive-message --queue-url https://sqs.ap-northeast-2.amazonaws.com/702197142747/cafe24-worker-queue-dlq \
     --max-number-of-messages 10 --visibility-timeout 5 --region ap-northeast-2
   ```
   Extract `mall_id` and `command` from `Body` JSON.

2. **Map mall to project:**
   There are two mapping paths:
   - **Primary (project table):** The `project` DynamoDB table has a `cafe24_info` attribute (Map type) containing `mall_id`. Scan `project` table and match `cafe24_info.mall_id` to the DLQ body's `mall_id`. Filter by `dev=false` for production scope.
     ```bash
     aws dynamodb get-item --table-name project \
       --key '{"id":{"S":"<project_id>"}}' \
       --projection-expression 'cafe24_info' --region ap-northeast-2
     # cafe24_info is a Map: {"M":{"mall_id":{"S":"inertia22"}}}
     ```
   - **Alternative (cafe24_integration table):** If the project table approach fails, try:
     ```bash
     aws dynamodb get-item --table-name cafe24_integration \
       --key '{"mall_id":{"S":"chosunhnb"}}' \
       --projection-expression 'mall_id, project_id' --region ap-northeast-2
     ```
   Then map `project_id` via DynamoDB `project` table.
   Note: Multiple project items may share the same `name` (e.g., dev and prod variants of "inertia"); always filter by `dev=false` for production scope.

3. **From Lambda logs:** If DLQ is empty, use the `[Cafe24 RedisRateLimiter] Backoff set for <mallId>` signature to identify the affected mall.

## Classification

| Signal | Classification | Reason |
|---|---|---|
| Lambda Errors=0, Throttles=0; backoff logs show known rate limit; DLQ count low and stable | `no_action` | Transient Cafe24 429 handled correctly; message will be processed after rate-limit window |
| Same mall repeatedly rate-limited over hours; DLQ growing; backoff TTL consistently 600s | `needs_fix` | Structural mismatch between Cafe24 quota window and SQS retry budget |
| Single-mall burst with 200x baseline rate-limited count; DLQ stabilizes after initial burst; Lambda deployed same day | `needs_fix` | Anomaly triggered by event burst (possibly deployment-correlated); DLQ needs redrive decision but not urgent escalation |
| Lambda Errors > 0 or timeout logs present | `needs_fix` or `urgent` | Real Lambda failure, not just rate-limit exhaustion |

## Selective redrive workflow

- Inspect DLQ bodies first and group by `mall_id`.
- **Preferred method**: `sqs.start_message_move_task` (server-side, single API call, no visibility changes). Use it when all DLQ messages are safe to redrive — i.e. single-mall DLQ, or all malls' backoff windows have expired. See `references/cafe24-worker-dlq-selective-redrive.md` for the full recipe including pre-redrive safety checks and post-redrive verification.
- **Manual selective** (mixed malls, some still rate-limited): receive/delete individual cohorts by `mall_id` so healthy malls don't churn back into DLQ. Keep the cohort separate.
- Do not mix multiple malls into one blind replay pass if one mall is still rate-limited.
- After redrive, verify both queue depths. DLQ should drain; source queue may briefly show a large in-flight count while replay is consumed.
- If the latest `Backoff set for <mallId>: 600s` is still within the active window, leave that mall in DLQ until it expires.

See `references/cafe24-worker-dlq-selective-redrive.md` for the session-derived redrive recipe.

## Fix targets

Preferred fix: do **not** auto-redrive the DLQ. Prevent Cafe24 429 messages from reaching DLQ by delayed self-requeueing in the source queue. See `references/cafe24-worker-rate-limit-auto-delay-requeue.md` for the implementation sketch and tests.

- `services/lambda/cafe24-worker/index.js` — on `Cafe24RateLimitError`, send the original body back to `cafe24-worker-queue` with `DelaySeconds` based on Redis/Cafe24 backoff, then omit the original from `batchItemFailures` if requeue succeeds.
- `services/lambda/cafe24-worker/lib/api/index.js` — make `Cafe24RateLimitError.retryAfterMs` reflect the effective Redis/Cafe24 backoff, not only a short fallback header value.
- `services/lambda/cafe24-worker/lib/redis-rate-limiter.js` — reuse `getBackoffRemainingMs(mallId)` for safe delay calculation; later add Redis token-bucket/lease if same-mall concurrency keeps extending the block.
- `services/lambda/cafe24-worker/lib/jobs/users.js` — consider collapsing multiple `points_updated` events for the same `(mallId, memberId)` before calling `getCustomer()`.
- `infra/terraform/prod/ap-northeast-2/lambda/functions.tf` — if needed, add `CAFE24_WORKER_QUEUE_URL`; current prod inventory already grants `sqs:SendMessage` in `cafe24-worker-inline`, but verify in PR.
- `infra/terraform/prod/ap-northeast-2/sqs/queues.tf` — raise `cafe24-worker-queue` `maxReceiveCount` only as a safety net; it does not solve same-mall Cafe24 quota pressure by itself.

## Pitfalls

- Do not assume `maxReceiveCount=6` prevents DLQ for persistent failures. Six retries can be exhausted in ~6 × `VisibilityTimeout` minutes, which may be shorter than a 600-second rate-limit window.
- `AWS/Lambda Errors=0` is expected with `ReportBatchItemFailures`. Do not conclude "healthy Lambda = no real problem" without checking whether the DLQ contents are from persistent external dependency failures.
- The DLQ body shape is a raw SQS payload with `mall_id`, `command`, `params`; not a Kinesis dispatch record. Do not search for `records[].data` fields.
- **`filter_log_events` hyphen pitfall**: `filterPattern="rate-limited"` returns 0 results. CloudWatch filter syntax treats hyphens as special characters. Use `filterPattern="WARN"` or `filterPattern="rate"` instead, or use Logs Insights `filter @message like "rate-limited"` which handles hyphens correctly.
- **SQS attribute name pitfall**: `get_queue_attributes` uses `ApproximateNumberOfMessages`, not `ApproximateNumberOfMessagesVisible`. The latter throws `InvalidAttributeName`.
- **DLQ creation alarm stays in ALARM**: The alarm threshold is `>= 1` on `ApproximateNumberOfMessagesVisible`. It will not auto-resolve to OK until the DLQ is drained or purged. Check `NumberOfMessagesReceived` on the DLQ to confirm the burst has stopped before deciding on redrive.
- **Deployment correlation**: When the Lambda `LastModified` is within hours of the DLQ burst onset, investigate whether the deployment changed rate-limit handling or event processing behavior. Compare rate-limited event counts before and after the deploy.
