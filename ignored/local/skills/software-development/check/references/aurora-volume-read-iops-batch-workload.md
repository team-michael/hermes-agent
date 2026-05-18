# Aurora VolumeReadIOPs Batch-Workload Triage

## Alarm shape

- Metric: `AWS/RDS` → `VolumeReadIOPs`
- Dimension: `DBClusterIdentifier` (e.g., `notifly-db-prod-cluster`)
- Typical threshold: `Average >= 12.5M` over `Period=900` with `EvaluationPeriods=1`
- Alarm name may be bare (e.g., `High VolumeReadIOPs`) and **not** contain the cluster identifier.

## Why this alarm fires

Aurora PostgreSQL reports cluster-level read I/O ops that aggregate all instances (writer + readers). When the `segment-publisher` scheduled batch runs, it executes parallel Athena + Postgres queries across reader instances, creating a synchronized ReadIOPS spike on every reader simultaneously.

## Quick triage checklist

1. **Describe the alarm** — confirm exact name, threshold, period, and `StateReasonData.startDate`.
2. **Alarm history** — count 30d/7d/1d ALARM transitions. Look for time-of-day recurrence.
3. **Metric pattern around the breach** — cluster `VolumeReadIOPs` 5-min datapoints.
4. **Per-instance ReadIOPS** — fetch `AWS/RDS` `ReadIOPS` per `DBInstanceIdentifier` during the window.
   - Uniform spikes across all readers → distributed batch query (expected scheduled workload).
   - Isolated spike on one instance → investigate that specific instance.
5. **ReadLatency** — cluster-level `ReadLatency` should stay under ~5 ms.
   - If ReadLatency stays low, the spike is throughput, not contention.
6. **CPUUtilization** — per-instance CPU during the window.
   - CPU under ~50% with low ReadLatency means headroom remains; this is capacity, not an incident.
7. **Segment-publisher correlation** — check `/aws/ecs/notifly-services-prod/segment-publisher` log streams active during the window for `Start extracting project segment` and `recipients published` lines.
8. **Scope extraction** — segment-publisher logs contain `project_id` and `campaign_id`. Map `project_id` via DynamoDB `project` table.

## Key metrics

```python
# Cluster-level VolumeReadIOPs around alarm
cw.get_metric_statistics(
    Namespace='AWS/RDS',
    MetricName='VolumeReadIOPs',
    Dimensions=[{'Name':'DBClusterIdentifier','Value':'notifly-db-prod-cluster'}],
    StartTime=alarm_start - timedelta(minutes=30),
    EndTime=alarm_start + timedelta(minutes=60),
    Period=300,
    Statistics=['Average','Maximum']
)

# Per-instance ReadIOPS (Aurora uses ReadIOPS, not VolumeReadIOPs, at instance level)
for inst in ['notifly-db-prod-a', ..., 'notifly-db-prod-i']:
    cw.get_metric_statistics(..., MetricName='ReadIOPS',
        Dimensions=[{'Name':'DBInstanceIdentifier','Value':inst}], ...)

# ReadLatency
 cw.get_metric_statistics(..., MetricName='ReadLatency', ...)
```

## Interpretation

| Pattern | Classification | Rationale |
|---------|---------------|-----------|
| Daily recurrence, ~25–35 min duration, ReadLatency < 5 ms, CPU < 50%, uniform reader spikes, segment-publisher logs active | `no_action` | Expected scheduled batch read workload. Cluster has capacity headroom. |
| Isolated instance spike, ReadLatency > 10 ms, or CPU > 80% | `needs_fix` or `urgent` | Possible runaway query, missing index, or Aurora reader instability. |
| No segment-publisher or batch job correlation, first-ever spike | `needs_fix` | Investigate source of unexpected read load (new query, scan, backup). |

## Historical baseline

At Notifly prod, daily peak `VolumeReadIOPs` ranges 10M–20M. Threshold set at 12.5M catches the scheduled batch every day. The batch typically:
- Starts within a consistent ~30-minute daily window
- Lasts 25–35 minutes
- Recovers cleanly to `OK` without manual intervention

When the daily fire time shifts by hours (e.g., from ~20:50 KST to ~15:00 KST), check whether campaign schedules or segment-publisher trigger times were adjusted.

## Scope

This alarm is **infra-wide** at the cluster level. Segment-publisher logs can tie the triggering batch to a specific `project_id`/`campaign_id` pair, but the alarm itself does not dimension by project. Report the dominant project/campaign from logs when available; otherwise state infra-wide scope.

## Known gotchas

- **Alarm name ≠ resource name**: The alarm may be named `High VolumeReadIOPs` with no cluster identifier embedded. Do not fabricate an alarm name by prepending the cluster ID.
- **Performance Insights unauthorized**: `pi:DescribeDimensionKeys` may return `NotAuthorizedException`. Do not block the triage on PI; fall back to CloudWatch metrics + ECS logs.
- **Per-instance `VolumeReadIOPs` does not exist**: Use `ReadIOPS` at `DBInstanceIdentifier` dimension for instance-level breakdown.
