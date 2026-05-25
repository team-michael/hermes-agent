# Kinesis Record Dispatcher Queue — ApproximateAgeOfOldestMessage Throughput Bottleneck

## Alarm shape

- Alarm name: `kinesis-record-dispatcher-queue too high approximate age` (Terraform-generated)
- Metric: `AWS/SQS` `ApproximateAgeOfOldestMessage`
- Queue: `kinesis-record-dispatcher-queue` (FIFO)
- DLQ: `kinesis-record-dispatcher-queue-dlq`
- Consumer: `kinesis-record-dispatcher` Lambda
- Producer: `segment-publisher` ECS service via `@notifly/kinesis` library

## Architecture

`@notifly/kinesis` does **not** write directly to Kinesis Streams. Instead it:
1. Batches kinesis records into SQS messages (`SQS_BATCH_SIZE=100`, ~100 records per message)
2. Sends to `kinesis-record-dispatcher-queue`
3. `kinesis-record-dispatcher` Lambda polls SQS and forwards to the actual `notifly-triggering-events-stream` Kinesis stream

Burst traffic from large scheduled batch campaigns causes the SQS queue to backlog temporarily. Because `segment-publisher` publishes triggering events for all recipients at once, a 1.3M-recipient campaign produces ~13,000 SQS messages within seconds.

## Known recurrence time slots (KST)

These are stable daily/weekly scheduled batch windows that correlate with queue-age spikes:

| Time slot | Typical projects (product_id) | Typical campaigns | Approx. recipients |
|---|---|---|---|
| ~08:15 KST | `regather` (teamremited.com) | `TOPccv` — "출석 알림신청자 데일리 푸시 1차(오전)" | ~485,000 |
| ~08:15 KST | `qmarket` (aswemake.com) | `KcqDMg` — "출석체크_푸시_오전" | ~105,000 |
| ~10:08 KST | `lookpin` (lookpin.co.kr) | rotating daily (e.g. `3TeBy8` — "md_260522_01_29669") | ~500,000–1,300,000 |
| ~10:08 KST | `okpos` (okpos.co.kr) | rotating (e.g. `I3MFZT`) | ~430,000 |
| ~10:08 KST | `sazo-kr` (sazo.shop) | rotating (e.g. `RpU2cJ`) | ~65,000–70,000 |

Campaigns rotate daily; use the segment-publisher ECS log stream around the alarm window to identify the current day's campaign IDs.

> **Note:** Bursts are not limited to these morning slots. Segment-publisher scheduled campaigns (including those with `0 recipients published`) can trigger queue-age spikes at any time of day. Always check ECS `segment-publisher` logs for `recipients published` around the alarm window rather than relying solely on the table above.

## Bounded trace commands

### 1. Queue + consumer baseline

```bash
# Queue attributes and redrive policy
aws sqs get-queue-attributes \
  --region ap-northeast-2 \
  --queue-url 'https://sqs.ap-northeast-2.amazonaws.com/702197142747/kinesis-record-dispatcher-queue' \
  --attribute-names All

# Lambda event source mapping
aws lambda list-event-source-mappings \
  --region ap-northeast-2 \
  --function-name kinesis-record-dispatcher

# Lambda config (BatchSize, MaximumConcurrency, VisibilityTimeout)
aws lambda get-function-configuration \
  --region ap-northeast-2 \
  --function-name kinesis-record-dispatcher
```

### 2. Confirm throughput bottleneck (not code failure)

```bash
# Lambda healthy signals → structural throughput issue
aws cloudwatch get-metric-statistics \
  --region ap-northeast-2 \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=kinesis-record-dispatcher \
  --statistics Sum \
  --period 60 \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ)

aws cloudwatch get-metric-statistics \
  --region ap-northeast-2 \
  --namespace AWS/Lambda \
  --metric-name Throttles \
  --dimensions Name=FunctionName,Value=kinesis-record-dispatcher \
  --statistics Sum \
  --period 60 \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ)

# Compare Sent vs Deleted: near-parity on average means spike, not sustained overload
aws cloudwatch get-metric-statistics \
  --region ap-northeast-2 \
  --namespace AWS/SQS \
  --metric-name NumberOfMessagesSent \
  --dimensions Name=QueueName,Value=kinesis-record-dispatcher-queue \
  --statistics Sum \
  --period 300 \
  --start-time $(date -u -d '3 hours ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ)

aws cloudwatch get-metric-statistics \
  --region ap-northeast-2 \
  --namespace AWS/SQS \
  --metric-name NumberOfMessagesDeleted \
  --dimensions Name=QueueName,Value=kinesis-record-dispatcher-queue \
  --statistics Sum \
  --period 300 \
  --start-time $(date -u -d '3 hours ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ)
```

### 3. Scope attribution: find the triggering campaign

```bash
# Segment-publisher ECS logs around the alarm window (adjust timestamp)
aws logs filter-log-events \
  --region ap-northeast-2 \
  --log-group-name /aws/ecs/notifly-services-prod/segment-publisher \
  --start-time 1747887600000 \
  --end-time 1747891200000 \
  --filter-pattern 'recipients published' \
  --max-items 20
```

Look for lines like:
```
[INFO] <project_id>-<campaign_id> Total recipients published: <count>
[INFO] Start extracting project segment for project <project_id>, campaign <campaign_id>
```

Map `project_id` via DynamoDB `project` table to get `product_id` and `name`.

Alternative via Athena when ECS logs are noisy or expired:
```sql
SELECT
  project_id,
  campaign_id,
  COUNT(*) as event_count,
  MAX(from_iso8601_timestamp(event_timestamp)) as latest_ts
FROM notifly_analytics.notifly_campaign_events
WHERE dt >= '2026-05-22'
  AND event_name = 'campaign_published'
  AND from_iso8601_timestamp(event_timestamp)
      BETWEEN TIMESTAMP '2026-05-22 01:00:00 UTC'
          AND TIMESTAMP '2026-05-22 02:00:00 UTC'
GROUP BY project_id, campaign_id
ORDER BY event_count DESC
LIMIT 10;
```

### 4. Verify queue fully drained (no data loss)

Check `ApproximateNumberOfMessagesVisible` on the main queue after the alarm window:
```bash
aws cloudwatch get-metric-statistics \
  --region ap-northeast-2 \
  --namespace AWS/SQS \
  --metric-name ApproximateNumberOfMessagesVisible \
  --dimensions Name=QueueName,Value=kinesis-record-dispatcher-queue \
  --statistics Average \
  --period 60 \
  --start-time $(date -u -d '2 hours ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ)
```

If it drops to zero within 5–10 minutes of the spike, no messages were lost.

## Classification

- **Lambda Errors=0, Throttles=0, Duration normal** + queue drains completely → `no_action`
- Root cause: **Lambda consumer throughput is below peak producer burst rate**
- This is a structural capacity mismatch, not a code bug or transient AWS failure

## Long-term fix target

- `kinesis-record-dispatcher` Lambda `EventSourceMapping`: increase `MaximumConcurrency` or `BatchSize`
- Or: `@notifly/kinesis` library-level rate limiting / backpressure to smooth SQS sends
- Terraform: review `infra/terraform/modules/kinesis_record_dispatcher/` or equivalent for Lambda concurrency config

## Related references

- `references/sqs-lambda-throughput-bottleneck.md` — generic throughput bottleneck recipe
- `references/sqs-dlq-kinesis-record-dispatcher-pattern.md` — DLQ message inspection and scope extraction for this queue
