# Segment-Publisher "slow eic query" Metric Filter

Session: 2026-05-06, 2026-05-07
Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`

## What the alarm actually fires on

The metric filter pattern is `took too long` (namespace `ConsoleErrors`, metric name `segment-publisher-prod slow eic query`). This broad substring match catches **two distinct log signatures** with different root causes, severity, and triage paths.

### Pattern A — Actual slow EIC query (alarm name accurate)

```
EventCounterCteManager.extract:{project_id} took too long: {ms}ms
```

This is emitted when the `event_intermediate_counts_{project_id}` aggregation query in `EventCounterCteManager.extract` exceeds internal latency expectations. The SQL is typically a `SUM(CASE WHEN ...)` grouped aggregation on `event_intermediate_counts`.

**Scope:** project-specific (table suffix in the log line). DB query latency signal.  
**Severity:** real DB workload indicator. Unlike Pattern B, this is not a benign WARN continuation.

Example query fingerprint:
```sql
select "notifly_user_id",
  SUM(CASE WHEN name = '...' THEN count ELSE 0 END) AS "cte_column_0",
  SUM(CASE WHEN name = '...' AND dt >= '...' THEN count ELSE 0 END) AS "cte_column_1"
from "event_intermediate_counts_{project_id}"
where "name" in (...) group by "notifly_user_id"
```

### Pattern B — Batch processing latency (alarm name mismatched / known noise)

```
[WARN] Processing took longer than expected: 3011248.69 ms
```

This is emitted by `services/task/segment-publisher/sqs_publisher.ts:55` when the total batch-processing time exceeds 30 minutes (1,800,000 ms). The processing time is dominated by large-scale campaign recipient publishing (e.g., stepup project campaign `UL1T00`, ~879K recipients), not by a slow `event_intermediate_counts` SQL query.

**Scope:** campaign-specific (from log context).  
**Severity:** benign WARN; invocation continues normally.

## Why Pattern B is noisy / mismatched

1. **Severity mismatch** — the log level is `[WARN]` and the invocation continues normally, yet it lands in `ConsoleErrors`.
2. **Cause mismatch** — the alarm name says "slow eic query", but Pattern B trigger is batch-processing latency in `sqs_publisher.ts`, not DB query time.
3. **Duplication** — the same log group already has a proper `Custom/segment-publisher` metric filter (`segment-publisher-slow-processing-filter`) with pattern `Processing took longer than expected` and metric `SegmentPublisher.ExecutionTimeOverThreshold`, plus a companion alarm `segment-publisher long running alam`.

## Known recurrence

- Pattern B: roughly daily around the same campaign window (stepup `UL1T00`). Project `32d8d9d6294d52e7a5427c036b471f91` (product `stepup`) is explicitly noted in code comments as dominating this alert.
- Pattern A: observed 2026-05-07 for project `b57754a9497a545ab9b0e4aadd6f53b6` (product `regather`). EIC aggregation on `event_intermediate_counts_b57754a9497a545ab9b0e4aadd6f53b6` took ~128 s.

## Triage rule

Determine which pattern triggered the current alarm before classifying.

**If Pattern A (EventCounterCteManager.extract):**
- Scope to the project in the log line (e.g., `regather` from `event_intermediate_counts_{project_id}`).
- Classify as `needs_fix` or monitor, because it signals real DB query latency on `event_intermediate_counts`.
- The EIC table size/index health for that project is the concrete next lookup target.

**If Pattern B (plain `[WARN] Processing took longer than expected`):**
- Scope to the campaign in the log (e.g., `stepup/UL1T00`).
- Classify as `no_action` because it is a known recurring pattern with no delivery failure or data loss.
- Note the metric-filter name mismatch in the final answer when it helps explain the noise.

**If the log instead shows an actual unhandled exception, DB error, or dead-letter event:**
- Treat that as the real signal and re-evaluate regardless of which parent pattern it resembles.

## Session evidence

- **2026-05-07 11:50 KST ALARM**: Metric datapoint 1.0 at 11:49:00 UTC, log line `[WARN] Processing took longer than expected: 3025296.53 ms` at 11:49:49.527 UTC. This is Pattern B (batch processing in `sqs_publisher.ts`), not Pattern A (slow EIC query). Scope: proudp/UL1T00 (~879K recipients). The log timestamp (11:49:49) falls inside the CloudWatch metric period 11:49:00–11:49:59, which the alarm evaluated at 11:50:21 UTC.
- Pattern A was also present earlier the same day (10:50:04 and 10:53:37 UTC for regather, ~128s), but those triggered separate ALARM transitions (10:51 and 10:54). The 11:50 transition is unequivocally Pattern B.

## Helper / investigation gap

The `check` helper derives Logs Insights filter terms from the alarm/metric name (`slow eic query`) rather than the metric filter pattern (`took too long`). This causes `count_7d` and `count_30d` to return 0 even when actual matches exist. Use the bounded manual trace in `references/ecs-log-manual-trace.md` with the exact metric filter pattern `took too long` when the helper reports empty current trigger contexts for this alarm.
