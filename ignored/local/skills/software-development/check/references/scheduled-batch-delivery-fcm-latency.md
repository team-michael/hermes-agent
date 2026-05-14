# Scheduled Batch Delivery FCM Latency Alarm Triage

Session: 2026-05-07  
Alarm: `ScheduledBatchDelivery-P2-FCMLatencyP99` (namespace `Notifly/ScheduledBatchDelivery`, metric `FCMSendLatency`)

## Alarm shape

- **Threshold**: `GreaterThanThreshold` 3000ms on `Maximum` (5-minute period)
- **Dimensions**: `outcome=success`, `channel=push-notification`
- **Current state**: Usually OK-to-ALARM-to-OK within minutes
- **FCM p99 is emitted as a custom metric**, not directly queryable through `get-metric-statistics` with a `p99` statistic.

## Key API pitfalls observed

### 1. `get-metric-statistics` does not support percentile statistics
AWS `get-metric-statistics` only accepts `SampleCount | Average | Sum | Minimum | Maximum`. `p99` is not valid. Use `Maximum` as a conservative proxy, or switch to `get-metric-data` with `ExtendedStatistics=['p99']` if exact percentiles are needed.

### 2. `describe-alarm-history` may return null `StateValue`/`StateReason`
The History API can return entries where both `StateValue` and `StateReason` are `null`. This prevents the helper from counting ALARM transitions directly from history fields. When this happens, fall back to:
- inspecting the alarm's current `StateReason` from `describe-alarms`
- reading metric datapoints directly to see which periods breached
- inferring transition count from metric breach density, not history nulls

### 3. Alarm name parsing with embedded priority tiers
The alarm name contains `-P2-` (priority tier), but the actual Lambda function is `scheduled-batch-delivery` without the tier suffix. The metric namespace `Notifly/ScheduledBatchDelivery` is shared across all priority tiers. Text-based alarm name extraction must handle embedded hyphens and tier labels.

## Triage checklist (read-only)

1. **Alarm definition** — confirm dimensions (`outcome`, `channel`) and threshold
2. **Lambda runtime** — check `AWS/Lambda` `Errors`, `Throttles`, `Duration` for the actual mapped function (`scheduled-batch-delivery`)
3. **SQS queues** — inspect `scheduled-batch-push-notification-queue` visible/in-flight counts and DLQ depth
4. **Metric datapoints** — fetch `Maximum` on `FCMSendLatency` around the alert window as p99 proxy, or use `get-metric-data` with `ExtendedStatistics=['p99']`
5. **Lambda logs ( External-latency verification )** — quick empty-filter confirmation:
   - `filter-log-events` on `/aws/lambda/scheduled-batch-delivery` with `filterPattern='ERROR'` → expect zero results
   - `filter-log-events` with `filterPattern='timeout'` → expect zero results
   - `filter-log-events` with `filterPattern='REPORT'` → typical duration 200–900 ms, max memory ~226 MB, all `Status=success`
   If all three hold, the latency root cause is external (FCM API), not Lambda execution failure.
6. **Logs** — if needed, check `/aws/lambda/scheduled-batch-delivery` for FCM response latency lines. Note that `FCMSendLatency` is emitted as EMF (Embedded Metric Format) `INFO` lines; these confirm metric source but do not explain *why* FCM was slow.

## Fast-path `no_action` criteria

If **all** of these hold, classify `no_action`:
- `outcome=success` dimension is present
- Lambda `Errors` = 0 and `Throttles` = 0
- SQS DLQ `ApproximateNumberOfMessages` = 0
- Metric spike recovered within one or two evaluation periods
- No customer-visible send-failure evidence in logs

Effect: push delivery may be delayed by seconds to tens of seconds, but no message loss.

**Rapid recurrence note**: This alarm often shows rapid recurrence (multiple OK→ALARM transitions within 10 minutes). Rapid recurrence alone does not override `no_action` when Lambda is healthy and metric values recover quickly. The p99 can spike to 4–6 seconds and drop back below 2 seconds within the next period. Treat each spike as a transient external latency burst unless the p99 sustains > threshold across 3+ consecutive periods or queue backlog grows.

## When to escalate

- `needs_fix`: recurrence is materially increasing vs 7d/30d baseline, or p99 sustains > threshold for > 2 consecutive periods with queue backlog. Concrete targets:
  1. `services/lambda/scheduled-batch-delivery/lib/send_push_v1_api.js` — review `batchSize`, `maxRetries`, and FCM HTTP client timeout.
  2. `infra/terraform/prod/ap-northeast-2/lambda/functions.tf` alarm block for `ScheduledBatchDelivery-P2-FCMLatencyP99` — evaluate whether threshold/period tuning is appropriate given normal FCM variance.
- `urgent`: Lambda Errors > 0, DLQ growing, or `outcome != success` metrics firing concurrently

## Related Notifly pattern

May 2026 evidence: this alarm fired multiple times daily. Daily `Maximum` values ranged from ~15s to ~45s. Lambda remained healthy, DLQ empty, and alerts consistently self-recovered.
