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
AWS `get-metric-statistics` only accepts `SampleCount | Average | Sum | Minimum | Maximum`. `p99` is not valid there. Use `Maximum` as a conservative proxy, or switch to `get-metric-data` with `Stat: 'p99'` inside `MetricStat` (not `ExtendedStatistics`) if exact percentiles are needed.

### 2. `describe-alarm-history` may return null `StateValue`/`StateReason`
The History API can return entries where both `StateValue` and `StateReason` are `null`. This prevents the helper from counting ALARM transitions directly from history fields. When this happens, fall back to:
- inspecting the alarm's current `StateReason` from `describe-alarms`
- reading metric datapoints directly to see which periods breached
- inferring transition count from metric breach density, not history nulls

### 3. Alarm name parsing with embedded priority tiers
The alarm name contains `-P2-` (priority tier), but the actual Lambda function is `scheduled-batch-delivery` without the tier suffix. The metric namespace `Notifly/ScheduledBatchDelivery` is shared across all priority tiers. Text-based alarm name extraction must handle embedded hyphens and tier labels.

### 4. EMF log sampling may miss sparse tail-latency events
`FCMSendLatency` EMF lines are INFO-level and emitted once per batch. When total batch volume is high (500+ batches in a 5-minute window), `filter-log-events` pagination (even across multiple calls) may not capture the small subset of lines with latency >3000ms because the high-latency tail is sparse and distributed across many log streams. In session 2026-06-12, 1000 paginated EMF lines showed zero >3000ms events even though `get-metric-data` reported p99=9785ms and Maximum=15151ms. **For classification, prefer metric-based verification (`get-metric-data` p99/Maximum + Lambda/SQS/DB health checks) over relying on log sampling to confirm the tail-latency signature.**

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

## Alternative root cause: concurrent campaign volume overlap (not a slow-batch tail)

Session 2026-07-08 observed a second distinct pattern: the p99 breach was driven by a raw *volume* spike, not a small set of unusually slow batches. Evidence chain:

1. `AWS/Lambda Invocations` for `scheduled-batch-delivery` jumped from a ~3,000/5min baseline to 4,762 → 6,193 → 9,250 in the three 5-minute buckets leading into the breach.
2. `Notifly/ScheduledBatchDelivery FCMSendBatch` with `outcome=success` jumped from ~2,900/5min baseline to 19,610 → 10,240 → 8,533 in the same window — a 3–7x surge.
3. `outcome=error` batch counts stayed in the normal 148–208 band (no error-rate change), and `AWS/Lambda Errors`/`Throttles` were 0 throughout — ruling out a code/dependency failure.
4. Because the surge was volume, not a handful of slow outliers, EMF `FCMSendLatency > 3000` filtering (the query above) is the wrong scope tool here — the dominant contributor is whichever campaign contributed the most *batches/recipients* in the window, not the highest individual latency.

**Scope extraction technique for this pattern** — pull raw `FCMSendBatch` EMF lines for the exact breach window and aggregate `recipient_count` by `(project_id, campaign_id)` in Python instead of Logs Insights (avoids `parse` field-collision issues and is easier to iterate on):

```bash
aws logs filter-log-events --region ap-northeast-2 \
  --log-group-name /aws/lambda/scheduled-batch-delivery \
  --start-time <epoch_ms_start> --end-time <epoch_ms_end> \
  --filter-pattern '"FCMSendBatch"' --max-items 500 --output json > /tmp_fcm.json
```

```python
import re, json
from collections import defaultdict
agg = defaultdict(int)
for line in open('/tmp_fcm.json'):
    ...
# or, once loaded as dict: iterate events[].message, regex out the _aws JSON blob,
# json.loads it, and sum recipient_count keyed by (project_id, campaign_id).
```

Sort by summed `recipient_count` descending — the top 1-2 (project_id, campaign_id) pairs are usually two or more *legitimate* campaigns whose scheduled sends happened to overlap in the same 5-10 minute window, which is enough to push p99 over 3000ms purely from queueing/serialization inside the Lambda, even though every batch still succeeds. Map both project_ids via DynamoDB `project` and report both in scope (do not force it to a single project when the evidence shows overlap).

Classification: this is the same `no_action` fast-path as the slow-tail pattern as long as Lambda Errors/Throttles stay at 0 and error batch rate stays in baseline — the mechanism differs (volume vs. outlier latency) but the customer impact (seconds of delay, zero data loss) and the escalation criteria are unchanged. If this volume-overlap pattern starts recurring several times per day with rising `Invocations`, treat it as a capacity signal for `needs_fix` (batch concurrency/rate-limit tuning) rather than a one-off scheduling coincidence.
