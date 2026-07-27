# segment-publisher batch processing WARN triage

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query` (historically also `segment-publisher long running alam`)

## Alarm shape

> **Architecture change:** The dedicated `segment-publisher long running alam` alarm (namespace `Custom/segment-publisher`, metric `SegmentPublisher.ExecutionTimeOverThreshold`) was removed in Terraform circa 2026-06-04 as redundant. Pattern B now arrives exclusively through the `ConsoleErrors` namespace alarm below.

**Current alarm (Pattern B superset):**
- **Name**: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`
- **Namespace**: `ConsoleErrors`
- **Metric**: `segment-publisher-prod slow eic query`
- **Filter pattern**: `took too long` (unquoted three-term AND match; catches both Pattern A and Pattern B)
- **Statistic**: `Sum`, period 60, threshold 1.0, `EvaluationPeriods=1`
- **TreatMissingData**: `missing`
- **Transition pattern**: `OK → ALARM → OK`

**Historical alarm (removed circa 2026-06-04):**
- **Name**: `segment-publisher long running alam`
- **Namespace**: `Custom/segment-publisher`
- **Metric**: `SegmentPublisher.ExecutionTimeOverThreshold`
- **Filter pattern**: `Processing took longer than expected`
- **Statistic**: `Sum`, period 300, threshold 1.0, `EvaluationPeriods=1`
- **TreatMissingData**: `missing`
- **Transition pattern**: `INSUFFICIENT_DATA → ALARM → INSUFFICIENT_DATA` (never reached `OK`)

## Known recurrence

Daily `Sum=1.0` at roughly the same clock time for ~30 days (verified via `get_metric_statistics Period=86400`):
- Typical window: ~11:45–11:50 UTC (≈ 20:45–20:50 KST).
- Since 2026-05-14 an additional window appeared at ~06:25–06:30 UTC (≈ 15:25–15:30 KST).
- 2026-05-14 had `Sum=2.0` because both windows fired.

Alarm-history transitions on the current `ConsoleErrors` alarm are `OK → ALARM → OK`. The helper counts these transitions directly from `describe-alarm-history` for the `빈도` field. Cross-check with `get_metric_statistics Period=86400 Sum` on `ConsoleErrors` / `segment-publisher-prod slow eic query` if the helper transition counts look unexpectedly high.

**Pitfall — 30일/7일 alarm_count 동일 현상**: 30일 알람 count와 7일 알람 count가 동일한 값(예: 둘 다 6회)으로 나타나는 경우, 이는 모든 알람이 최근 7일 이내에 집중 발생했음을 의미한다. `daily_alarm_counts`를 보면 실제 날짜별 분포를 확인할 수 있다. 이것이 이상 신호가 아닌지 확인하려면 30일 전체 기간 대비 최근 집중도를 체크한다. 2026-06-18~21 기간에 4일 연속 발생(총 6회) 패턴은 `class101` 대규모 다중 캠페인 배치가 정기화된 신호로, baseline 수준이다.

(The old `Custom/segment-publisher` alarm used `INSUFFICIENT_DATA → ALARM → INSUFFICIENT_DATA` before its removal circa 2026-06-04; prior session notes may reference that transition style.)

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
- Memory must be compared against the task definition revision that actually ran. The live production task definition observed on 2026-07-23 (`segment-publisher-prod:117`) reserves **98,304 MiB (96 GiB)** at task level; do not reuse the stale 3,072 MB limit from old investigations.
  - Historical RSS samples include **4,655 MB** (2026-05-24), **4,717 MB** (2026-06-02), and **7,931.58 MB** (2026-07-08).
  - These samples did not coincide with OOM/abnormal exit, and the 7.9 GB sample is well below the current 96 GiB task limit. Before claiming memory pressure, map the log stream/task to its exact task-definition revision and inspect stop reason/exit code.
- The task continues publishing recipients normally; batch index increments.

## Scope extraction

The triggering stream varies per invocation (different ECS tasks handle different batches). To find the campaign/project:

1. Identify the active stream around the alarm-datapoint time via `describe_log_streams(orderBy='LastEventTime', descending=True, limit=20)`. **Key filtering step**: Many of the returned streams have duration ~0 seconds (short-lived triggerer tasks). Filter by `(lastEventTimestamp - firstEventTimestamp) / 1000 / 60 > 5` minutes to isolate the long-running batch stream that carries the WARN line. The triggering stream is typically 16–35 minutes long and ranks 5th–15th in the `LastEventTime` ordering; it finishes and its stream closes *before* the many subsequent short tasks complete. Compute durations in Python/boto3 to avoid manual inspection of 20+ stream names.
2. Use `get_log_events` on that stream bounded to the alarm window (±5 min).
   - **AWS CLI v2 pitfall**: use `--no-start-from-head` instead of `--start-from-head false`.
3. Look for:
   - `campaignId: <id>` lines. In a multi-campaign batch you will see interleaved `campaignId: <id>, N recipients published. (batch index: N)` lines from many campaigns in the same stream.
   - `Received event` JSON containing `project_id`, `campaigns[].id`, and especially a `user_journeys` array.
     - **Multi-campaign batch**: when the payload contains `"schedule_type":"campaign"` and a `campaigns[]` array with many objects, report the dominant campaigns (or the full list if short) and the shared `project_id`.
     - **Finding `Received event`**: it is often the first line of the stream. If `get_log_events` with a time-window returns only later lines, read from the stream start with `--start-from-head` and scan the first ~20 events.
   - `project_id` and `campaign_id` in structured `Used user property names in message:` or `Used user property names in segments:` logs. These are reliable fallback scope sources when the `Received event` JSON is too long or truncated.
4. Map `project_id` via DynamoDB `project` table.

When the `Received event` payload contains `"schedule_type": "user_journey"` and a `user_journeys` array, report the scope as **user journey** (mutually exclusive with campaign), using the ID from the array.

Observed projects/campaigns in recent triggers (scope varies by day because `UL1T00` is not globally unique):
- **`class101`** / multi-campaign batch `CNGJjd`, `3KWfBG`, `VMyJo5`, `WPE9J6`, `IdxUZt`, `C5Zpf0`, `HxbGSr`, `a84kiE` (2026-06-21 05:59–06:30 UTC, ~31.2 min, **campaign**, rss ~2.0 GB; 30일/7일 각 6회)
- **`class101`** / multi-campaign batch `CNGJjd`, `C5Zpf0`, `WPE9J6`, `VMyJo5`, `3KWfBG`, `a84kiE`, `FQgbL9`, `sOk5Yk`, `IdxUZt`, `HxbGSr` (2026-06-02 06:29 UTC, ~30.3 min, **campaign**, rss peaked at **4717 MB**)
- **`melting`** / `k6bkO6` (2026-05-24 06:29 UTC, ~30.4 min, multi-campaign batch, rss peaked at **4655 MB**)
- `melting` / `k6bkO6` (2026-05-15 06:30 UTC, ~31.4 min)
- `proudp` / `UL1T00` (2026-05-14 11:52 UTC, ~53.6 min, 884k recipients)
- `stepup` / `UL1T00` (2026-05-16 11:47 UTC, ~52.3 min, 885k recipients, **user journey** `[만보기] 매일 적립 리마인드`)
- `proudp` / `UL1T00` (2026-05-19 11:51 UTC, ~52.3 min, 887,991 recipients)
- `stepup` / `UL1T00` (2026-05-25 11:55 UTC, ~56.5 min, 891,998 recipients, **user journey** `[만보기] 매일 적립 리마인드`)
- `stepup` / `UL1T00` (2026-06-09 11:56 UTC, ~56.7 min, 902,580 recipients, **user journey** `[만보기] 매일 적립 리마인드`)
- `stepup` / `UL1T00` (2026-06-10 11:54 UTC, ~55.4 min, 903,200 recipients, **user journey** `[만보기] 매일 적립 리마인드`)
- `stepup` / `UL1T00` (2026-06-11 11:54 UTC, ~55.2 min, 904,054 recipients, **user journey** `[만보기] 매일 적립 리마인드`)

**Scope-attribution caveat**: The same campaign/user journey ID (`UL1T00`) has appeared under different projects on different days. Always extract the current alarm-window `project_id` from the ECS log stream (e.g., from `Used user property names in message:` JSON or inline `project_id`/`campaignId` structured lines), then map it via DynamoDB `project`, and finally determine whether `resource_type` is `campaign` or `user_journey`. Never scope by campaign/user journey ID alone.

- **`class101`** / `7q0OMH` (2026-07-02 08:12 UTC / 17:12 KST, ~112.75 min total processing time, batch index 163, **3,783,935 recipients**, **user journey** "미구독자 Active 7d 타임딜 | korea_crm-ua_subscription_growth-dailytimedeal"). No `[MEMORY USAGE REPORT]` line found in this stream (6,068 total events scanned) and zero ERROR lines — this is the longest observed clean run so far (prior max was ~56.7 min for `stepup`/`UL1T00`), driven purely by recipient volume (3.78M), not by a code fault. Still `no_action`: no ERROR/OOM, and duration scales with recipient count as expected.
- **`class101`** / `7q0OMH` (2026-07-07 06:19–08:56 UTC / 15:19–17:56 KST, project_id `b2b4a8f879a75673b755bff42fc1deb6`, stream `prod/segment-publisher/5210fa780b2b4209a56f65dadb194871`, ~173.3 min total processing time per WARN log (`10395812.78 ms`), batch index 165, **3,787,841 recipients**, **user journey** "미구독자 Active 7d 타임딜 | korea_crm-ua_subscription_growth-dailytimedeal"). Zero ERROR lines, zero `[MEMORY USAGE REPORT]` lines in the stream. This is now the longest observed clean run (prior max ~112.75 min on 2026-07-02, same user journey). Duration continues to track recipient count (3.79M vs 3.78M, nearly identical volume) yet processing time grew ~54% (113→173 min) — worth watching if this trend continues upward on subsequent days without a proportional recipient increase, but still `no_action` for this single occurrence since there is no ERROR/OOM and the batch completed successfully.
- **`class101`** / `7q0OMH` (2026-07-09 09:44 UTC / 18:44 KST, project_id `b2b4a8f879a75673b755bff42fc1deb6`, stream `prod/segment-publisher/0e6fd33634e94366beed01ae29294abd`, ~205.6 min total processing time (`12336422.32 ms`), batch index 165, **3,788,067 recipients**, **user journey**, same "미구독자 Active 7d 타임딜" journey). Zero ERROR/OOM/MEMORY-report lines across all 6,144 scanned events. **Third consecutive occurrence with monotonically rising duration on this exact user journey: 113min (07-02) → 173min (07-07) → 206min (07-09), +54% then +19%, while recipient count stayed flat (~3.79M each time)**. Since recipient volume is not growing, the per-recipient processing cost itself is increasing — points to a code/query-side regression (e.g. `EventCounterCteManager.extract` CTE cost, DB contention, or a growing `entry_conditions`/segment filter) rather than organic traffic growth. Escalating this occurrence to **`needs_fix`**: no immediate outage, but the trend should be tracked now before it approaches the ECS task time/memory ceiling. Action target: pull Performance Insights or `pg_stat_statements` for the `EventCounterCteManager.extract` query tied to project `b2b4a8f879a75673b755bff42fc1deb6` across the three dates to confirm whether query cost (not I/O wait) is what's rising.
- **`stepup`** / `UL1T00` (2026-07-03 12:08 UTC / 21:08 KST, ~69.3 min total processing time, project_id `32d8d9d6294d52e7a5427c036b471f91`, **user journey** "[만보기] 매일 적립 리마인드", `schedule_type: "user_journey"` confirmed from `Received event` payload at stream head). Stream `prod/segment-publisher/c78cf223b1fd423b8480663eeba116e7`, active ~06:12–07:02 UTC. Continues the recurring `stepup`/`UL1T00` daily-reminder pattern first seen 2026-05-16; still within documented baseline duration range (30–113 min observed so far). `no_action`.
- **`class101`** / multi-campaign batch `1QGQZ3`, `DIk7mI`, `Zip3WO`, `WuefT1`, `lUw0zm`, `oj4x40` (2026-07-08 11:12–11:36 UTC / 20:12–20:36 KST, project_id `b2b4a8f879a75673b755bff42fc1deb6`, channel `kakao-brand-message`, stream `prod/segment-publisher/cbfc9e6447b4443aa4ae4a6299b2ae28`, ~23.5 min stream duration, `Total processing time: 2199594.11 ms` ≈ 36.7 min, **campaign** (`campaign_count: 6` at head, not user journey)). `[MEMORY USAGE REPORT] rss` peaked at **7,931.58 MB**. Full-stream scan (3,861 events) found **zero ERROR lines** and the task completed normally without an OOM-kill signal. The live task definition later verified on 2026-07-23 has a 96 GiB task-level memory limit, so this sample is not evidence of crossing the current limit; map the exact historical task-definition revision before judging headroom. Still `no_action` because there was no ERROR/OOM, while retaining the RSS value as a trend signal.
- **`stepup`** / `UL1T00` (2026-07-09 12:03 UTC / 21:03 KST, ~63.7 min total processing time (`3824344.85 ms`), project_id `32d8d9d6294d52e7a5427c036b471f91`, channel `webhook`, stream `prod/segment-publisher/cc248198e512474cacf70d921e4dc15c`, ~43.1 min stream duration, **928,554 recipients**, batch index 19, **user journey** "[만보기] 매일 적립 리마인드", `schedule_type` confirmed via `user_journeys` array in `Received event` payload at stream head). Full-stream scan (82 events) found **zero ERROR lines** and no `[MEMORY USAGE REPORT]` line. Duration/recipient count is within the established `stepup`/`UL1T00` baseline range (30–113 min observed across 885K–3.79M recipient runs on other projects; this run's 928K recipients at 63.7 min tracks consistently with the 2026-07-03 occurrence at 69.3 min for a similar recipient count). `no_action`.

**Pitfall — helper's structured scope extractor misses plain-text `campaignId: <id>` lines in `surrounding_lines`**: Unlike the JSON payload lines (`Received event`, `Used user property names in message:`), the batch-loop progress line `campaignId: <id>, N recipients published. (batch index: N)` is plain text, not JSON. The helper's `logs.current_trigger_contexts[].project_ids` and `.project_campaign_pairs` fields can come back empty (`[]`) even though this exact line is sitting in `surrounding_lines` right next to the WARN trigger. Do not conclude scope is unresolvable from empty structured fields alone — always read `surrounding_lines` verbatim for `campaignId:`/`projectId:` tokens first, then confirm the owning project and `resource_type` (`campaign` vs `user_journey`) by reading the stream from the head (`get_log_events(startFromHead=True)`) to find the `Received event:` JSON, exactly as in the "Scope extraction" steps above.

**Helper gap — `metric_filter_terms` on literal phrases**: The helper's `metric_filter_terms("took too long")` historically returned `[]` because none of the words passed the error-token heuristic, causing the fallback to search for the alarm-name-derived term `"slow eic query"` instead. This was patched in `text.py` (simple literal phrase extraction). If the helper still returns empty `current_trigger_contexts` for this alarm, the manual fallback is `filter-log-events` with `"took" "too" "long"` (three separate quoted terms) on the alarm window, then `get-log-events` on the matching stream.

## Classification

- **`no_action`** — predictable scheduled-batch latency. The alarm is a batch-duration canary, not a failure signal.
- Only elevate to `needs_fix` if:
  - Durations start trending upward over multiple days (e.g. consistently > 60 min).
  - ERROR logs or OOM-kills appear alongside the WARN.
  - The second daily window (~06:30 UTC) continues to grow in frequency beyond the known two-a-day pattern.

> Note: The old dedicated `segment-publisher long running alam` companion alarm was removed circa 2026-06-04. Classification now relies on the `ConsoleErrors` `slow eic query` alarm directly. `no_action` remains the default unless new failure signals appear.

## Investigation commands

```bash
# Verify daily recurrence on the current ConsoleErrors alarm
aws cloudwatch get-metric-statistics \
  --namespace ConsoleErrors \
  --metric-name segment-publisher-prod slow eic query \
  --start-time 2026-05-08T00:00:00Z \
  --end-time 2026-06-10T07:00:00Z \
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
