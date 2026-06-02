# segment-publisher batch processing WARN triage

Alarm: `segment-publisher long running alam`

## Alarm shape

- **Name**: `segment-publisher long running alam` (bare name, no `/aws/ecs/.../` prefix).
- **Namespace**: `Custom/segment-publisher`
- **Metric**: `SegmentPublisher.ExecutionTimeOverThreshold`
- **Filter pattern**: `Processing took longer than expected`
- **Statistic**: `Sum`, period 300, threshold 1.0, `EvaluationPeriods=1`
- **TreatMissingData**: `missing`
- **Transition pattern**: `INSUFFICIENT_DATA → ALARM → INSUFFICIENT_DATA` (never reaches `OK`).

## Known recurrence

Daily `Sum=1.0` at roughly the same clock time for ~30 days (verified via `get_metric_statistics Period=86400`):
- Typical window: ~11:45–11:50 UTC (≈ 20:45–20:50 KST).
- Since 2026-05-14 an additional window appeared at ~06:25–06:30 UTC (≈ 15:25–15:30 KST).
- 2026-05-14 had `Sum=2.0` because both windows fired.

Alarm-history transitions are `INSUFFICIENT_DATA → ALARM → INSUFFICIENT_DATA` (never `OK`). The helper now extracts `oldState.stateValue → newState.stateValue` from `HistoryData` to count these transitions, so `alarm_count_7d` / `alarm_count_30d` will reflect actual daily alarm occurrences (e.g. `30일: 33회 / 7일: 10회`). They can be used directly for the `빈도` field. Cross-check with `get_metric_statistics Period=86400 Sum` if the helper transition counts look unexpectedly high.

## Root cause

A single large-batch `segment-publisher` ECS task processes a heavy campaign (e.g. 800k+ recipients) and the total batch duration exceeds an internal threshold. The emitted log is:

```
[WARN] Processing took longer than expected: <duration_ms> ms
```

preceded by:

```
Total processing time: <duration_ms> ms
```

- No ERROR logs co-occur.
- Memory (`[MEMORY USAGE REPORT] rss`) is frequently below the ECS task limit (3072 MB), but large multi-campaign batches can push it well above the limit (observed **4655 MB** on 2026-05-24 for melting `k6bkO6`). The container does not necessarily OOM-kill; swap-driven latency may contribute to the total batch time.
- The task continues publishing recipients normally; batch index increments.

## Scope extraction

The triggering stream varies per invocation (different ECS tasks handle different batches). To find the campaign/project:

1. Identify the active stream around the alarm-datapoint time via `describe_log_streams(orderBy='LastEventTime', descending=True)`. For large-batch tasks the trigger stream may be ranked 5th–10th because it finishes earlier than smaller active tasks; see the `ecs-log-manual-trace.md` reference.
2. Use `get_log_events` on that stream bounded to the alarm window (±5 min).
   - **AWS CLI v2 pitfall**: use `--no-start-from-head` instead of `--start-from-head false`.
3. Look for:
   - `campaignId: <id>` lines.
   - `Received event` JSON containing `project_id`, `campaigns[].id`, and especially a `user_journeys` array.
   - `project_id` and `campaign_id` in structured `Used user property names in message:` or `Used user property names in segments:` logs.
   - **User-journey fast check**: when `Received event` contains `"schedule_type":"user_journey"`, the top-level `campaignId` in the same payload refers to the user journey ID (e.g. `UL1T00`). Extract the actual name/ID from the `user_journeys` array, not from the `campaigns` array.
4. Map `project_id` via DynamoDB `project` table.

When the `Received event` payload contains `"schedule_type": "user_journey"` and a `user_journeys` array, report the scope as **user journey** (mutually exclusive with campaign), using the ID from the array.

Observed projects/campaigns in recent triggers (scope varies by day because `UL1T00` is not globally unique):
- **`melting`** / `k6bkO6` (2026-05-24 06:29 UTC, ~30.4 min, multi-campaign batch, rss peaked at **4655 MB**)
- `melting` / `k6bkO6` (2026-05-15 06:30 UTC, ~31.4 min)
- `proudp` / `UL1T00` (2026-05-14 11:52 UTC, ~53.6 min, 884k recipients)
- `stepup` / `UL1T00` (2026-05-16 11:47 UTC, ~52.3 min, 885k recipients, **user journey** `[만보기] 매일 적립 리마인드`)
- `proudp` / `UL1T00` (2026-05-19 11:51 UTC, ~52.3 min, 887,991 recipients)
- `stepup` / `UL1T00` (2026-05-25 11:55 UTC, ~56.5 min, 891,998 recipients, **user journey** `[만보기] 매일 적립 리마인드`)

**Scope-attribution caveat**: The same campaign/user journey ID (`UL1T00`) has appeared under different projects on different days. Always extract the current alarm-window `project_id` from the ECS log stream (e.g., from `Used user property names in message:` JSON or inline `project_id`/`campaignId` structured lines), then map it via DynamoDB `project`, and finally determine whether `resource_type` is `campaign` or `user_journey`. Never scope by campaign/user journey ID alone.

## Classification

- **`no_action`** — predictable scheduled-batch latency. The alarm is a batch-duration canary, not a failure signal.
- Only elevate to `needs_fix` if:
  - Durations start trending upward over multiple days (e.g. consistently > 60 min).
  - ERROR logs or OOM-kills appear alongside the WARN.
  - The second daily window (~06:30 UTC) continues to grow in frequency beyond the known two-a-day pattern.

## Investigation commands

```bash
# Verify daily recurrence (use Sum because alarm history lacks OK→ALARM)
aws cloudwatch get-metric-statistics \
  --namespace Custom/segment-publisher \
  --metric-name SegmentPublisher.ExecutionTimeOverThreshold \
  --start-time 2026-05-08T00:00:00Z \
  --end-time 2026-05-15T07:00:00Z \
  --period 86400 --statistics Sum --region ap-northeast-2

# Find recent streams
aws logs describe-log-streams \
  --log-group-name /aws/ecs/notifly-services-prod/segment-publisher \
  --order-by LastEventTime --descending --limit 10 \
  --region ap-northeast-2 --query 'logStreams[].logStreamName'

# Read exact stream events when filter_log_events returns empty
aws logs get-log-events \
  --log-group-name /aws/ecs/notifly-services-prod/segment-publisher \
  --log-stream-name <stream> \
  --start-time <epoch_ms> --end-time <epoch_ms> --limit 100 \
  --region ap-northeast-2
```
