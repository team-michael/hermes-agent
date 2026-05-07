# Segment-Publisher "slow eic query" Metric Filter Noise

Session: 2026-05-06  
Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`

## What the alarm actually fires on

The metric filter pattern is `took too long` (namespace `ConsoleErrors`, metric name `segment-publisher-prod slow eic query`).
The log line that actually triggers it is:

```
[WARN] Processing took longer than expected: 3011248.69 ms
```

This is emitted by `services/task/segment-publisher/sqs_publisher.ts:55` when the total batch-processing time exceeds 30 minutes (1,800,000 ms). The processing time is dominated by large-scale campaign recipient publishing (e.g., stepup project campaign `UL1T00`, ~879K recipients), not by a slow `event_intermediate_counts` (EIC) SQL query.

## Why it is noisy / mismatched

1. **Severity mismatch** — the log level is `[WARN]` and the invocation continues normally, yet it lands in `ConsoleErrors`.
2. **Cause mismatch** — the alarm name says "slow eic query", but the trigger is batch-processing latency in `sqs_publisher.ts`, not DB query time.
3. **Duplication** — the same log group `/aws/ecs/notifly-services-prod/segment-publisher` already has a proper `Custom/segment-publisher` metric filter (`segment-publisher-slow-processing-filter`) with pattern `Processing took longer than expected` and metric `SegmentPublisher.ExecutionTimeOverThreshold`, plus a companion alarm `segment-publisher long running alam`.

## Known recurrence

- Roughly daily around the same campaign window (stepup `UL1T00`).
- 30d/7d counts were both 5 transitions at the time of investigation.
- Project `32d8d9d6294d52e7a5427c036b471f91` (product `stepup`) is explicitly noted in code comments as dominating this alert.

## Triage rule

If the current trigger log is the plain `[WARN] Processing took longer than expected` with normal completion afterward:
- Scope to the campaign in the log (e.g., `stepup/UL1T00`).
- Classify as `no_action` because it is a known recurring pattern with no delivery failure or data loss.
- Note the metric-filter name mismatch in the final answer when it helps explain the noise.
- If the log instead shows an actual unhandled exception, DB error, or dead-letter event, treat that as the real signal and re-evaluate.
