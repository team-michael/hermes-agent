# Notifly statistics read performance reference

Use this when a user asks why Notifly metrics/statistics reads are slow, timeout, or feel unusable for large projects or long date ranges.

## Core model

Statistics reads are not a simple raw-event lookup. The heavy paths are roughly:

```txt
delivery_result_* / message_events_*       raw event rows
        ↓
campaign_statistics_* / user_journey_statistics_*  aggregated rows
        ↓
api-service / web-console statistics responses
```

Two different issues can be confused:

- **Freshness lag:** raw event exists but has not yet been collected into `campaign_statistics_*`.
- **Read latency:** the statistics API query itself is expensive and may timeout.

For “엄청 느리다 / 아예 못 쓴다” reports, first suspect read latency on the aggregate API, not event ingestion.

## Key files

- `services/server/api-service/lib/api/v1/statistics/services/index.js`
  - `aggregateStatistics()` runs campaign statistics and user-journey statistics concurrently.
  - Has a hard timeout: `TIMEOUT = 29000` and `Statistics query timeout after 29 seconds`.
- `services/server/api-service/lib/api/v1/statistics/services/campaignService.js`
  - Queries `campaign_statistics_${projectId}`.
  - Applies date filtering/grouping/ordering using a computed timestamp expression over `collected_from`.
- `services/server/api-service/lib/api/v1/statistics/services/userJourneyService.js`
  - Similar computed timestamp pattern for `user_journey_statistics_${projectId}`.
- `services/server/api-service/lib/api/v1/statistics/validators/errorHandler.js`
  - JSON timeout becomes HTTP 408 `RequestTimeout`.
  - CSV timeout can be returned as HTTP 200 text.
- `services/server/api-service/lib/api/v1/statistics/handlers.js`
  - CSV export has `CSV_SIZE_LIMIT_BYTES = 2 * 1024 * 1024`.
- `services/server/api-service/lib/api/v1/statistics/validators/dateRangeValidator.js`
  - Today in KST is rejected; this API is not a realtime “today” dashboard path.
- `services/server/web-console/src/services/CampaignStatisticService.ts`
  - Web console can fall back from `campaign_statistics_*` to raw `delivery_result_*`.
- `services/server/web-console/src/repositories/DeliveryResultRepository.ts`
  - Raw fallback groups delivery results by campaign/event/hour and can be expensive on large tables.

## Diagnostic workflow

1. Identify the exact endpoint/screen:
   - API v1 aggregate statistics?
   - CSV export?
   - web-console campaign detail?
   - raw delivery result fallback?
2. Check if the query is broad:
   - whole project vs one campaign
   - long date range vs short range
   - tag filtering and whether it is pushed into SQL or applied later
3. Inspect query shape in the code:
   - Look for `replace(collected_from, '_', ' ')::timestamp + interval '9 hours'`.
   - If a function is applied to the filtered column, normal btree indexes on the raw column often cannot be used effectively.
4. Use `EXPLAIN`, not `EXPLAIN ANALYZE`, on production-sized tables unless explicit approval exists. `EXPLAIN ANALYZE` executes the heavy query.
5. Check table sizes with PostgreSQL catalog estimates:
   - `pg_class.reltuples` for `campaign_statistics_%`, `delivery_result_%`, `user_journey_statistics_%`.
6. Inspect indexes for the specific per-project table:
   - `campaign_statistics_*` often has a unique index starting with `(campaign_id, variant_id, metric_name, ...)`.
   - Whole-project date-range queries may not match that leading-column order.
   - `delivery_result_*` may have `(campaign_id)` and `(event_name, created_at)` but not `(campaign_id, created_at)`.

## Typical findings

A representative slow plan for large `campaign_statistics_*` queries shows:

```txt
Parallel Seq Scan on campaign_statistics_...
Filter: dimension_key = ''
        and ((replace(collected_from, '_'::text, ' '::text) || ':00:00')::timestamp + '09:00:00'::interval) >= ...
```

Interpretation:

- `collected_from` is text-like and converted at read time.
- Date filtering is applied after computing a timestamp expression per row.
- The query can degrade into scanning a large fraction of the table.
- `GROUP BY`/`ORDER BY` over the same expression compounds the cost.

Large deployments can have:

- hundreds of per-project statistics tables
- `delivery_result_*` tables in the hundreds of millions of rows
- `campaign_statistics_*` tables in the tens of millions of rows

Do not overstate exact counts unless freshly re-queried; treat them as scale intuition.

## How to explain to the user

Preferred framing:

> “수집이 느리다”와 “읽는 쿼리가 느리다”를 분리해야 합니다. 여기서 큰 문제는 읽기 쪽입니다. 집계 테이블을 쓰는데도, 시간 컬럼을 문자열에서 timestamp로 매번 변환하고 전체 프로젝트 기간 조회/group/order를 하면서 인덱스를 잘 못 타는 구조라 큰 프로젝트/긴 기간에서는 29초 timeout에 걸릴 수 있습니다.

When the user says “아예 못 쓴다”:

- Do not claim universal outage.
- Say it can be effectively unusable for large project + long range + CSV/export combinations.
- Shorter ranges, narrower campaign filters, or smaller projects may still work.

## Improvement directions

- Store normalized timestamp/date columns instead of deriving them from text at read time.
- Add generated column or expression index if schema migration is constrained.
- Add indexes that match the read pattern, e.g. date/dimension/metric/campaign order depending on endpoint.
- Use daily/materialized rollups for whole-project dashboard reads.
- Move large CSV exports to async jobs with object-storage download links.
- For raw fallback, consider `(campaign_id, created_at, event_name)` or partitioning, after checking write cost and actual query distribution.
- Apply tags/campaign filters as early as possible instead of aggregating broadly and filtering later.

## Pitfalls

- Do not run production `EXPLAIN ANALYZE` on huge tables casually; it executes the query.
- Do not equate `campaign_statistics_*` with “always fast”; aggregation reduces raw volume but does not fix a mismatched query/index shape.
- Do not ignore CSV behavior: timeout or size-limit messages may be returned as HTTP 200 text.
- Do not treat today’s date rejection as a performance bug; it is a product/API freshness contract in the validator.
