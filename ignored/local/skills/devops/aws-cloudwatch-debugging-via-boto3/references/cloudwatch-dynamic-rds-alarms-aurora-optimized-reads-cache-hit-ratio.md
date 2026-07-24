# Aurora Optimized Reads cache hit ratio alarms

Use when tuning `AWS/RDS` `AuroraOptimizedReadsCacheHitRatio` alarms for Aurora PostgreSQL clusters.

## Metric semantics

`AuroraOptimizedReadsCacheHitRatio` is a cache-efficiency signal for Aurora Optimized Reads, not a direct user-impact metric. AWS documents it as roughly:

```text
orcache_blks_hit / (orcache_blks_hit + storage_blks_read)
```

Treat it as a warning/diagnostic signal unless correlated with latency, I/O pressure, DB load, replica lag, Lambda/ECS errors, or customer-facing symptoms.

## Tuning pattern for noisy boundary flaps

If the alarm is flapping around a threshold such as `<= 30%` or `<= 25%` with `Period=3600`, first distinguish a real sequence of incidents from sliding-window churn. CloudWatch reevaluates one-hour periods every minute; the six period boundaries therefore slide together, and borderline hourly averages can repeatedly produce `OK -> ALARM -> OK` transitions even with `3/6` persistence.

Replay the raw 1-minute metric with those sliding boundaries and validate the simulator by reproducing the real `Action` count from alarm history. Then compare candidates. A practical warning-only starting point for a Notifly-like workload is:

```text
metric_name          = AuroraOptimizedReadsCacheHitRatio
period               = 3600
statistic            = Average
comparison_operator  = LessThanOrEqualToThreshold
threshold            = 25
EvaluationPeriods    = 6
DatapointsToAlarm    = 4
treat_missing_data   = missing
```

Interpretation: alert only when cache hit ratio stays `<= 25%` for at least 4 of 6 one-hour periods. This preserves the same definition of poor cache efficiency while reducing boundary churn. It is not a universal default: keep `3/6` when replay shows acceptable behavior. In one seven-day production replay, the current `25%, 3/6` simulation matched 10 actual actions; `25%, 4/6` reduced them to 3, while `20%, 3/6` produced none.

For paging/critical semantics, do not page on cache ratio alone. Use a composite or operational runbook requiring a second pressure signal, for example:

- low cache ratio plus `ReadLatency` / `WriteLatency` degradation
- low cache ratio plus high `VolumeReadIOPs` / `VolumeWriteIOPs`
- low cache ratio plus DBLoad/DBLoadNonCPU or replica recovery conflicts
- low cache ratio plus Lambda/ECS duration/errors/DLQ/user-impact metrics

## Sliding one-hour windows can still flap with M-of-N

`Period=3600` does not mean CloudWatch evaluates only on fixed clock-hour boundaries. CloudWatch can reevaluate every minute using six one-hour windows with that minute offset. State reasons therefore show datapoints such as `03:07`, `04:07`, ..., then a later evaluation may use `03:14`, `04:14`, ... . When hourly averages hover near the threshold, the membership of the M breaching windows changes minute by minute and a nominally persistent `3/6` alarm can still flip `OK ↔ ALARM` repeatedly.

Investigation and replay pattern:

1. Count `Action` history, not only Slack messages or state history. Multiple ALARM actions can be one continuous low-efficiency episode with boundary flapping, not independent incidents.
2. Fetch the cluster metric at `Period=60` for the retained window.
3. For every evaluation minute, calculate six contiguous 60-minute rolling averages at the same minute offset.
4. Replay the CloudWatch state machine:
   - enter ALARM when at least `M` of `N` windows breach;
   - leave ALARM when at least `N-M+1` windows do not breach;
   - compare simulated entries with actual `Action` history to validate the replay.
5. Simulate candidate persistence values before changing production. In one representative seven-day Notifly window, live `<=25%, 3/6` replayed 10 ALARM entries and matched the 10 actual actions; `<=25%, 4/6` replayed 3 entries, while `<=20%, 3/6` replayed none. Treat these as examples only and recompute each incident.

Practical interpretation:

- Keep cache ratio as warning/diagnostic telemetry.
- Prefer `4/6` over blindly lowering the threshold when the goal is to suppress boundary flaps while retaining visibility.
- If `<=20%` produced no alerts in replay, it can be considered for a critical tier only when combined with latency, I/O, DBLoad, replica-lag, or application-impact signals.
- Report exact notification times and explicitly say when repeated posts are alarm re-entries from one episode rather than separate outages.

## Post-tuning alert verification

A new alert after changing `3/6 -> 4/6` does not by itself mean the Terraform change failed or that immediate DB intervention is required.

1. Verify the live alarm before interpreting the alert:
   - `AlarmConfigurationUpdatedTimestamp`
   - `DatapointsToAlarm`, `EvaluationPeriods`, threshold, period, description
   - merge/apply time versus the new `OK -> ALARM` time
2. Read state history at one-minute resolution after the configuration update. Even `4/6` can enter ALARM for one minute and return to OK on the next evaluation because all six one-hour boundaries slide together.
3. State the actual outcome precisely:
   - tuning reduced notification frequency;
   - it did not guarantee zero boundary flips;
   - a one-minute ALARM followed by immediate OK is usually not an operational incident when companion signals remain healthy.
4. Re-check the current state immediately before reporting. A response based on a state sampled one or two minutes earlier can already be stale.
5. Correlate the alert with both reader-local and writer signals:
   - per-reader hit ratio, DBLoad, CPU, ReadIOPS, read latency, replica lag, free ephemeral storage
   - writer DBLoad/CPU/WriteIOPS/latency plus PI waits and top SQL
   - `High VolumeReadIOPs`, RDS events, and application DB-error signatures
6. A brief writer spike can be real and still require no on-call action. If it recovers within one sample window while reader DBLoad/latency/lag and application errors remain healthy, classify it as a workload burst to follow up, not a failover/restart/scale event.
7. Attribute PI table suffixes to projects when one tenant dominates, but phrase writer pressure as a correlated contributor: the cache-hit alarm is reader-local unless direct evidence proves causation.
8. Compare the alarm datapoint timestamps with any newly discovered application query/deploy timeline. A current ALARM can still be driven by older one-hour windows while a newer expensive query is a separate regression. Report both independently rather than forcing one causal story.
   - If PI shows `delivery_result_<projectId>` / `message_events_<projectId>`, correlate `/api/projects/<projectId>/delivery-results` access-log duration and current `pg_stat_activity`.
   - A request with `status=-` / `duration=-` can be disconnected or unfinished, while the PostgreSQL query may continue running.
   - For the full Notifly query/schema workflow, use `notifly-alert-live-investigation` → `references/notifly-delivery-results-rds-cache-churn.md`.

Do not respond to residual flapping by mechanically increasing persistence again (`4/6 -> 5/6`). If the Slack signal is intended to be actionable, the better next design is usually:

- keep the cache-ratio alarm as warning/diagnostic telemetry;
- create a composite/actionable alarm requiring low cache ratio plus `VolumeReadIOPs`, latency, DBLoad, replica lag, or application-error deterioration;
- or apply notification cooldown/deduplication to the warning route.

## Metric scope and reader aggregation pitfall

For an Aurora cluster with `r6gd` Optimized Reads readers and a non-Optimized-Reads writer, a cluster-dimension `AuroraOptimizedReadsCacheHitRatio` alarm can aggregate reader samples even though the alarm dimension is only `DBClusterIdentifier`.

Verify this rather than assuming the writer is affected:

- call `list_metrics` for the metric and inspect `DBInstanceIdentifier`, `DBClusterIdentifier`, and `Role=READER` dimension sets;
- inspect cluster membership and instance classes;
- compare cluster `SampleCount` with reader count (for example, 180 samples/hour can indicate three readers × 60 one-minute samples);
- pull per-reader hit ratio, DBLoad, CPU, latency, replica lag, and ephemeral-storage metrics;
- state clearly that a low cluster ratio is reader-local cache inefficiency, while writer write pressure is a correlated contributor unless direct evidence proves causation.

Also check current PostgreSQL progress views before attributing the event to DDL. An empty `pg_stat_progress_create_index` means there is no active index build; large existing index families can still add ongoing UPSERT/write-maintenance cost, but that is a separate, evidence-qualified hypothesis.

## Terraform implementation pitfall

Many Terraform roots use `for_each` keys or `alarm_name` as the CloudWatch alarm identity and also set `prevent_destroy = true`. Do **not** rename the alarm/key just to improve wording unless replacement has been explicitly approved.

For tuning an existing alarm, keep the existing map key/alarm name and update only in-place attributes such as:

```text
threshold
evaluation_periods
datapoints_to_alarm
alarm_description
```

Verify the plan is in-place only:

```text
Plan: 0 to add, 1 to change, 0 to destroy.
```

If a rename is desirable, split it into a separate human-reviewed migration because replacement/deletion may be blocked by `prevent_destroy` and can break alert continuity.

## Companion dashboard metrics

When investigating low hit ratio, inspect together:

- `FreeEphemeralStorage`
- `ReadIOPSEphemeralStorage`, `WriteIOPSEphemeralStorage`
- `ReadLatencyEphemeralStorage`, `WriteLatencyEphemeralStorage`
- `VolumeReadIOPs`, `VolumeWriteIOPs`
- `ReadLatency`, `WriteLatency`
- `DBLoad`, `DBLoadCPU`, `DBLoadNonCPU`
- relevant Lambda/ECS duration, errors, queue depth/DLQ, and recovery-conflict logs
