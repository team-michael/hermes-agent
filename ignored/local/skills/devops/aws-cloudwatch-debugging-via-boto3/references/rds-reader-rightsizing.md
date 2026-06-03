# Aurora/RDS reader right-sizing via CloudWatch

Use this when asked whether a Notifly Aurora reader fleet can be reduced, e.g. 3 reader instances → 2.

## Minimal evidence set

1. Discover live cluster membership first:
   - `rds.describe_db_clusters(DBClusterIdentifier=...)`
   - `rds.describe_db_instances(DBInstanceIdentifier=...)`
   - separate writer vs readers, status, class, AZ, Performance Insights resource ID.
   - If transient/deleting readers exist, compute the main recommendation from **currently available active readers**, not stale/deleting identifiers.

2. Pull at least 30d CloudWatch 5-minute metrics per active reader:
   - `CPUUtilization` Average/Maximum
   - `DBLoad`, `DBLoadCPU`, `DBLoadNonCPU`
   - `DatabaseConnections`
   - `ReadIOPS`, `ReadThroughput`, `ReadLatency`
   - `AuroraReplicaLag`
   - `FreeableMemory`, `SwapUsage`, `DiskQueueDepth`

3. Compute per-instance p50/p95/p99/max and then a reduction projection:
   - For N→M readers, align datapoints by timestamp.
   - Sum active-reader workload at each timestamp and divide by M.
   - Report p50/p95/p99/max for the projected per-reader load.
   - Be explicit that this assumes roughly even reader-endpoint load balancing and no instance-endpoint pinning.

4. Verify burst behavior with 1-minute CPU where retention allows, especially against existing alarms:
   - Count datapoints above thresholds such as 60/70/80/90%.
   - Detect sustained runs, e.g. `>=70% for >=5 consecutive 1-minute datapoints`.
   - This is better than relying on isolated 5-minute max values.

5. Inspect scaling/alarms/events:
   - Application Auto Scaling target/policy for `rds:cluster:ReadReplicaCount`.
   - Metrics Insights or metric alarms covering the DB cluster/readers.
   - RDS events for recent create/delete/restart/failover; RDS events retain only about 14 days, so do not assume month-scale event history is available.

## Interpretation pattern

- If projected 2-reader p95 CPU is <~50%, p99 around ~50–60%, DBLoad remains well below vCPU count, latency/lag stay low, and there are no sustained alarm-threshold runs, a 3→2 trial is usually reasonable for cost optimization.
- Still separate **normal 2-reader operation** from **2-reader fleet with 1 reader down**. In 2-reader mode, losing one reader means the remaining reader absorbs all read traffic; N+1 safety can be much worse even when normal 2-reader p95 looks fine.
- If high projected CPU points are isolated and not sustained, call them burst risk rather than steady-state capacity failure.
- If memory/swap alarms fire, identify whether they came from writer or readers before attributing them to reader capacity.

## Recommended final answer shape

1. Direct verdict: can reduce / can trial / should not reduce.
2. Current topology table: writer/readers, class, AZ, status.
3. Current active-reader p95/p99/max table.
4. N→M projection table.
5. Risk distinction: normal operation vs one-reader-failed condition.
6. Guardrails for trial:
   - preserve AZ diversity,
   - verify no direct instance endpoint dependencies,
   - execute during low-traffic KST window,
   - monitor CPU, DBLoad, replica lag, read latency, connection errors for 24–48h.
