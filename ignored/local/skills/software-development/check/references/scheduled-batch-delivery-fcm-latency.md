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
5. **Volume stability check** — fetch `Sum` on `FCMSendBatch` (success + error) for the same window. Stable volume with a stable ~3–5% error rate means the latency spike is external variance, not a traffic surge or new failure mode.
6. **DbInsert error cross-check** — query `DbInsert` with `outcome=error` for `delivery_result` and `delivery_failure_log`. Zero error counts during the latency window confirms no database write failures are accompanying the FCM slowdown.
7. **Lambda logs ( External-latency verification )** — quick empty-filter confirmation:
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

May 2026 evidence: this alarm fired multiple times daily. Daily `Maximum` values ranged from ~8s to ~57s (30-day span). Lambda remained healthy, DLQ empty, and alerts consistently self-recovered.

Concrete baseline observed (2026-04-21 to 2026-05-16):
- 30-day ALARM transitions: ~75 (nearly daily)
- 7-day ALARM transitions: ~21–25
- 1-day ALARM transitions: ~4–9
- 10-minute rapid recurrence: common (2–3 transitions within 10 minutes)
- Daily FCM batch volume (success): ~600K–800K batches/day, stable
- Error batch rate: ~3–5% of total, stable
- No concurrent `DbInsert outcome=error` spikes during latency windows (cross-check `delivery_result` and `delivery_failure_log` metrics)
- Daily `Maximum` (FCMSendLatency) observed 2026-05-09 to 2026-05-16: 39491ms → 14227ms → 23977ms → 8727ms → 47069ms → 56997ms → 14727ms → 11455ms. Average remains stable at ~350ms, confirming extreme variance is tail-only.

These baselines confirm the alarm is a threshold-vs-normal-variance mismatch rather than a worsening or new regression.

## EMF log scope extraction

`FCMSendLatency` is emitted as EMF `INFO` lines in `/aws/lambda/scheduled-batch-delivery`. Each line carries `project_id` and `campaign_id`, so per-project/campaign scope attribution is possible when needed.

Example CloudWatch Logs Insights query:
```
fields @timestamp, @message
| filter @message like 'FCMSendLatency'
| parse @message "\"FCMSendLatency\":" as lat
| parse @message "\"project_id\":\"*\"" as project_id
| parse @message "\"campaign_id\":\"*\"" as campaign_id
| filter lat > 3000
| stats count() as cnt, max(lat) as max_lat by project_id, campaign_id
| sort max_lat desc
```

In the 2026-05-16 13:35 KST window, the dominant contributor was `project_id=02a3660e1b675689a0757409e5c1efaa` (`cosmo`) / `campaign_id=4SQbit` with entries at 3049ms, 1631ms, 1480ms, 1441ms, 1403ms, and 1252ms. Other campaigns showed normal sub-second latency. This confirms the p99 spike is driven by a small number of high-latency batches rather than a broad FCM degradation.
