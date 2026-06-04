# Aurora Optimized Reads cache hit ratio alarms

Use when tuning `AWS/RDS` `AuroraOptimizedReadsCacheHitRatio` alarms for Aurora PostgreSQL clusters.

## Metric semantics

`AuroraOptimizedReadsCacheHitRatio` is a cache-efficiency signal for Aurora Optimized Reads, not a direct user-impact metric. AWS documents it as roughly:

```text
orcache_blks_hit / (orcache_blks_hit + storage_blks_read)
```

Treat it as a warning/diagnostic signal unless correlated with latency, I/O pressure, DB load, replica lag, Lambda/ECS errors, or customer-facing symptoms.

## Tuning pattern for noisy boundary flaps

If the alarm is flapping around a threshold such as `<= 30%` with `Period=3600`, `EvaluationPeriods=1`, `DatapointsToAlarm=1`, prefer changing both threshold and persistence rather than only muting notifications.

A practical warning-only default observed for Notifly prod:

```text
metric_name          = AuroraOptimizedReadsCacheHitRatio
period               = 3600
statistic            = Average
comparison_operator  = LessThanOrEqualToThreshold
threshold            = 25
EvaluationPeriods    = 6
DatapointsToAlarm    = 3
treat_missing_data   = missing
```

Interpretation: alert only when cache hit ratio stays `<= 25%` for at least 3 of 6 one-hour periods. This preserves visibility while avoiding single-hour `30%` boundary flaps.

For paging/critical semantics, do not page on cache ratio alone. Use a composite or operational runbook requiring a second pressure signal, for example:

- low cache ratio plus `ReadLatency` / `WriteLatency` degradation
- low cache ratio plus high `VolumeReadIOPs` / `VolumeWriteIOPs`
- low cache ratio plus DBLoad/DBLoadNonCPU or replica recovery conflicts
- low cache ratio plus Lambda/ECS duration/errors/DLQ/user-impact metrics

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
