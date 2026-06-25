# Aurora VolumeReadIOPs Batch-Workload Triage

## Alarm shape

- Metric: `AWS/RDS` → `VolumeReadIOPs`
- Dimension: `DBClusterIdentifier` (e.g., `notifly-db-prod-cluster`)
- Typical threshold: `Average >= 15M` (previously 12.5M; raised to reduce daily noise) over `Period=900` with `EvaluationPeriods=2`, `DatapointsToAlarm=2` (2 consecutive 15-min datapoints must breach)
- Alarm name may be bare (e.g., `High VolumeReadIOPs`) and **not** contain the cluster identifier.
- The 15M threshold sits close to the daily batch peak (observed breach: 15.36M, ~2.4% margin), so the alarm fires on most batch days when read IOPS is slightly elevated. This is expected — the batch workload itself is benign, not the alarm sensitivity.

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

At Notifly prod, daily peak `VolumeReadIOPs` ranges 10M–20M. Threshold was originally 12.5M (caught the batch every day), later raised to 15M to reduce noise. Even at 15M, the batch peak still breaches on most days (observed 15.36M vs 15M threshold). The batch typically:
- Starts within a consistent ~30-minute daily window (most alarms fire KST 20:00–21:00)
- Lasts 25–35 minutes
- Recovers cleanly to `OK` without manual intervention

When the daily fire time shifts by hours (e.g., from ~20:50 KST to ~15:00 KST), check whether campaign schedules or segment-publisher trigger times were adjusted.

## Performance Insights when available

When PI is authorized (not `NotAuthorizedException`), the top SQL by `db.load.avg` during a VolumeReadIOPs batch window shows:

**Writer (notifly-db-prod-c):**
- `DEALLOCATE ALL` — prepared-statement cleanup, **not a business query**. Frequently appears as the #1 writer load (focus_max observed: 27.97). It is a PgBouncer / connection-pool lifecycle statement fired when connections are recycled. Do not attribute the VolumeReadIOPs spike to it or investigate it as a root cause.
- `INSERT INTO event_intermediate_counts_<project_id> AS EIC ... ON CONFLICT` — EIC upsert from `kds-consumer` / batch processing. This is the dominant **business** writer load. The `<project_id>` suffix maps to the project with the highest event ingestion volume during the window (observed: stepup focus_avg=1.71, playio=0.53, regather=0.28).

**Readers (notifly-db-prod-a/b/d):**
- `select * from "users_<project_id>" where "notifly_user_id" = $?` — point lookup per user resolution
- `select "notifly_user_id", exit_time IS NULL AS is_active, COUNT(*) ... from "user_journey_sessions_<project_id>"` — user journey session count
- `SELECT device_table.notifly_device_id, ... FROM device_<project_id> ...` — device resolution join
- `SELECT user_table.notifly_user_id, ... FROM users_<project_id>` (Athena/Spark subquery form)

All reader queries are parameterized point lookups or small aggregates — no full scans. The ReadIOPS spike comes from the **volume** of these lookups across all readers simultaneously, not from any single expensive query.

**Key takeaway**: When PI shows `DEALLOCATE ALL` as top writer load during a VolumeReadIOPs alarm, classify it as `current_unattributed_top_sql` (no table refs) and focus the root-cause narrative on the `event_intermediate_counts_*` INSERT family and the reader-side `users_*` / `user_journey_sessions_*` / `device_*` lookups instead.

## Companion-alarm shortcut

When `segment-publisher long running alam` (namespace `Custom/segment-publisher`) is in `ALARM` with a datapoint overlapping the `VolumeReadIOPs` breach window, treat this as strong evidence that the IOPS spike is caused by the known `segment-publisher` scheduled batch workload. The batch queries (`user_journey_sessions_*`, `event_intermediate_counts_*`) run in parallel across reader instances, producing the uniform ReadIOPS signature described above.

This shortcut is especially useful when:
- Fargate log streams have already expired before investigation.
- `filter_log_events` returns zero matches despite the metric filter demonstrably breaching.

In this case, the companion alarm's purpose-built metric filter (`Processing took longer than expected`) proves the batch workload is active, and the `VolumeReadIOPs` alarm is catching its parallel query side effect. Classification remains `no_action` when ReadLatency is healthy and CPU headroom exists.

See `references/segment-publisher-slow-eic-query-noise.md` § "Cross-reference: RDS VolumeReadIOPs correlation" for the reverse direction.

## Scope

This alarm is **infra-wide** at the cluster level. Segment-publisher logs can tie the triggering batch to a specific `project_id`/`campaign_id` pair, but the alarm itself does not dimension by project. Report the dominant project/campaign from logs when available; otherwise state infra-wide scope.

## Known gotchas

- **Alarm name ≠ resource name**: The alarm may be named `High VolumeReadIOPs` with no cluster identifier embedded. Do not fabricate an alarm name by prepending the cluster ID.
- **`DEALLOCATE ALL` is not a root cause**: When PI is available, `DEALLOCATE ALL` frequently appears as the #1 writer load (focus_max up to ~28). It is a connection-pool prepared-statement cleanup, not a business query. Attribute the spike to the `event_intermediate_counts_*` INSERT family and reader-side lookups instead. See "Performance Insights when available" above.
- **Performance Insights unauthorized**: `pi:DescribeDimensionKeys` may return `NotAuthorizedException`. Do not block the triage on PI; fall back to CloudWatch metrics + ECS logs.
- **Per-instance `VolumeReadIOPs` does not exist**: Use `ReadIOPS` at `DBInstanceIdentifier` dimension for instance-level breakdown.
- **Threshold may have been raised**: The alarm threshold was 12.5M and later raised to 15M. Always read the actual `Threshold` and `EvaluationPeriods` from `describe-alarms` rather than assuming a fixed value.
