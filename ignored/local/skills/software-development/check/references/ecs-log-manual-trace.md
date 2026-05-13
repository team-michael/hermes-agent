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

## Stream-first tail check for short-lived ECS tasks

Some ECS services (e.g., `segment-publisher`) run as short-lived Fargate tasks triggered by SQS. They create a new log stream per task, write all events quickly, and the stream becomes inactive within minutes. `filter-log-events` with a time window may return **zero** matches even when the triggering log exists, because:

- The stream was created and finished inside the window but is not indexed for `filter-log-events` fast enough.
- Task startup/shutdown flushes leave the stream in a state where `filter-log-events` skips it.

When this happens, use a **stream-first tail check** instead:

1. **List recent streams** (not events):
   ```bash
   aws logs describe-log-streams \
     --log-group-name '/aws/ecs/notifly-services-prod/<service>' \
     --order-by LastEventTime --descending --limit 20
   ```

2. **Inspect the tail of each candidate stream** with a small limit:
   ```bash
   aws logs get-log-events \
     --log-group-name '/aws/ecs/notifly-services-prod/<service>' \
     --log-stream-name '<stream>' \
     --start-from-head false --limit 10
   ```
   Scan the returned messages for the metric filter pattern or campaign/project IDs.

3. **Expand the matching stream** once you identify the right one:
   ```bash
   aws logs get-log-events \
     --log-group-name '/aws/ecs/notifly-services-prod/<service>' \
     --log-stream-name '<stream>' \
     --start-from-head false --limit 100
   ```
   This keeps the search bounded to exactly one stream.

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
- **For short-lived ECS tasks**, prefer `get_log_events` on recent streams over `filter-log_events` when the latter returns zero results despite an active alarm.
- **Stale `lastEventTimestamp` for actively-writing short-lived streams:** `describe_log_streams` can report a `lastEventTimestamp` that lags the actual most recent event by minutes (observed ~23 min for `segment-publisher`). This happens when the stream is actively being written to but CloudWatch has not yet updated the metadata timestamp. Do not stop at the stream with the highest reported `lastEventTimestamp`; scan the next 5–10 recent streams with `get_log_events` before concluding the trigger is absent. Rely on `get_log_events` timestamps, not `describe_log_streams` metadata, to determine whether a stream contains the alarm-window events.
- **When streams are already gone:** If `describe_log_streams` shows `lastEventTimestamp` already past the alarm datapoint window (often within 5–10 minutes for `segment-publisher`), the trigger stream has flushed and become inactive. `get_log_events` will also fail because the stream is no longer indexed. In this case, fall back to:
  1. Verify the daily metric sum from `get-metric-statistics` (Period=86400) to place the alarm in the 30-day baseline.
  2. Check prior verified events on the same day (from session history or other streams) to establish that the pattern completed normally.
  3. Accept a `no_action` classification if baseline is stable and no failure metric (ECS failed tasks, DLQ, Lambda Errors) is elevated, even when the exact trigger log is unreachable.
