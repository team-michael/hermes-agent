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

**Pitfall — never `filter-log-events --filter-pattern '"<campaign_id>"'` on `segment-publisher` logs**: segment-publisher also logs a `Received event: {...}` startup/config line per invocation that embeds a base64-encoded blob of **every active project's sender credentials** (`fcm_service_account` private keys, SMTP/API secrets, etc.), keyed by project id hash. A bare campaign-ID substring filter can incidentally match this line (the ID string may appear anywhere inside that large JSON blob), and the terminal will then dump the full credential payload into your context. Always scope segment-publisher log queries with the fixed phrases `'recipients published'`, `'Start extracting project segment'`, or `'Total recipients published'` — never with a bare campaign/project ID as the sole filter pattern. If a Received-event line appears in any query result, do not read into or copy any part of it (do not print `fcm_service_account`, keys, or tokens) — discard it and re-query with a narrower phrase filter instead.

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

**Pitfall — main queue draining to zero does not mean zero loss; always cross-check the paired DLQ in the same window.** `maxReceiveCount=1` means any single failed receive during the concurrency crunch DLQs the message immediately with no retry — this can happen *while* the main queue is still healthily draining to 0. Always pull the DLQ's own metrics for the identical time range before concluding "no data loss":

```bash
aws sqs get-queue-attributes --region ap-northeast-2 \
  --queue-url 'https://sqs.ap-northeast-2.amazonaws.com/702197142747/kinesis-record-dispatcher-queue-dlq' \
  --attribute-names ApproximateNumberOfMessages

aws cloudwatch get-metric-statistics --region ap-northeast-2 \
  --namespace AWS/SQS --metric-name ApproximateAgeOfOldestMessage \
  --dimensions Name=QueueName,Value=kinesis-record-dispatcher-queue-dlq \
  --start-time <burst_window_start> --end-time <burst_window_end> \
  --period 3600 --statistics Maximum
```

If the DLQ's `ApproximateAgeOfOldestMessage` jumps from 0 to a nonzero value in the exact hourly bucket that overlaps the queue-age alarm (not some earlier stale residue — check the bucket timestamp lines up with the alarm window), the DLQ receipt is current and caused by this burst, not leftover from a previous incident. `ApproximateNumberOfMessages` on the DLQ alone doesn't tell you *when* those messages arrived — the age-of-oldest-message metric bucketed at the alarm hour does. When this happens, still classify the alarm itself `no_action` (Lambda healthy, structural throughput mismatch, self-resolving), but the `고객 영향도` field must say explicitly that N messages were dropped to DLQ with zero retries during the burst, name the affected project/campaign from the DLQ payload (see `references/sqs-dlq-kinesis-record-dispatcher-pattern.md` for both known payload shapes), and flag `maxReceiveCount=1` as the structural gap to track (not urgent, but real — don't round down to "no impact" just because the alarm condition itself resolved).

## Classification

- **Lambda Errors=0, Throttles=0, Duration normal** + queue drains completely → `no_action` for the alarm itself
- Root cause: **Lambda consumer throughput is below peak producer burst rate**
- This is a structural capacity mismatch, not a code bug or transient AWS failure
- Still check the paired DLQ per the pitfall above before writing `고객 영향도` — "alarm resolved" and "zero impact" are not the same claim

## Long-term fix target

- `kinesis-record-dispatcher` Lambda `EventSourceMapping`: increase `MaximumConcurrency` or `BatchSize`
- Or: `@notifly/kinesis` library-level rate limiting / backpressure to smooth SQS sends
- Terraform: review `infra/terraform/modules/kinesis_record_dispatcher/` or equivalent for Lambda concurrency config

## Related references

- `references/sqs-lambda-throughput-bottleneck.md` — generic throughput bottleneck recipe
- `references/sqs-dlq-kinesis-record-dispatcher-pattern.md` — DLQ message inspection and scope extraction for this queue
