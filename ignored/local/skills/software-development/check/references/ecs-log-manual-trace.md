# Manual ECS Log Context Tracing (Helper Fallback)

When the helper skips `logs_insights_summary` with "no stable filter terms inferred"
—even though a metric filter exists on the ECS log group—use this manual trace to
recover the current trigger context.

## When to use

- `metric_filters[]` shows a clear `filter_pattern` (e.g., a simple string match).
- `logs.skipped` says the helper refused to scan.
- `can_answer_root_cause` is `false` because `current_trigger_contexts` is missing.
- You need the exact triggering log line and surrounding business context.

## Steps

1. **Bounded Logs Insights query** around the latest ALARM transition ±15 min:
   ```bash
   aws logs start-query \
     --log-group-name '/aws/ecs/notifly-services-prod/<service>' \
     --start-time $(date -d '2026-05-06 11:30:00 UTC' +%s) \
     --end-time   $(date -d '2026-05-06 12:00:00 UTC' +%s) \
     --query-string 'fields @timestamp, @message | filter @message like /PATTERN/ | sort @timestamp desc | limit 20'
   ```
   Use the exact `filter_pattern` from the metric filter configuration.

2. **Get query results**, extract `@ptr` (log record pointer).

3. **Resolve the log stream** from the pointer:
   ```bash
   aws logs get-log-record --log-record-pointer '<ptr>' --region ap-northeast-2
   ```
   Read `@logStream` from the response.

4. **Fetch surrounding context** from that exact stream:
   ```bash
   aws logs filter-log-events \
     --log-group-name '/aws/ecs/notifly-services-prod/<service>' \
     --log-stream-names '<stream>' \
     --start-time <epoch-ms> --end-time <epoch-ms> \
     --limit 100
   ```

5. **Sanitize and scope** — extract campaign IDs, recipient counts, batch indices, project IDs, error signatures. Do not paste raw full payloads.

## Example outcome

From a `segment-publisher` trace around a `Processing took longer than expected` alarm:

```
campaignId: UL1T00, 879211 recipients published. (batch index: 18)
Total processing time: 3011248.69 ms
[WARN] Processing took longer than expected: 3011248.69 ms
```

This gives:
- campaign scope (`UL1T00`)
- concrete customer impact (879K recipients, ~50 min delay)
- exact code source (`sqs_publisher.ts:55`)

## Pitfalls

- Do not run unbounded `filter-log-events` across the entire log group without a stream or time restriction.
- Do not dump more than ~20 surrounding lines; keep evidence compact.
- If the log stream has high volume, narrow the time window to ±5 min around the metric datapoint breach.
