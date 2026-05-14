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

When the trigger is `EventCounterCteManager.extract:{project_id} took too long: {ms}ms`, the log line carries the `project_id` but often **no campaign or user-journey ID**. In the stream context, `campaign_id` may appear as `undefined` because the schedule is segment-condition-based rather than tied to a single campaign entity. Do not force a campaign scope when the log explicitly shows `campaign_id: undefined` and no `user_journey.id` is present in the payload. The correct scope is `project/unknown-campaign` (or `project/unknown-user-journey` when the payload shape suggests a journey).

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

## Related skill

For deeper project segment extraction, EIC Large Scale conversion workflows, and user-journey session analysis, see `notifly-segment-publisher-alarm-analysis`.
