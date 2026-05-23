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

### CloudWatch Logs filter syntax detail

The metric filter pattern `took too long` has **no quotes** in the filter configuration, so CloudWatch Logs treats it as three separate terms (`took`, `too`, `long`) that are ANDed together. CloudWatch matches each term as a **substring**, not as a whole word.

- `"took"` matches `Processing **took** longer than expected`
- `"too"` matches `Processing t**oo**k longer than expected` (substring of `took`)
- `"long"` matches `Processing took lo**ng**er than expected` (substring of `longer`)

This means `filter_log_events` with a quoted phrase `"took too long"` returns **zero** matches for the WARN line, while `"took" "too" "long"` returns the match. In manual traces, always test with the separate-term form when the metric filter pattern is unquoted.

### Known recurrence

- Pattern B: roughly daily. Two distinct daily windows observed:
  - Stepup UL1T00 (`[만보기] 매일 적립 리마인드`) at ~11:47 UTC (20:47 KST), project `32d8d9d6294d52e7a5427c036b471f91` (product `stepup`). Typically 18 batches, ~880K recipients, durations ~2977–3214 s.
  - Class101 multi-campaign batch at ~06:30 UTC (15:30 KST), project `b2b4a8f879a75673b755bff42fc1deb6` (product `class101`). Ten parallel campaigns (CNGJjd, 3KWfBG, HxbGSr, WPE9J6, VMyJo5, IdxUZt, a84kiE, FQgbL9, sOk5Yk, C5Zpf0), ~49 batches, durations ~1807–1882 s. Observed 2026-05-14 and 2026-05-15; see reference entries below.
- Pattern A: observed sporadically for munice (`031b18009978590188e49e6777447fc2`) and regather (`b57754a9497a545ab9b0e4aadd6f53b6`).

### Scope-attribution caveat for `UL1T00`
The user-journey ID `UL1T00` has been observed under **multiple projects**:
- `stepup` (`32d8d9d6294d52e7a5427c036b471f91`) on 2026-05-08, 05-10, 05-12, 05-17
- `proudp` (`bcf172129f80521a9a3b2d72b58ecb29`) on 2026-05-13

This means `UL1T00` is **not globally unique**; different projects' `user_journeys_*` shards can contain the same ID. Always use the `project_id` from the **current alarm window's** `Received event` payload or `Used user property names` block. Prior-day scoping by journey ID alone will misattribute the project when multiple customers share the same journey ID.

## Triage rule

Determine which pattern triggered the current alarm before classifying.

**If Pattern A (EventCounterCteManager.extract):**
- Scope to the project in the log line (e.g., `regather` from `event_intermediate_counts_{project_id}`).
- Classify as `needs_fix` or monitor, because it signals real DB query latency on `event_intermediate_counts`.
- The EIC table size/index health for that project is the concrete next lookup target.

**If Pattern B (plain `[WARN] Processing took longer than expected`):**
- Scope to the campaign(s) in the log. When multiple parallel campaigns are present (class101 batch), report `project/<multiple campaigns>` rather than forcing a single campaign.
- **Redundancy check:** Verify `segment-publisher long running alam` (namespace `Custom/segment-publisher`, metric `SegmentPublisher.ExecutionTimeOverThreshold`) state. If it transitioned to ALARM within the same minute, the `ConsoleErrors` `slow eic query` alarm is catching the same benign log line.
- Classify as `no_action` because it is a known recurring pattern with no delivery failure or data loss.
- Note the metric-filter name mismatch in the final answer when it helps explain the noise.

**If the log instead shows an actual unhandled exception, DB error, or dead-letter event:**
- Treat that as the real signal and re-evaluate regardless of which parent pattern it resembles.

## Session evidence

- **2026-05-07 11:50 KST ALARM**: Metric datapoint 1.0 at 11:49:00 UTC, log line `[WARN] Processing took longer than expected: 3025296.53 ms` at 11:49:49.527 UTC. This is Pattern B (batch processing in `sqs_publisher.ts`), not Pattern A (slow EIC query). Scope: proudp/UL1T00 (~879K recipients). The log timestamp (11:49:49) falls inside the CloudWatch metric period 11:49:00–11:49:59, which the alarm evaluated at 11:50:21 UTC.
- Pattern A was also present earlier the same day (10:50:04 and 10:53:37 UTC for regather, ~128s), but those triggered separate ALARM transitions (10:51 and 10:54). The 11:50 transition is unequivocally Pattern B.
- **2026-05-08 20:48 KST ALARM**: Metric datapoint 1.0 at 11:48:00 UTC, log line `[WARN] Processing took longer than expected: 2977275.38 ms` at 11:48:56.538 UTC. This is Pattern B, not Pattern A. Scope: stepup/UL1T00 (~880K recipients). The log timestamp (11:48:56) falls inside the metric period 11:48:00–11:48:59, evaluated at 11:49:21 UTC.

## 2026-05-08 session — `segment-publisher long running alam`

Alarm: `segment-publisher long running alam`  
Metric filter: `Processing took longer than expected` on `/aws/ecs/notifly-services-prod/segment-publisher`  
Metric: `Custom/segment-publisher` / `SegmentPublisher.ExecutionTimeOverThreshold`

Evidence:
- Trigger log (2026-05-08 11:48:56.538 UTC): `[WARN] Processing took longer than expected: 2977275.38 ms`
- Same-stream context: `campaignId: UL1T00, 880029 recipients published. (batch index: 18)`
- Received event payload confirms schedule type `user_journey` with name `[만보기] 매일 적립 리마인드`. Project mapping from the same stream: `project_id: 32d8d9d6294d52e7a5427c036b471f91` → DynamoDB `project` table → product `stepup`.
- Daily recurrence: exactly 1 match per day for the last 7 days (2026-05-01 through 2026-05-08), durations ~2993–3025 s (~49.8–50.4 min)
- This is a total-batch-processing WARN, not a slow EIC query and not an error.

Triage: `no_action` if publish completes and no DLQ/ECS failure. The `Custom/segment-publisher` alarm (`segment-publisher long running alam`) is the correct metric for this pattern; the `ConsoleErrors` `slow eic query` metric on the same log group is redundant for Pattern B.

## 2026-05-09 session — `segment-publisher long running alam` recurrence

Alarm: `segment-publisher long running alam`  
Transition: `INSUFFICIENT_DATA -> ALARM` at 2026-05-09 11:50:03 UTC  
Datapoint: `Sum=1.0` at 2026-05-09 11:45:00 UTC  
30-day metric history: continues the exact daily 1-dp recurrence (2026-04-09 through 2026-05-09, every day `Sum=1.0`)

Investigation note:
- The exact trigger log for the 11:45 UTC datapoint was not retrieved in this session because the manual `filter-log-events` window was anchored to the Slack `message_ts` rather than the CloudWatch `StateReasonData.startDate` timestamp. This reproduced the timestamp-derivation pitfall now documented in `SKILL.md`.
- Alarm history, metric pattern (exactly 1 per day at ~11:48–11:50 UTC), and prior session evidence strongly indicate this is the same Pattern B (batch-processing WARN in `sqs_publisher.ts`).
- Classification: `no_action`.

## 2026-05-10 session — `segment-publisher long running alam` recurrence

Alarm: `segment-publisher long running alam`  
Transition: `INSUFFICIENT_DATA -> ALARM` at 2026-05-10 11:52:03 UTC  
Datapoint: `Sum=1.0` at 2026-05-10 11:47:00 UTC (metric period 300s)

Evidence:
- Trigger log (2026-05-10 11:51:53.215 UTC): `[WARN] Processing took longer than expected: 3150574.29 ms`
- Same-stream context: 18 batches, final count `campaignId: UL1T00, 881595 recipients published.`
- Received event payload (2026-05-10 11:39:22 UTC) shows `schedule_type: "user_journey"`, id `UL1T00`, name `[만보기] 매일 적립 리마인드`.
- Project explicit in stream: `project_id: 32d8d9d6294d52e7a5427c036b471f91` → DynamoDB `project` → product `stepup`.
- Daily recurrence continues: 30d=30, 7d=7, 1d=1 exactly at ~11:47–11:52 UTC each day. Durations ~2977–3150 s (~49.6–52.5 min).
- This is the exact same Pattern B as 2026-05-08 and 2026-05-09; the WARN source is `sqs_publisher.ts:55` and total processing time is dominated by large-scale user-journey recipient publishing.

Triage: `no_action`.

## 2026-05-10 session — `segment-publisher slow eic query` ALARM

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`  
Transition: `OK -> ALARM` at 2026-05-10 11:52:21 UTC  
Datapoint: `Sum=1.0` at 2026-05-10 11:45:00 UTC  
30-day alarm history: 3 ALARM transitions total (2026-05-08, 2026-05-09, 2026-05-10) — exactly one per day.

Evidence:
- Trigger log (2026-05-10 11:38:33 UTC): `[WARN] Processing took longer than expected: 3150574.29 ms`
- Same-stream context: `campaignId: UL1T00, 881595 recipients published. (batch index: 18)`
- Project mapping from earlier payload in the same stream: `project_id: 32d8d9d6294d52e7a5427c036b471f91` → DynamoDB `project` table → product `stepup`
- Campaign name confirmed: `[만보기] 매일 적립 리마인드`
- This is unequivocally Pattern B (batch-processing WARN in `sqs_publisher.ts`), not Pattern A (slow EIC query).

**Investigation note — stream tail first:**
- `filter-log_events` with both three-term and quoted patterns returned zero matches in the expected time window because the segment-publisher Fargate task creates short-lived log streams that flush and become inactive quickly.
- The actual trigger was found by calling `get_log_events` with `startFromHead=False` and a small `limit` on recently active streams from `describe_log_streams`, then scanning the tail events manually.
- See `references/ecs-log-manual-trace.md` § "Stream-first tail check for short-lived ECS tasks" for the exact fallback.

Classification: `no_action` (publish completed, no DLQ/ECS failure, no customer impact).

## 2026-05-12 session — `segment-publisher long running alam` recurrence

Alarm: `segment-publisher long running alam`  
Transition: `INSUFFICIENT_DATA -> ALARM` at 2026-05-12 11:51:05 UTC  
Datapoint: `Sum=1.0` at 2026-05-12 11:46:00 UTC (metric period 300s)

Evidence:
- Trigger log (2026-05-12 11:50:32.098 UTC): `[WARN] Processing took longer than expected: 3077274.25 ms`
- Same alarm-window window has **zero ERROR logs**; only the single WARN line.
- 30-day metric history (`Custom/segment-publisher` / `SegmentPublisher.ExecutionTimeOverThreshold`, `Period=86400`, `Statistics=Sum`): exactly **1.0 every day** from 2026-04-12 through 2026-05-12 (31 consecutive days). No missed days.
- Daily timing: consistently ~11:44–11:50 UTC (20:44–20:50 KST), durations ~2977–3150 s (~49.6–52.5 min).
- Alarm history transitions are all `INSUFFICIENT_DATA -> ALARM` (no `OK` state), because `TreatMissingData: missing` and the metric only emits when the log line appears. Between daily runs the alarm lapses to `INSUFFICIENT_DATA`.
- This matches the exact same Pattern B (`sqs_publisher.ts` batch-processing WARN) seen on 2026-05-08 through 2026-05-10.

Scope note: the single WARN line in this window carries no explicit campaign or project ID because the log line is emitted from `sqs_publisher.ts:55` as a summary. Prior sessions on adjacent days have scoped this to `stepup/UL1T00` (`[만보기] 매일 적립 리마인드`). When the exact trigger log has no IDs but the daily baseline is stable and prior days are already scoped, it is acceptable to scope by prior-day evidence rather than forcing "unknown."

Classification: `no_action`. The 31-day perfect-daily recurrence with no ERROR coexistence confirms this is expected batch-processing latency, not an incident signal.

## 2026-05-13 session — `segment-publisher long running alam` recurrence

Alarm: `segment-publisher long running alam`  
Transition: `INSUFFICIENT_DATA -> ALARM` at 2026-05-13 11:52:05 UTC  
Datapoint: `Sum=1.0` at 2026-05-13 11:47:00 UTC (metric period 300s)

Evidence:
- Trigger log (2026-05-13 11:51:28.295 UTC, stream `prod/segment-publisher/c9fe3be5756443f1939616fc2d870d19`): `[WARN] Processing took longer than expected: 3104158.19 ms`
- Same-stream context: 18 batches, final `campaignId: UL1T00, 883481 recipients published.`
- Stream context also shows other campaigns processed in the same batch window: `6329de`, `97jnMs`, `KcYBdd`, `RcwWiz`, `XTFSnB`, `Yo1ztf`, `z1IGNh`.
- Project explicit in stream via `Used user property names in segments/message` blocks: `project_id: bcf172129f80521a9a3b2d72b58ecb29` → DynamoDB `project` → product `proudp`.
- Zero ERROR logs in the entire alarm window (2026-05-13 10:55–11:57 UTC); only the single WARN line.
- Daily recurrence continues: 30d=30, 7d=7, 1d=1 exactly at ~11:47–11:52 UTC each day. Durations ~2977–3150 s.
- Helper reproduced the literal-substring gap: `logs.skipped: "no stable filter terms inferred"` for metric filter pattern `Processing took longer than expected`. Manual `filter-log-events` with the exact literal string confirmed the trigger.

Classification: `no_action`. WARN threshold (30 min) is lower than actual large-batch processing time (~51 min). No delivery failure or DLQ signal.

## 2026-05-12 session — `segment-publisher slow eic query` ALARM (ConsoleErrors)

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`  
Transition: `OK -> ALARM` at 2026-05-12 11:51:39 UTC (KST 20:51)  
Datapoint: `Sum=1.0` at 2026-05-12 11:50:00 UTC (metric period 60s)

Evidence:
- Trigger log (2026-05-12 11:50:32.098 UTC, stream `prod/segment-publisher/b5d7054cea2946828d9a1348907db758`): `[WARN] Processing took longer than expected: 3077274.25 ms`
- Same-stream context: 18 batches, final count `campaignId: UL1T00, 883089 recipients published.`
- Received event payload shows `schedule_type: "user_journey"`, id `UL1T00`, name `[만보기] 매일 적립 리마인드`.
- Project explicit in stream: `project_id: 32d8d9d6294d52e7a5427c036b471f91` → DynamoDB `project` → product `stepup`.
- The stream was found via stream-first tail check after the most-recent-by-`lastEventTimestamp` stream (`b23df5aa70da498eb30e23fb9dc138b8`) contained no trigger; `describe_log_streams` had reported `lastEventTimestamp=11:27:48` for `b5d7054cea2946828d9a1348907db758`, but `get_log_events` revealed events up to 11:50:32, exposing stale metadata.
- Daily metric sum (`ConsoleErrors` `segment-publisher-prod slow eic query`, `Period=86400`): 79 total over 30 days, 12 over 7 days, 1 today. Baseline 1–7/day.
- This is the same Pattern B (`sqs_publisher.ts` batch-processing WARN) that fired on the companion `Custom/segment-publisher` `segment-publisher long running alam` minutes earlier. Two alarms fire for the same benign log line.

Classification: `no_action` — publish completed, no DLQ/ECS failure, no customer impact. The `ConsoleErrors` alarm is functionally redundant for Pattern B.

## 2026-05-13 session — `segment-publisher slow eic query` ALARM (ConsoleErrors)

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`  
Transition: `OK -> ALARM` at 2026-05-13 11:52:39 UTC (KST 20:52)  
Datapoint: `Sum=1.0` at 2026-05-13 11:51:00 UTC (metric period 60s)

Evidence:
- Trigger log (2026-05-13 11:51:28 UTC, stream `prod/segment-publisher/c9fe3be5756443f1939616fc2d870d19`): `[WARN] Processing took longer than expected: 3104158.19 ms`
- Same-stream context: 18 batches, final count `campaignId: UL1T00, 883481 recipients published.`
- Received event payload shows `schedule_type: "user_journey"`, id `UL1T00`, name `[만보기] 매일 적립 리마인드`.
- Project explicit in stream: `project_id: 32d8d9d6294d52e7a5427c036b471f91` → DynamoDB `project` → product `stepup`.
- Stream discovery note: `describe_log_streams` reported `lastEventTimestamp=2026-05-13T11:23:19Z` for this stream, but `get_log_events` revealed events up to 11:51:28 UTC — a ~28-minute metadata lag. The stream was found only by scanning all streams with `lastEventTimestamp >= 11:00 UTC` and checking tails, not by examining the top 1–3 most recent streams (which had `lastEventTimestamp` up to 11:49:35 UTC but did not contain the trigger).
- Daily metric sum (`ConsoleErrors` `segment-publisher-prod slow eic query`, `Period=86400`): 2026-05-13=1, 05-12=3, 05-11=5. 30-day baseline remains 1–7/day.
- This is unequivocally Pattern B (`sqs_publisher.ts` batch-processing WARN), not Pattern A (slow EIC query).

Classification: `no_action` — publish completed, no DLQ/ECS failure, no customer impact.

## 2026-05-11 session — `segment-publisher slow eic query` ALARM (Pattern A), 06:34 UTC

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`  
Transition: `OK -> ALARM` at 2026-05-11 06:34:21 UTC (KST 15:34)  
Datapoint: `Sum=1.0` at 2026-05-11 06:33:00 UTC

Evidence:
- Trigger log (2026-05-11 06:33:52.808 UTC): `EventCounterCteManager.extract:031b18009978590188e49e6777447fc2 took too long: 63401ms`
- This is **Pattern A** (actual slow EIC query), not Pattern B.
- Project mapping: `project_id: 031b18009978590188e49e6777447fc2` → DynamoDB `project` → product `munice`.
- Schedule context setup completed ID: `f72d9080259a4abdafa5d443d5924496`.
- Campaign/user journey scope could not be narrowed: `user_journeys_031b...` had no matching ID; `scheduled_messages_031b...` also no match; logs showed `campaign_id: undefined`.
- The batch continued normally after the slow query log (`Schedule context setup completed` followed by standard publishing steps).
- Classification: `no_action` because the alarm metric filter is broad and catches mostly Pattern B noise; this isolated Pattern A spike completed without delivery failure.

## 2026-05-11 session — `segment-publisher slow eic query` ALARM (Pattern A), 11:02 UTC

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`  
Transition: `OK -> ALARM` at 2026-05-11 11:02:21 UTC (KST 20:02)  
Datapoint: `Sum=1.0` at 2026-05-11 11:01:00 UTC

Evidence:
- Trigger log (2026-05-11 11:01:55.178 UTC): `EventCounterCteManager.extract:031b18009978590188e49e6777447fc2 took too long: 63876ms`
- Project mapping: same `031b18009978590188e49e6777447fc2` → product `munice`.
- Stream context shows `Schedule context setup completed b563e7a844804442847f46ea6e2243b8` and then standard publishing batches (344→3020 recipients).
- `campaign_id: undefined` in log; schedule is segment-condition-driven, not a named campaign.
- Classification: `no_action` — query completed, batch publishing finished, no recipient loss.

## 2026-05-11 session — `segment-publisher slow eic query` ALARM (Pattern A), 11:08 UTC

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`  
Transition: `OK -> ALARM` at 2026-05-11 11:08:21 UTC (KST 20:08)  
Datapoint: `Sum=1.0` at 2026-05-11 11:07:00 UTC

Evidence:
- Trigger log (2026-05-11 11:07:03.852 UTC, stream `prod/segment-publisher/b424b4efffeb46b98dbd96b53dda8858`): `EventCounterCteManager.extract:031b18009978590188e49e6777447fc2 took too long: 67210ms`
- Project mapping: `project_id: 031b18009978590188e49e6777447fc2` → DynamoDB `project` → product `munice`.
- Same-stream context: schedule context setup completed `9827cde1d7334a48b1e4f46b1c3ecd6e`, then standard publishing batches (344→2683 recipients, 8 batches).
- `campaign_id: undefined`; schedule is segment-condition-driven.
- Classification: `no_action` — query completed, batch publishing finished, no recipient loss.

## 2026-05-11 session — `segment-publisher slow eic query` ALARM (Pattern A), 11:14 UTC

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`  
Transition: `OK -> ALARM` at 2026-05-11 11:15:21 UTC (KST 20:15)  
Datapoint: `Sum=1.0` at 2026-05-11 11:14:00 UTC

Evidence:
- Trigger log (2026-05-11 11:14:21 UTC, stream `prod/segment-publisher/88330228c9d84107855c363e77121bd6`): `EventCounterCteManager.extract:031b18009978590188e49e6777447fc2 took too long: 61786ms`
- Project mapping: `project_id: 031b18009978590188e49e6777447fc2` → DynamoDB `project` → product `munice`.
- Same-stream context: schedule context setup completed `37252857851147688a09f6313c675ec2`, then standard publishing batches up to 8,759 recipients.
- `campaign_id: undefined`; schedule is segment-condition-driven.
- Classification: `no_action` — query completed, batch publishing finished, no recipient loss.

Note: This was the fourth verified Pattern A occurrence for `munice` on 2026-05-11. Daily `Sum` for 2026-05-11 was later updated to **5.0 total** (see the 11:53 UTC entry below); the fifth occurrence could not be verified because the Fargate log stream had already flushed.

## 2026-05-11 session — `segment-publisher slow eic query` ALARM, 11:53 UTC

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`  
Transition: `OK -> ALARM` at 2026-05-11 11:53:21 UTC (KST 20:53)  
Datapoint: `Sum=1.0` at 2026-05-11 11:52:00 UTC

Investigation note:
- `filter-log-events` across the alarm window returned zero matches because segment-publisher Fargate tasks create short-lived log streams that become inactive within minutes of task stop. By the time of investigation, the 11:52 UTC datapoint window had no active stream.
- Daily metric sum for 2026-05-11 is **5.0 total**. Four of the five were verified as Pattern A (`EventCounterCteManager.extract:031b18009978590188e49e6777447fc2 took too long`) for munice; the fifth (this alarm) is consistent with the same daily baseline but could not be verified as Pattern A vs Pattern B due to the expired log window.
- Classification: `no_action` based on (1) the 30-day baseline of 1–7/day, (2) the four verified munice Pattern A events on the same day all completed normally with no recipient loss, and (3) no ECS failure or DLQ signal.

### Pattern A scope-attribution note

When the trigger is `EventCounterCteManager.extract:{project_id} took too long: {ms}ms`, the log line carries the `project_id` but often **no campaign or user-journey ID**. In the stream context, `campaign_id` may initially appear as `undefined` because the schedule is segment-condition-based rather than tied to a single campaign entity. However, check the same stream tail within the next few seconds after the slow-query log; `campaign_id` may appear in `shouldExtractOnlyUsedProperties` or `Schedule context setup completed` lines before batch publishing begins (e.g., munice `zmmqWA` on 2026-05-21). If still absent, do not force a campaign scope. The correct scope is `project/unknown-campaign` (or `project/unknown-user-journey` when the payload shape suggests a journey).

If a single day jumps to >10 or the weekly total doubles versus the 30-day mean, treat it as `needs_fix` and inspect the dominant project in that window. Otherwise, `no_action` is appropriate. The 2026-05-12 count (1) is well within the 1–7 baseline.

Example daily counts observed (updated 2026-05-13):

```
2026-04-13=7, 04-14=3, 04-15=2, 04-16=3, 04-17=4, 04-18=1,
04-19=1, 04-20=5, 04-21=3, 04-22=2, 04-23=3, 04-24=6, 04-25=2, 04-26=2,
04-27=4, 04-28=3, 04-29=5, 04-30=2, 05-01=1, 05-02=3, 05-03=1, 05-04=2,
05-05=1, 05-06=1, 05-07=3, 05-08=1, 05-09=1, 05-10=1, 05-11=5, 05-12=3,
05-13=1
```

If a single day jumps to >10 or the weekly total doubles versus the 30-day mean, treat it as `needs_fix` and inspect the dominant project in that window. Otherwise, `no_action` is appropriate. The 2026-05-11 count (5) is within the 1–7 baseline range but higher than the recent 1–3/day trend, so monitor for sustained elevation rather than treating it as an isolated anomaly. The 2026-05-13 count (1) is normal baseline.

The `check` helper derives Logs Insights filter terms from the alarm/metric name (`slow eic query`) rather than the metric filter pattern (`took too long`). This causes `count_7d` and `count_30d` to return 0 even when actual matches exist. Use the bounded manual trace in `references/ecs-log-manual-trace.md` with the exact metric filter pattern `took too long` when the helper reports empty current trigger contexts for this alarm.

A second gap was observed for `segment-publisher long running alam` (filter pattern `Processing took longer than expected`): the helper reported `logs.skipped: "no stable filter terms inferred"` even though the pattern is a stable literal substring. When this happens, use the exact literal string in a bounded Logs Insights query rather than treating zero helper counts as absence of logs.

## 2026-05-14 session — `segment-publisher long running alam` recurrence (class101 multi-campaign batch)

Alarm: `segment-publisher long running alam`  
Transition: `INSUFFICIENT_DATA -> ALARM` at 2026-05-14 06:30:05 UTC  
Datapoint: `Sum=1.0` at 2026-05-14 06:23:00 UTC (metric period 300s)

Evidence:
- Trigger log (2026-05-14 06:29:34 UTC, stream `prod/segment-publisher/dd5861af15ce4d9e87e45630a860ced6`): `[WARN] Processing took longer than expected: 1807631.93 ms`
- Same-stream context: 49 batches total for 10 parallel campaigns (CNGJjd, 3KWfBG, HxbGSr, WPE9J6, VMyJo5, IdxUZt, a84kiE, FQgbL9, sOk5Yk, C5Zpf0). Final batch: `campaignId: 3KWfBG, 617 recipients published. (batch index: 49)`.
- Project explicit in stream `Received event` payload: `project_id: b2b4a8f879a75673b755bff42fc1deb6` → DynamoDB `project` → product `class101`.
- Zero ERROR logs in the alarm window; only the single WARN line.
- Daily recurrence: 30d=31, 7d=8, 1d=2. Continues the exact daily 1-dp pattern from 2026-04-14 through 2026-05-14 with no missed days. Timing today shifted earlier (~06:23 UTC) compared to the usual ~11:47 UTC window.

Scope note: this is the first observed Pattern B instance where the triggering batch contains **10 concurrent small campaigns** rather than a single large user journey (e.g., stepup `UL1T00`). The WARN comes from total parallel processing time in `sqs_publisher.ts`, not from a slow `event_intermediate_counts` query. When multiple campaign IDs are present and no single campaign dominates the batch, scope should be reported as `project/<multiple campaigns>` rather than forcing a single campaign.

Classification: `no_action`. Publish completed normally, no DLQ/ECS failure.

## 2026-05-14 session — mixed-pattern day (`slow eic query` triggers twice, Pattern A + Pattern B)

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`  
Transition 1: `OK -> ALARM` at 2026-05-14 03:59:39 UTC (KST 12:59), recovered 04:00:39 UTC  
Datapoint 1: `Sum=1.0` at 2026-05-14 03:58:00 UTC  
Transition 2: `OK -> ALARM` at 2026-05-14 06:30:39 UTC (KST 15:30), recovered 06:31:39 UTC  
Datapoint 2: `Sum=1.0` at 2026-05-14 06:29:00 UTC

Evidence — Transition 1 (Pattern A):
- Trigger log (2026-05-14 03:58:13.920 UTC, stream `prod/segment-publisher/280ff091-7ae7-4723-b5b2-bc8a6bf1afad`): `EventCounterCteManager.extract:031b18009978590188e49e6777447fc2 took too long: 60929ms`
- Project: `031b18009978590188e49e6777447fc2` → DynamoDB `project` → product `munice`
- This is an actual slow EIC query (Pattern A).

Evidence — Transition 2 (Pattern B, the Slack-delivered alert):
- Trigger log (2026-05-14 06:29:34.929 UTC, stream `prod/segment-publisher/dd5861af15ce4d9e87e45630a860ced6`): `[WARN] Processing took longer than expected: 1807631.93 ms`
- Same-stream context: 49 batches across 10 concurrent campaigns (CNGJjd, 3KWfBG, HxbGSr, WPE9J6, VMyJo5, IdxUZt, a84kiE, FQgbL9, sOk5Yk, C5Zpf0). Final batch: `campaignId: 3KWfBG, 617 recipients published. (batch index: 49)`.
- Project explicit in `Received event` payload: `project_id: b2b4a8f879a75673b755bff42fc1deb6` → DynamoDB `project` → product `class101`.
- Zero ERROR logs in the alarm window; only the single WARN line.
- This is **Pattern B** (batch-processing WARN in `sqs_publisher.ts`), not Pattern A.
- Memory pressure observed: rss peaked at **3616 MB** during the batch, exceeding the ECS task memory limit of **3072 MB** (`taskDefinition: segment-publisher-prod` revision 5). The container did not OOM-kill, suggesting swap usage.

### Redundancy with `segment-publisher long running alam`
- The dedicated `segment-publisher long running alam` (namespace `Custom/segment-publisher`, metric `SegmentPublisher.ExecutionTimeOverThreshold`) also transitioned `INSUFFICIENT_DATA -> ALARM` at 06:30:05 UTC for the same underlying WARN line.
- The `ConsoleErrors` `slow eic query` alarm caught the same log via the metric filter `took too long`, because CloudWatch substring tokenization matches `too` inside `took` and `long` inside `longer`.
- This confirms the `ConsoleErrors` alarm is functionally redundant for Pattern B and adds metric-filter noise.

### Mixed-pattern day triage rule
When a broad metric-filter alarm fires **more than once on the same day**, always verify the **exact log line that maps to the most recent datapoint** before classifying. Do not assume the most recent transition shares the same pattern as the first transition of the day. The `slow eic query` alarm on 2026-05-14 had one Pattern A episode and one Pattern B episode; conflating them would misattribute root cause and scope.

Classification (Transition 2, Slack alert): `no_action` — publish completed normally, no DLQ/ECS failure, dedicated `long running alam` already covers the same signal.

## 2026-05-14 session — `segment-publisher slow eic query` ALARM (Pattern A, munice), 15:46 KST

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`  
Transition: `OK -> ALARM` at 2026-05-14 06:46:39 UTC (KST 15:46)  
Datapoint: `Sum=1.0` at 2026-05-14 06:45:00 UTC (metric period 60s)

Evidence:
- Manual `filter-log-events` with `"took" "too" "long"` in the 06:45–07:00 UTC window found **3 Pattern A matches**, all for the same project:
  - `EventCounterCteManager.extract:031b18009978590188e49e6777447fc2 took too long: 64239ms` (06:45:01 UTC)
  - `EventCounterCteManager.extract:031b18009978590188e49e6777447fc2 took too long: 66915ms` (06:46:18 UTC)
  - `EventCounterCteManager.extract:031b18009978590188e49e6777447fc2 took too long: 63772ms` (06:47:55 UTC)
- Project mapping: `project_id: 031b18009978590188e49e6777447fc2` → DynamoDB `project` → product `munice`.
- Stream context shows `campaign_id: undefined` (segment-condition-driven schedule, not a named campaign entity).
- Zero ERROR logs in the alarm window.
- The `check` helper returned `can_answer_root_cause: false` because it derived filter terms from the alarm name (`slow eic query`) rather than the metric filter pattern (`took too long`), yielding zero Logs Insights matches. The trigger was recovered only by the bounded manual trace with the three-term filter.
- 30-day metric sum (`ConsoleErrors` `segment-publisher-prod slow eic query`, `Period=86400`, `Statistics=Sum`): 81 total. Daily count for 2026-05-14 is **5.0 total**, confirming three additional transitions on this day besides the two already documented above.
- This alarm window contained **no Pattern B** (`[WARN] Processing took longer than expected`) matches.

Investigation note — `describe_log_streams` stale timestamp pitfall:
- The top 5 most-recent streams by `lastEventTimestamp` all had first/last timestamps near **2026-05-14 06:48–06:49 UTC** (i.e., *after* the 06:45 alarm window), because the Fargate task restarted and created new streams. Streams active during 06:45–07:00 were no longer in the top-N by the time of investigation (~06:48 UTC).
- The actual trigger streams (`24a8a452...`, `5a9ddbd5...`, `a70d6cc6...`) were discovered only by scanning a broader set of streams and checking tail events.

### 2026-05-14 daily count reconciliation
The Slack-delivered alert (this session, 15:46 KST) and the prior session's Transition 2 (06:30 KST) are **separate transitions on the same day** for the same alarm. The `slow eic query` alarm on 2026-05-14 fired at least 3 times:
1. 03:59:39 UTC — Pattern A (munice)
2. 06:30:39 UTC — Pattern B (class101, documented in prior session)
3. 06:46:39 UTC — Pattern A (munice, this session)

**Updated daily counts** (2026-05-14 added):

```
2026-04-13=7, 04-14=3, 04-15=2, 04-16=0, 04-17=4, 04-18=1,
04-19=1, 04-20=5, 04-21=3, 04-22=2, 04-23=3, 04-24=6, 04-25=2, 04-26=2,
04-27=4, 04-28=3, 04-29=5, 04-30=2, 05-01=1, 05-02=3, 05-03=1, 05-04=2,
05-05=1, 05-06=1, 05-07=3, 05-08=1, 05-09=1, 05-10=1, 05-11=5, 05-12=3,
05-13=1, 05-14=5
```

Classification: `no_action` — queries completed, batch publishing finished normally (recipient counts 351→5752), no ECS failure or DLQ signal. The 3 munice Pattern A occurrences are within the 1–7/day baseline.

## 2026-05-14 session — `segment-publisher slow eic query` ALARM (Pattern B, stepup), 20:52 KST

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`  
Transition: `OK -> ALARM` at 2026-05-14 11:53:39 UTC (KST 20:53)  
Datapoint: `Sum=1.0` at 2026-05-14 11:52:00 UTC (metric period 60s)

Evidence:
- Trigger log (2026-05-14 11:52:52.241 UTC, stream `prod/segment-publisher/e74d180bca4f4e0fbf7cfdd91c8cf92d`): `[WARN] Processing took longer than expected: 3213874.92 ms`
- Same-stream context: 18 batches, final `campaignId: UL1T00, 884366 recipients published.`
- Received event payload shows `schedule_type: "user_journey"`, id `UL1T00`, name `[만보기] 매일 적립 리마인드`.
- Project explicit in stream: `project_id: 32d8d9d6294d52e7a5427c036b471f91` → DynamoDB `project` → product `stepup`.
- **2026-05-14 re-check note**: A later manual trace of the same trigger stream (`e74d180b...`) from 11:30–11:58 UTC found only `campaignId: UL1T00` lines and no `project_id` or `Received event`. The `project_id` may have been in an earlier part of the stream (<11:30 UTC) or a different concurrent stream. Because prior-day evidence for `UL1T00` is inconsistent (`stepup` on 05-08/10/12, `proudp` on 05-13), treat project scope for `UL1T00` as unreliable unless explicitly present in the current alarm window.
- Zero ERROR logs in the alarm window.
- `describe_log_streams` stale-metadata pitfall reproduced: the trigger stream (`e74d180b...`) had `lastEventTimestamp=11:31:27` in the API response, ~21 minutes behind its actual final event at 11:52:52. Scanning `limit=10` streams and checking tails with `get_log_events` found it at position #9.
- Daily recurrence continues: exact same Pattern B (`sqs_publisher.ts` batch-processing WARN) as the 2026-05-08 through 2026-05-13 stepup triggers. Durations ~2977–3214 s.
- The `segment-publisher long running alam` (namespace `Custom/segment-publisher`) also transitioned `INSUFFICIENT_DATA -> ALARM` at 11:52:05 UTC for the same underlying WARN line, confirming the two alarms are redundant for Pattern B.

Classification: `no_action` — publish completed, no DLQ/ECS failure, no customer impact.

## 2026-05-14 session — `segment-publisher long running alam` recurrence (Pattern B), 20:53 KST

Alarm: `segment-publisher long running alam`  
Transition: `INSUFFICIENT_DATA -> ALARM` at 2026-05-14 11:53:05 UTC (KST 20:53)  
Datapoint: `Sum=1.0` at 2026-05-14 11:46:00 UTC (metric period 300s)

Evidence:
- Trigger log (2026-05-14 11:52:52.241 UTC, stream `prod/segment-publisher/e74d180bca4f4e0fbf7cfdd91c8cf92d`): `[WARN] Processing took longer than expected: 3213874.92 ms`
- Same-stream context: 18 batches (index 10→18), final `campaignId: UL1T00, 884366 recipients published.`
- Zero ERROR logs in the alarm window; only the single WARN line.
- Memory pressure: rss ~318 MB, well below ECS task memory limit 3072 MB. No OOM or swap signal.

Scope note — **project_id missing in trigger stream, prior-day evidence inconsistent**:
- The trigger stream (`e74d180b...`) contained only `campaignId: UL1T00` batch lines from 11:31:27 to 11:52:52 UTC. **No `project_id` or `Received event` payload was present in this stream.**
- Other concurrent streams in the same log group carried `project_id` values such as `bcf172129f80521a9a3b2d72b58ecb29` (product `proudp`) and `e7239ea653e251ed8b0ae4aff9d9d859`, but Logs Insights confirmed those streams handled different campaigns, not UL1T00.
- Prior-day evidence for `UL1T00` is **inconsistent**:
  - 2026-05-08, 05-10, 05-12: `stepup` (`32d8d9d6294d52e7a5427c036b471f91`)
  - 2026-05-13: `proudp` (`bcf172129f80521a9a3b2d72b58ecb29`)
- Because the same `campaignId` appears under different projects on different days, **prior-day scoping is unreliable for `UL1T00`**. When the current trigger stream lacks an explicit `project_id`, the safe scope is `project unknown for campaign UL1T00`.

Daily recurrence: 30d=31, 7d=8, 1d=2, 10m=1. Continues the exact daily 1-dp pattern, though today had a second earlier occurrence at 06:23 UTC (class101, see above).

Classification: `no_action` — publish completed, no DLQ/ECS failure, no customer impact.

## 2026-05-14 session — `segment-publisher slow eic query` ALARM (Pattern A, munice), 21:41 KST

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`  
Transition: `OK -> ALARM` at 2026-05-14 12:41:39 UTC (KST 21:41)  
Datapoint: `Sum=1.0` at 2026-05-14 12:41:00 UTC (metric period 60s)  
Recovery: `ALARM -> OK` at 2026-05-14 12:42:39 UTC

Evidence:
- Trigger log (2026-05-14 12:40:42.452 UTC, stream `prod/segment-publisher/621b157cbd7749dca0f8e3eab4804b4e`): `EventCounterCteManager.extract:031b18009978590188e49e6777447fc2 took too long: 63711ms`
- Project mapping: `project_id: 031b18009978590188e49e6777447fc2` → DynamoDB `project` → product `munice`.
- Stream context: `Schedule context setup completed 6003c9499873432ba7ea54cae333694c`, then standard publishing batches (950→9,507 recipients, 8 batches).
- `campaign_id: undefined` in log; schedule is segment-condition-driven, not a named campaign entity.
- Zero ERROR logs in the alarm window.
- 30-day metric sum (`ConsoleErrors` `segment-publisher-prod slow eic query`, `Period=86400`, `Statistics=Sum`): 82 total. Daily count for 2026-05-14 is 1.0 so far (05-13 was 9.0, peak day).
- Helper reproduced the name-vs-pattern false-negative (`filter_terms: ["slow eic query"]`), returning zero Logs Insights matches. Manual `filter-log-events` with `"took" "too" "long"` recovered the trigger.

Classification: `no_action` — query completed, batch publishing finished normally, no ECS failure or DLQ signal. The munice Pattern A occurrence is within the 1–7/day baseline and followed by normal recipient publishing.

## 2026-05-15 session — `segment-publisher slow eic query` ALARM (Pattern B, class101)

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`
Transition: `OK -> ALARM` at 2026-05-15 06:31:10 UTC (KST 15:31)
Datapoint: `Sum=1.0` at 2026-05-15 06:30:00 UTC (metric period 60s)
Companion alarm: `segment-publisher long running alam` transitioned `INSUFFICIENT_DATA -> ALARM` at 2026-05-15 06:31:05 UTC.

Evidence:
- Trigger log (2026-05-15 06:30:46 UTC, stream `prod/segment-publisher/d1757014940b44d491486cce6cfbe9e1`): `[WARN] Processing took longer than expected: 1882927.67 ms`
- Same-stream context: 49 batches across 10 concurrent campaigns (CNGJjd, 3KWfBG, HxbGSr, WPE9J6, VMyJo5, IdxUZt, a84kiE, FQgbL9, sOk5Yk, C5Zpf0). Final batch indices 48 and 49.
- Received event payload (stream head): `project_id: b2b4a8f879a75673b755bff42fc1deb6` → DynamoDB `project` → product `class101`.
- `describe_log_streams` reported `lastEventTimestamp=2026-05-15T06:27:48Z` for this stream, but `get_log_events` revealed events up to 06:30:46 UTC — a ~3-minute metadata lag.
- Zero ERROR logs in the alarm window (06:00–07:00 UTC).
- Daily recurrence: 30d=12, 7d=12, 1d=1. 2026-05-14 had the identical class101 10-campaign batch. This confirms a second daily Pattern B window (~06:30 UTC for class101) distinct from the stepup UL1T00 window (~11:47 UTC).

Classification: `no_action` — publish completed, no DLQ/ECS failure, companion `long running alam` already covers same signal.

## 2026-05-17 session — `segment-publisher slow eic query` ALARM (Pattern B, stepup)

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`
Transition: `OK -> ALARM` at 2026-05-17 11:53:10 UTC (KST 20:53)
Datapoint: `Sum=1.0` at 2026-05-17 11:52:00 UTC (metric period 60s)
Companion alarm: `segment-publisher long running alam` transitioned `INSUFFICIENT_DATA -> ALARM` at 2026-05-17 11:52:05 UTC.

Evidence:
- Trigger log (2026-05-17 11:52:15 UTC, stream `prod/segment-publisher/d7e39f2d0d674abb997451750946bebd`): `[WARN] Processing took longer than expected: 3179257.95 ms`
- Same-stream context: 18 batches, final `campaignId: UL1T00, 885924 recipients published. (batch index: 18)`
- Received event payload (stream head, 2026-05-17 11:39:15 UTC) shows `schedule_type: "user_journey"`, id `UL1T00`, name `[만보기] 매일 적립 리마인드`
- Project explicit in stream via `Received event`: `project_id: 32d8d9d6294d52e7a5427c036b471f91` → DynamoDB `project` → product `stepup`
- Zero ERROR logs in the alarm window (2026-05-17 11:40–12:00 UTC); only the single WARN line.
- Alarm history pitfall reproduced: `describe-alarm-history` returned ~150 entries with `StateValue: null` and `Summary: null` over the 30-day window. ALARM transitions are countable only by parsing `HistoryData` JSON (`newState.stateValue`). 30d ALARM transitions = 25; daily recurrence continues.
- `filter-log_events` with `took too long` (unquoted three-term form) found exactly one match in the 11:40–12:00 UTC window, confirming the trigger.
- `describe_log_streams` stale-metadata pitfall reproduced: the trigger stream had `lastEventTimestamp=11:49:29` in the API response, but `get_log_events` revealed the final WARN event at 11:52:15 — a ~3-minute metadata lag.

Daily recurrence update:
- 30-day metric sum (`ConsoleErrors` `segment-publisher-prod slow eic query`, `Period=86400`, `Statistics=Sum`): 81 total over 30 days, ~1–6/day baseline.
- Today's count (2026-05-17) is 1.0.

Scope note: This session confirms `UL1T00` can appear under `stepup` on some days and `proudp` on others (see 2026-05-13 evidence). The current alarm window explicitly shows `project_id: 32d8d9d6294d52e7a5427c036b471f91` (stepup), resolving the ambiguity for this transition. Journey IDs are not globally unique across projects.

Classification: `no_action` — publish completed, no DLQ/ECS failure, companion `long running alam` already covers same signal.

## 2026-05-18 session — `segment-publisher long running alam` recurrence (class101 multi-campaign batch)

Alarm: `segment-publisher long running alam`
Transition: `INSUFFICIENT_DATA -> ALARM` at 2026-05-18 06:30:05 UTC (KST 15:30)
Datapoint: `Sum=1.0` at 2026-05-18 06:23:00 UTC (metric period 300s)

Evidence:
- Trigger log (2026-05-18 06:29:47.379 UTC, stream `prod/segment-publisher/007da2262cb04e1cb6c2a44082ec03e7`): `[WARN] Processing took longer than expected: 1814721.12 ms`
- Same-stream context: 49 batches total for 10 parallel campaigns (CNGJjd, 3KWfBG, HxbGSr, WPE9J6, VMyJo5, IdxUZt, a84kiE, FQgbL9, sOk5Yk, C5Zpf0). Final batch indices 48 and 49.
- Memory pressure: rss peaked at **3965.73 MB** during the batch, exceeding the ECS task memory limit of **3072 MB** (`taskDefinition: segment-publisher-prod` revision 5). The container did not OOM-kill, suggesting swap usage.
- Project explicit in stream `Received event` payload: `project_id: b2b4a8f879a75673b755bff42fc1deb6` → DynamoDB `project` → product `class101`.
- Zero ERROR logs in the alarm window; only the single WARN line.
- Daily recurrence: 30d=33, 7d=10, 1d=2. Today had two Pattern B occurrences: class101 at ~06:23 UTC and stepup UL1T00 at ~11:52 UTC (see separate Slack alert).
- `describe_log_streams` stale-metadata pitfall reproduced: the trigger stream had `lastEventTimestamp=06:12:57` in the API response, but `get_log_events` revealed the final WARN event at 06:29:47 — a ~17-minute metadata lag.

Classification: `no_action` — publish completed normally, no DLQ/ECS failure, dedicated `long running alam` already covers same signal.

## 2026-05-18 session — `segment-publisher slow eic query` ALARM (Pattern B, stepup)

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`
Transition: `OK -> ALARM` at 2026-05-18 11:53:10 UTC (KST 20:53)
Datapoint: `Sum=1.0` at 2026-05-18 11:52:00 UTC (metric period 60s)
Companion alarm: `segment-publisher long running alam` transitioned `INSUFFICIENT_DATA -> ALARM` at 2026-05-18 11:52:05 UTC.

Evidence:
- Trigger log (2026-05-18 11:52:03 UTC, stream `prod/segment-publisher/0bf290e7372e48f7917a0dd8a9acabfb`): `[WARN] Processing took longer than expected: 3151808.24 ms`
- Same-stream context: 18 batches, final `campaignId: UL1T00, 886858 recipients published. (batch index: 18)`
- Received event payload (stream head, 2026-05-18 11:39:15 UTC) shows `schedule_type: "user_journey"`, id `UL1T00`, name `[만보기] 매일 적립 리마인드`
- Project explicit in stream via `Received event` payload: `project_id: 32d8d9d6294d52e7a5427c036b471f91` → DynamoDB `project` → product `stepup`
- Memory pressure: rss data not present in this stream; no recurrence of the elevated-swap signal seen in class101 concurrent runs.
- `describe_log_streams` stale-metadata pitfall reproduced: the trigger stream had `lastEventTimestamp=2026-05-18T11:49:58Z` in the API response, but `get_log_events` revealed events up to 11:52:03 UTC — a ~2-minute metadata lag.
- Zero ERROR logs in the alarm window (11:45–11:58 UTC); only the single WARN line.
- Daily metric sum (`ConsoleErrors` `segment-publisher-prod slow eic query`, `Period=86400`, `Statistics=Sum`): 2026-05-18=2.0 total (class101 at 06:23 + stepup at 11:52).
- 1d=2 confirms the two-daily-window pattern that first appeared on 2026-05-14 (class101 ~06:23 + stepup ~11:52) and repeated on 2026-05-15 and 2026-05-18.

Classification: `no_action` — publish completed, no DLQ/ECS failure, companion `long running alam` already covers same signal.

## 2026-05-18 session — `segment-publisher slow eic query` ALARM (Pattern B, class101)

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`  
Transition: `OK -> ALARM` at 2026-05-18 06:30:27 UTC (KST 15:30)  
Datapoint: `Sum=1.0` at 2026-05-18 06:29:00 UTC (metric period 60s)  
Recovery: transitioned to `INSUFFICIENT_DATA` shortly after  
Companion alarm: `segment-publisher long running alam` transitioned `INSUFFICIENT_DATA -> ALARM` at 2026-05-18 06:30:05 UTC (datapoint 06:25:00 UTC).

Evidence:
- Trigger log (2026-05-18 06:29:47 UTC, stream `prod/segment-publisher/007da2262cb04e1cb6c2a44082ec03e7`): `[WARN] Processing took longer than expected: 1814721.12 ms`
- Same-stream context: 49 batches across 10 concurrent campaigns (CNGJjd, C5Zpf0, 3KWfBG, HxbGSr, WPE9J6, VMyJo5, IdxUZt, a84kiE, FQgbL9, sOk5Yk). Final batch indices 48 and 49.
- Received event payload (stream head, 2026-05-18 06:39:32 UTC) shows `project_id: b2b4a8f879a75673b755bff42fc1deb6` → DynamoDB `project` → product `class101`.
- **Memory pressure — new high**: `[MEMORY USAGE REPORT] rss` climbed from ~3900 MB through ~3920 MB during batch 48–49. The ECS task memory limit for `segment-publisher-prod` is 3072 MB (revision 5). The container did not OOM-kill, indicating swap-driven latency. Prior class101 batch on 2026-05-14 had rss peak at 3616 MB; today it reached ~3920 MB, a ~304 MB increase.
- Zero ERROR logs in the alarm window (06:24–06:34 UTC); only the single WARN line.
- Alarm name still mismatched: the `ConsoleErrors` metric filter `took too long` caught the batch-processing WARN, not a slow EIC query.
- Daily recurrence: the class101 multi-campaign batch continues at ~06:25–06:30 UTC every day (observed 2026-05-14, 05-15, and 05-18).

Classification: `no_action` — publish completed, no DLQ/ECS failure, companion `long running alam` already covers same signal.

## 2026-05-20 session — `segment-publisher slow eic query` ALARM (Pattern B, stepup)

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`
Transition: `OK -> ALARM` at 2026-05-20 11:54:46 UTC (KST 20:54)
Datapoint: `Sum=1.0` at 2026-05-20 11:53:00 UTC (metric period 60s)
Companion alarm: `segment-publisher long running alam` transitioned `INSUFFICIENT_DATA -> ALARM` at 2026-05-20 11:54:05 UTC (datapoint 11:49:00 UTC).

Evidence:
- Trigger log (2026-05-20 11:53:19 UTC, stream `prod/segment-publisher/cc1676f92a3d474c9107a78ad364501c`): `[WARN] Processing took longer than expected: 3243945.97 ms` (~54.0 min, the longest duration observed to date).
- Same-stream context: 18 batches, final `campaignId: UL1T00, 888846 recipients published. (batch index: 18)`
- `Received event` payload in the same stream head (2026-05-20 10:59:15 UTC) shows `schedule_type: "user_journey"`, id `UL1T00`, name `[만보기] 매일 적립 리마인드`
- Project explicit in stream: `project_id: 32d8d9d6294d52e7a5427c036b471f91` → DynamoDB `project` → product `stepup`
- Zero ERROR logs in the alarm window; only the single WARN line.
- Daily recurrence continues uninterrupted: 30d baseline ~1–6/day, 2026-05-20 count = 1.0.

Classification: `no_action` — publish completed, no DLQ/ECS failure, companion `long running alam` already covers same signal. Durations continue creeping upward (3243s vs ~2977s on 2026-05-08); monitor if sustained growth crosses a material threshold.

**Updated daily counts** (2026-05-21 added):

```
2026-04-13=7, 04-14=3, 04-15=2, 04-16=0, 04-17=4, 04-18=1,
04-19=1, 04-20=5, 04-21=3, 04-22=2, 04-23=3, 04-24=6, 04-25=2, 04-26=2,
04-27=4, 04-28=3, 04-29=5, 04-30=2, 05-01=1, 05-02=3, 05-03=1, 05-04=2,
05-05=1, 05-06=1, 05-07=3, 05-08=1, 05-09=1, 05-10=1, 05-11=5, 05-12=3,
05-13=1, 05-14=5, 05-15=1, 05-16=1, 05-17=1, 05-18=2, 05-19=1, 05-20=1,
05-21=6
```

## 2026-05-21 session — `segment-publisher slow eic query` ALARM (Pattern A, munice), 16:49 KST

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`
Transition: `OK -> ALARM` at 2026-05-21 07:49:46 UTC (KST 16:49)
Datapoint: `Sum=1.0` at 2026-05-21 07:48:00 UTC (metric period 60s)
Recovery: `ALARM -> OK` at 2026-05-21 07:50:46 UTC
Companion alarm: `segment-publisher long running alam` remained `INSUFFICIENT_DATA` throughout the window — confirming this is **not** Pattern B.

Evidence:
- Trigger log (2026-05-21 07:48:25 UTC, stream `prod/segment-publisher/2d2350c0129345548d555d1610a27887`): `EventCounterCteManager.extract:031b18009978590188e49e6777447fc2 took too long: 67824ms`
- Same-stream context: `Received event` payload (07:47:15 UTC) shows `projectId: 031b18009978590188e49e6777447fc2` with segment conditions on `amplitude__trial_converted`, `amplitude__subscription_renewed`, `amplitude__subscription_started`, etc. Channel: `push-notification`.
- `Schedule context setup completed cc1074a3639e423fa955325c6a183378` at 07:48:25 UTC.
- `campaign_id: undefined` in log; schedule is segment-condition-driven, not a named campaign entity.
- Standard publishing batches followed (10 batches, 352→3122 recipients).
- Zero ERROR logs in the alarm window (07:35–07:55 UTC).
- Project mapping: `project_id: 031b18009978590188e49e6777447fc2` → DynamoDB `project` → product `munice`.

Daily recurrence context:
- 2026-05-21 metric sum = 2.0 total. The second event (07:15:47 UTC, same stream form) is a second munice Pattern A occurrence.
- This is the first **clean Pattern A day** in the recent window — prior days (2026-05-17 through 05-20) were either Pattern B only or mixed-pattern days.
- The trigger time (~07:15 and ~07:48 UTC) is outside both known Pattern B windows (~06:30 UTC for class101, ~11:47 UTC for stepup), confirming this is independent batch scheduling for munice.

Classification: `no_action` — query completed, batch publishing finished normally, no ECS failure or DLQ signal. The 2 munice Pattern A occurrences are within the 1–7/day baseline.

## 2026-05-21 session — `segment-publisher slow eic query` ALARM (Pattern B, stepup), 20:54 KST

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`
Transition: `OK -> ALARM` at 2026-05-21 11:54:46 UTC (KST 20:54)
Datapoint: `Sum=1.0` at 2026-05-21 11:53:00 UTC (metric period 60s)
Recovery: `ALARM -> OK` at 2026-05-21 11:55:46 UTC
Companion alarm: `segment-publisher long running alam` transitioned `INSUFFICIENT_DATA -> ALARM` at 2026-05-21 11:54:05 UTC (datapoint 11:49:00 UTC).

Evidence:
- Trigger log (2026-05-21 11:53:09 UTC, stream `prod/segment-publisher/ae1b37bc67654c628859651af958e635`): `[WARN] Processing took longer than expected: 3233991.74 ms`
- Same-stream context: 18 batches, final `campaignId: UL1T00, 890035 recipients published. (batch index: 18)`
- Received event payload (stream head, 2026-05-21 10:59:15 UTC) shows `schedule_type: "user_journey"`, id `UL1T00`, name `[만보기] 매일 적립 리마인드`
- Project explicit in stream: `project_id: 32d8d9d6294d52e7a5427c036b471f91` → DynamoDB `project` → product `stepup`
- Zero ERROR logs in the alarm window; only the single WARN line.
- This is the stepup UL1T00 daily batch, continuing the exact same Pattern B seen since 2026-05-08.

Daily recurrence update:
- 2026-05-21 had 4 ALARM transitions total for this alarm (munice Pattern A at 07:16, 07:49, and 12:55 UTC; stepup Pattern B at 11:54 UTC). The ConsoleErrors metric daily sum = 4.0.
- Daily count baseline remains 1–7/day.

Classification: `no_action` — publish completed, no DLQ/ECS failure, companion `long running alam` already covers same signal.

## 2026-05-21 session — `segment-publisher slow eic query` ALARM (Pattern A, munice), 21:56 KST

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`
Transition: `OK -> ALARM` at 2026-05-21 12:56:46 UTC (KST 21:56)
Datapoint: `Sum=1.0` at 2026-05-21 12:55:00 UTC (metric period 60s)
Recovery: `ALARM -> OK` at 2026-05-21 12:57:46 UTC
Companion alarm: `segment-publisher long running alam` remained `INSUFFICIENT_DATA` throughout the window — confirming this is **not** Pattern B.

Evidence:
- Trigger log (2026-05-21 12:55:27.545 UTC, stream `prod/segment-publisher/54cf34398c6a43a48c1218ccfc3acf53`): `EventCounterCteManager.extract:031b18009978590188e49e6777447fc2 took too long: 60520ms`
- Same-stream context: `Received event` payload (12:54:25 UTC) shows `projectId: 031b18009978590188e49e6777447fc2`, segment conditions on `amplitude__trial_converted`, `amplitude__subscription_renewed`, `amplitude__subscription_started`, channel `push-notification`.
- `Schedule context setup completed 8e5afa88c35546a78333ac4ae9f92cd2` at 12:55:27 UTC.
- The slow query log line carries no campaign ID, but the same stream tail (12:55:27 UTC) shows `shouldExtractOnlyUsedProperties` context with `campaign_id: 'zmmqWA'` and campaign name `(푸시) (ja) 리뷰 이벤트 (구독 1차)`. This is the first documented Pattern A occurrence with an explicit munice campaign ID.
- Standard publishing batches followed (3 batches, 350→683 recipients).
- Memory pressure observed: `[MEMORY USAGE REPORT] rss` climbed from ~1906 MB through ~2997 MB during batch processing, approaching but not exceeding the ECS task memory limit of 3072 MB.
- Zero ERROR logs in the alarm window (12:40–13:00 UTC).
- `filter-log-events` with the unquoted metric filter pattern `"took" "too" "long"` would match; the Logs Insights bounded query `filter @message like /took too long/` recovered the trigger directly.
- Project mapping: `project_id: 031b18009978590188e49e6777447fc2` → DynamoDB `project` → product `munice`.

Daily recurrence context:
- 2026-05-21 daily metric sum (ConsoleErrors `segment-publisher-prod slow eic query`, `Period=86400`, `Statistics=Sum`) = **4.0 total**, the highest since 2026-05-14 (5.0). Munice contributed three Pattern A occurrences (07:16, 07:49, 12:55 UTC); stepup contributed one Pattern B (11:54 UTC).
- The munice trigger time at 12:55 UTC is outside both known Pattern B windows (~06:30 UTC class101, ~11:47 UTC stepup), confirming independent batch scheduling.

Classification: `no_action` — query completed, batch publishing finished normally, no ECS failure or DLQ signal. The three munice Pattern A occurrences are within the 1–7/day baseline.

## 2026-05-21 session — `segment-publisher slow eic query` ALARM (Pattern A, munice), 22:28 KST

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`
Transition: `OK -> ALARM` at 2026-05-21 13:28:46 UTC (KST 22:28)
Datapoint: `Sum=1.0` at 2026-05-21 13:27:00 UTC (metric period 60s)
Recovery: `ALARM -> OK` at 2026-05-21 13:29:46 UTC
Companion alarm: `segment-publisher long running alam` remained `INSUFFICIENT_DATA` throughout the window — confirming this is **not** Pattern B.

Evidence:
- Trigger log (2026-05-21 13:27:08 UTC, stream `prod/segment-publisher/99652a47df1d415da6b573d371742e73`): `EventCounterCteManager.extract:031b18009978590188e49e6777447fc2 took too long: 65220ms`
- Same-stream context: `Schedule context setup completed ce383e83defe49309042bb07943ad583` at 13:27:08 UTC.
- `project_id: '031b18009978590188e49e6777447fc2'` in the schedule context block; `campaign_id: undefined`.
- 10 standard publishing batches followed (batch indices 1–10, 349→3,131 recipients).
- Zero ERROR logs in the alarm window (13:12–13:32 UTC).
- Project mapping: `project_id: 031b18009978590188e49e6777447fc2` → DynamoDB `project` → product `munice`.
- Daily recurrence context: 2026-05-21 metric sum = 6.0 total, the highest since 2026-05-14 (5.0). This was the sixth `slow eic query` transition on 2026-05-21 (munice Pattern A at 07:16, 07:49, 12:55, 13:28, 13:37 UTC; stepup Pattern B at 11:54 UTC).

Classification: `no_action` — query completed, batch publishing finished normally, no ECS failure or DLQ signal. The five munice Pattern A occurrences on 2026-05-21 are within the 1–7/day baseline.

## 2026-05-21 session — `segment-publisher slow eic query` ALARM (Pattern A, munice), 22:38 KST

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`
Transition: `OK -> ALARM` at 2026-05-21 13:38:46 UTC (KST 22:38)
Datapoint: `Sum=1.0` at 2026-05-21 13:37:00 UTC (metric period 60s)
Recovery: `ALARM -> OK` at 2026-05-21 13:39:46 UTC
Companion alarm: `segment-publisher long running alam` remained `INSUFFICIENT_DATA` throughout the window — confirming this is **not** Pattern B.

Evidence:
- Trigger log (2026-05-21 13:37:05 UTC, stream `prod/segment-publisher/d6e6f02955dd4fa9906b4edeb5af6f05`): `EventCounterCteManager.extract:031b18009978590188e49e6777447fc2 took too long: 65353ms`
- Same-stream context: `Schedule context setup completed f5c74493899749498eb8544191f27f82` at 13:37:05 UTC.
- `project_id: '031b18009978590188e49e6777447fc2'` in the schedule context block; `campaign_id: undefined`.
- Standard publishing batches followed (10 batches, 349→3,131 recipients).
- Zero ERROR logs in the alarm window (13:30–13:45 UTC).
- Project mapping: `project_id: 031b18009978590188e49e6777447fc2` → DynamoDB `project` → product `munice`.
- Daily recurrence context: 2026-05-21 metric sum = 6.0 total. This was the sixth and final `slow eic query` transition on 2026-05-21, completing a burst of five munice Pattern A occurrences between 07:16 and 13:38 UTC.

Classification: `no_action` — query completed, batch publishing finished normally, no ECS failure or DLQ signal. The five munice Pattern A occurrences on 2026-05-21 are within the 1–7/day baseline.

## 2026-05-22 session — `segment-publisher slow eic query` ALARM (Pattern B, stepup), 20:54 KST

Alarm: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`
Transition: `OK -> ALARM` at 2026-05-22 11:54:08 UTC (KST 20:54)
Datapoint: `Sum=1.0` at 2026-05-22 11:53:00 UTC (metric period 60s)
Companion alarm: `segment-publisher long running alam` (`Custom/segment-publisher` / `SegmentPublisher.ExecutionTimeOverThreshold`, period 300) in ALARM with datapoint 1.0 at 2026-05-22 11:49:00 UTC.

Evidence:
- **Fargate log stream expiration before investigation**: The segment-publisher Fargate task that processed the 11:53 datapoint had already stopped by investigation time (~11:54 UTC). `describe_log_streams` showed the most recent stream (`83ad8133441643a7ba2371beef4c3b59`) ended at 11:54:26 UTC and contained only a 93-second sub-batch for project `e7239ea653e251ed8b0ae4aff9d9d859` (campaign `fUxoSN`), not the trigger. Streams before that ended at 11:49:27 UTC. There was a **~4-minute gap** (11:49–11:53) with no active streams in the log group, yet the metric filter demonstrably breached at 11:53.
- Logs Insights (`filter @message like /took too long/`, 11:00–12:00 UTC) scanned 879 records and matched 0 within ~300 seconds of the breach, confirming CloudWatch Logs ingestion lag even for the exact metric-filter pattern.
- Manual stream-first tail checks on all streams with `lastEventTimestamp >= 11:00 UTC` found zero `Processing took longer than expected` or `EventCounterCteManager.extract...took too long` matches in any stream ending between 11:00–11:55 UTC.
- The companion alarm `segment-publisher long running alam` was in ALARM with a datapoint at 11:49:00 UTC (period 300), evaluated at 11:54:05 UTC. Its metric filter (`Processing took longer than expected`) is the exact Pattern B signature. This is strong evidence that the `ConsoleErrors` `slow eic query` alarm caught the same benign log line.
- Daily recurrence: 30d=9, 7d=9, 1d=5, 10m=1. Continues the known baseline of 1–7/day.
- Zero ERROR logs visible in any stream in the 11:00–12:00 UTC window.

**Companion-alarm shortcut rule**: When the `slow eic query` helper returns empty `current_trigger_contexts`, manual Logs Insights/`filter_log_events` also returns zero, AND the `segment-publisher long running alam` is in ALARM with a datapoint overlapping the same time window, treat this as **Pattern B** without requiring the exact trigger log line. The `Custom/segment-publisher` alarm has a purpose-built metric filter for `Processing took longer than expected`; its ALARM state is definitive evidence that the `ConsoleErrors` alarm is catching the same benign log line.

Scope: user journey UL1T00 (`[만보기] 매일 적립 리마인드`), project unknown for this window (동일 ID가 stepup·proudp 등 다수 프로젝트에서 관찰됨; 현재 윈도우에 명시적 `project_id` 없음).

Classification: `no_action` — `ConsoleErrors` metric-filter 노이즈, companion `long running alam`이 동일 신호를 이미 커버함.

For deeper project segment extraction, EIC Large Scale conversion workflows, and user-journey session analysis, see `notifly-segment-publisher-alarm-analysis`.

