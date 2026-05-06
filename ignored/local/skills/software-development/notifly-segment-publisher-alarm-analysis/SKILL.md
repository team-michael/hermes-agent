---
name: notifly-segment-publisher-alarm-analysis
description: Investigate Notifly segment-publisher CloudWatch alarms by separating slow EIC extraction from long-running processing, mapping project IDs to products, and tracing the responsible campaign or user journey.
version: 1.0.0
author: Hermes Agent
license: MIT
---

# Notifly segment-publisher alarm analysis

Use this when a Notifly CloudWatch alert involves:
- `/aws/ecs/notifly-services-prod/segment-publisher ...`
- `slow eic query`
- `Processing took longer than expected`
- segment-publisher batch/runtime issues

## Goal

Answer three questions quickly and correctly:
1. What exact log class triggered the alarm?
2. Which `project_id` and product does it belong to?
3. Is the root cause EIC extraction, large segment extraction, or downstream user-journey/session work?

## Key learned behavior

In Notifly, the alarm named `slow eic query` may be polluted because the metric filter can be broader than the alarm name suggests.

For segment-publisher, verify the metric filters first:
- `segment-publisher-prod slow eic query` uses filter pattern `took too long`
- `segment-publisher-slow-processing-filter` uses `Processing took longer than expected`

Because the `slow eic query` alarm filter is broad, it can count both:
- `EventCounterCteManager.extract:<project_id> took too long: ...`
- other warnings containing `took/too long`

So never trust the alarm name alone.

## Workflow

### 1. Inspect the alarm and metric filters

Use CloudWatch and Logs APIs to collect:
- alarm config
- alarm history (`OK -> ALARM` count in the last 30 days)
- metric filters on `/aws/ecs/notifly-services-prod/segment-publisher`

Important check:
- if the filter is text-based and generic, classify matching logs into separate buckets before drawing conclusions.

### 2. Separate the two main warning classes

Query the log group for the last 30 days and classify by message pattern:

#### A. Slow EIC extraction
Pattern:
- `EventCounterCteManager.extract:<project_id> took too long: <duration>ms`

Extract:
- `project_id`
- `duration_ms`
- timestamp

Aggregate by `project_id`:
- hit count
- distinct days
- avg/min/max duration

#### B. Long-running processing
Pattern:
- `[WARN] Processing took longer than expected: <duration> ms`

These logs do **not** include `project_id` directly.

### 3. Resolve project_id for long-running processing

For each long-running warning:
- take the warning timestamp
- subtract the logged duration to estimate process start
- fetch events from the **same log stream** over that window

Look for:
- `project_id: '<project_id>'`
- `Received event: {"<project_id>": ...}`
- `campaignId: <id>, <n> recipients published. (batch index: <k>)`
- `"user_journeys":[{"id":"...","name":"..."` in the received payload

This same-stream correlation is the most reliable way to map long-running warnings to the responsible project and campaign/user journey.

### 4. Map project_id to product

Always resolve the product from DynamoDB `project` table:
- table name: `project`
- hash key: `id`
- useful fields: `product_id`, `name`

Report both:
- `project_id`
- product (`product_id` / `name`)

### 5. Remember Notifly table naming

PostgreSQL tables are per-project sharded:
- `table_name_${project_id}`

This lets you infer that queries touching:
- `event_intermediate_counts_${project_id}`
- `users_${project_id}`
- `device_${project_id}`
- `user_journey_sessions_${project_id}`

all belong to that same project.

### 6. Distinguish root-cause classes

#### Slow EIC extraction root cause
Typical evidence:
- `EventCounterCteManager.extract:<project_id> took too long`
- query against `event_intermediate_counts_${project_id}`
- often `GROUP BY notifly_user_id`
- often long lookback windows (`dt >= ...`) or `TRUE` without a narrowing cutoff

Check code paths:
- `packages/event-counter/src/lib/event_counter.ts`
- `packages/event-counter/src/lib/extractor.ts`
- `packages/event-counter/src/lib/event_counter_cte/query_builder.ts`
- `packages/segment-helper/src/schedule_context.ts`

Check whether the project is missing from:
- `LARGE_SCALE_PROJECTS`

### 6.1 If the fix is EIC Large Scale conversion

Use this sub-workflow when slow EIC extraction is caused by large `event_intermediate_counts_${project_id}` aggregation and the user asks whether/how to convert a project to Large Scale.

Important distinction: Notifly has **two different Large Scale switches**:

1. **EIC/EventCounter Large Scale**
   - file: `packages/common/src/constants.ts`
   - constant: `LARGE_SCALE_PROJECTS`
   - selected in: `packages/segment-helper/src/schedule_context.ts`
   - executed in: `packages/event-counter/src/lib/extractor.ts`
   - effect: split event counter extraction into recent Postgres + old Athena/S3 data

2. **ProjectSegmentPublisher Large Scale**
   - file: `services/task/segment-publisher/lib/segment/segment_publisher.ts`
   - hard-coded `this.isLargeScale` allowlist
   - effect: users-first extraction and chunked device lookup instead of joining `device_${project_id}` to `users_${project_id}` up front

Do not assume one implies the other. For example, `511f0143084f55fa85a71f776455d58c` / `mmtalk` has been present in the ProjectSegmentPublisher Large Scale allowlist while still missing from the EIC `LARGE_SCALE_PROJECTS` allowlist.

EIC Large Scale mechanism:
- recent window constant: `DURATION_IN_DAYS_MEANING_RECENT = 3`
- recent event counters come from Postgres table `event_intermediate_counts_${project_id}`
- older event counters come from Athena table `notifly_event_intermediate_counts`
- old Athena event counter lookup is skipped when `externalUserId` is missing, so check `external_user_id` coverage before conversion

Required readiness checks before adding a project to `LARGE_SCALE_PROJECTS`:
- map `project_id` to product via DynamoDB `project` table with projection only (`id`, `product_id`, `name`)
- confirm historical EIC data exists in Athena/S3 for the project/date/name coverage needed by campaigns
- confirm Glue/Athena partitions include `project_id`, `dt`, and `name` so partition pruning works
- check whether event conditions include unbounded `count X` / `and TRUE` shapes, because Athena scan cost and latency may increase
- verify target audience counts before/after conversion, especially for users without `external_user_id`

Migration/backfill path:
- EventBridge schedule: `infra/terraform/prod/ap-northeast-2/eventbridge/schedules.tf`
  - `trigger-eic-migration-workflow-every-day`
  - daily `cron(30 0 * * ? *)`, timezone `Asia/Seoul`
- Step Functions definition: `infra/terraform/prod/ap-northeast-2/step-functions/definitions/migrate-event-intermediate-counts.asl.json`
  - state machine: `migrate-event-intermediate-counts`
  - scheduler lambda command: `schedule-migrate-event-intermediate-counts`
  - Glue job: `migrate_event_intermediate_counts`
  - arguments: `--PROJECT_ID`, `--START_DATE`, `--END_DATE`
  - Map `MaxConcurrency: 50`
- default EventBridge input file supports blank `start_date`, `end_date`, `project_id`; manual backfills should pass explicit values

Operational guidance:
- convert high-frequency slow EIC projects first; treat one-off slow projects as watchlist unless recurrence grows
- backfill one or two large projects at a time, split long date ranges, and run off-peak to avoid shared RDS/Glue/S3 pressure
- after deployment, monitor slow EIC logs, RDS Performance Insights, Athena query failures/latency/cost, migration monitoring, and campaign target count deltas
- if the alarm's metric filter is broad, estimate alert reduction by separating EIC-driven runs from unrelated long-processing warnings before claiming benefit

#### Long-running processing root cause
Typical evidence:
- warning around 40–50 minutes
- same stream shows `Project segment extraction query: ... users_${project_id} ... WHERE (TRUE)`
- many `campaignId: ... recipients published` logs for a single huge campaign/user journey
- correlation with `user_journey_sessions_${project_id}` queries and inserts

Check code paths:
- `services/task/segment-publisher/sqs_publisher.ts`
- `services/task/segment-publisher/lib/schedule.ts`
- `services/task/segment-publisher/lib/segment/segment_publisher.ts`
- `services/task/segment-publisher/lib/user_journey/consumer.ts`
- `services/task/segment-publisher/lib/user_journey/lib/reentry_policy.ts`
- `services/task/segment-publisher/lib/user_journey/lib/user_journey_session.ts`

Interpretation pattern:
- long-running processing is usually **not** the EIC query itself
- it is the total runtime of `handleCampaignSchedules(...)`, which includes:
  - schedule context setup
  - project segment extraction
  - per-batch publish fanout
  - user-journey re-entry checks
  - `user_journey_sessions_${project_id}` inserts
  - Kinesis session start tracking

### 7. Use Performance Insights to confirm DB pressure shape

For long-running processing, inspect the Notifly Aurora instances and look for top SQL on:
- `user_journey_sessions_${project_id}`
- `campaigns_${project_id}`
- `user_journeys_${project_id}`
- `event_intermediate_counts_${project_id}`

This helps separate:
- EIC bottleneck
- user-journey session bottleneck
- writer-side insert pressure

## Strong learned pattern

Recent incidents showed that long-running processing warnings were consistently caused by:
- project `32d8d9d6294d52e7a5427c036b471f91`
- product `stepup`
- user journey `UL1T00` (`[만보기] 매일 적립 리마인드`)

The root cause was:
- very large audience size (~860k+ recipients)
- project segment extraction on `users_${project_id}` / `device_${project_id}` with `WHERE (TRUE)`
- repeated batch publishing over ~45–49 minutes
- additional load from re-entry policy checks and `user_journey_sessions_${project_id}` inserts

This is a structural throughput problem, not an EIC-only issue.

## Output template

Answer in this order:
1. Alarm/log class actually responsible
2. `project_id` and product
3. Campaign/user journey ID and name if found
4. Exact code path responsible
5. Whether it is primarily:
   - slow EIC extraction
   - long-running segment extraction/publish
   - user-journey session fanout
6. Concrete recommendation for threshold/filter changes vs real performance fixes
