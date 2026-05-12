# Campaign statistics KST/UTC date-boundary triage

Use when Notifly campaign stats / 발송 현황 shows dates shifted by one day, a selected period's previous day appears as `0`, or the same calendar date has different counts depending on the selected start/end date.

## Observed symptom pattern

- Customer/internal report: `집계기간 당일` vs `전일` gives different data for the same date.
- Thread-level detail can be more important than the parent message: e.g. "DB 수와 일치하는데 하루씩 뒤로 밀림" and "설정한 기간 -1 날짜가 0으로 표기".
- The data can be correct while the UI date labels / zero-filled days are wrong.

## Key code paths

Web console detail stats path:

- `services/server/web-console/src/components/stats/CampaignStats.tsx`
  - sends `startDate: startDate.toISOString()` and `endDate: endDate.toISOString()` to `CampaignStatisticClient.getCampaignStats`.
- `services/server/web-console/src/pages/api/projects/[projectId]/campaigns/[campaignId]/stats/index.ts`
  - parses `req.query.startDate/endDate` with `new Date(...)`.
- `services/server/web-console/src/services/CampaignStatisticService.ts`
  - `formatDatesForDatabase(from,to)` converts dates to `yyyy-MM-dd_HH` UTC bucket strings.
  - `formatDatesForDatabase` currently forces the upper bound to `setUTCHours(15,0,0,0)`, which is intended to represent KST day boundary but can be easy to misread.
  - `calculateDateRange(from,to)` builds display zero-fill dates using `eachDayOfInterval({start: from, end: to})` then `toZonedTime(..., KST)`, which can introduce a previous-day zero bucket if `from` is a KST midnight represented as prior-day `15:00Z`.
  - `aggregateMetrics` parses `stat.collected_from` as UTC and formats it as KST date labels.
- `services/server/web-console/src/repositories/CampaignStatisticRepository.ts`
  - query: `collected_from >= from` and `collected_to <= to`.

API-service parallel path:

- `services/server/api-service/lib/api/campaigns/stats.js`
  - formats request dates to UTC bucket strings using `formatInUTC(..., 'yyyy-MM-dd_HH')`.
  - has explicit KST-midnight end-date handling in `aggregateCampaignStats`: when end is exactly KST 00:00, subtract 1ms before creating display dateRange.
- `services/server/api-service/lib/db/CampaignStatistics.js`
  - same range predicate: `collected_from >= $2 AND collected_to <= $3`.

Pipeline path:

- `jobs/aggregate_campaign_statistics/etl/extract.py`
- `jobs/aggregate_campaign_statistics/etl/transform.py`
- `jobs/aggregate_campaign_statistics/etl/load.py`
- Shared Glue predicate builder may use half-open hour filters: start day `h >= start_hour`, end day `h < end_hour`.

## Quick reproduction / sanity check

KST datepicker midnight becomes prior-day UTC 15:00:

```bash
TZ=Asia/Seoul node -e "const d=new Date(2026,4,7,0,0,0); const e=new Date(2026,4,8,0,0,0); console.log(d.toISOString()); console.log(e.toISOString());"
# 2026-05-06T15:00:00.000Z
# 2026-05-07T15:00:00.000Z
```

DB query bucket conversion examples:

```bash
node -e "function f(date){const iso=date.toISOString();return iso.slice(0,10)+'_'+iso.slice(11,13)} function range(fromIso,toIso){const from=new Date(fromIso); const to=new Date(toIso); const upper=new Date(to); upper.setUTCHours(15,0,0,0); console.log({input:{from:fromIso,to:toIso}, db:{from:f(from),to:f(upper)}})} range('2026-05-06T15:00:00.000Z','2026-05-07T15:00:00.000Z'); range('2026-05-07T15:00:00.000Z','2026-05-07T15:00:00.000Z');"
# 5/7~5/8 KST-midnight style -> from 2026-05-06_15 to 2026-05-07_15
# 5/8 same-day midnight-only -> from 2026-05-07_15 to 2026-05-07_15
```

## Interpretation heuristic

- If DB rows use `collected_from='YYYY-MM-DD_15'`, that bucket is **next calendar day at KST 00:00**. Do not call it a one-day data shift until checking the display conversion.
- If counts align with DB but the UI shows a previous selected-date row with `0`, suspect display zero-fill date-range generation, not event ingestion.
- If the same date count changes when the start date changes, compare the exact `from/to` bucket strings sent to the DB; inclusive `collected_to <= to` and KST/UTC boundary conversion can include/exclude edge buckets.
- Compare web-console `CampaignStatisticService.ts` against `api-service/lib/api/campaigns/stats.js`; the API-service path already contains KST-midnight end-date range adjustment that web-console may lack or implement differently.

## Recommended fix shape

- Normalize the selected period as a KST day range first, then derive both:
  1. DB UTC bucket range, and
  2. display zero-fill date labels
  from that single normalized range.
- Prefer explicit semantics: `from = selectedStart KST 00:00`, `toExclusive = selectedEnd + 1 day KST 00:00` (or `toInclusive = selectedEnd KST 23:59:59.999`) and document which is used.
- Add regression coverage for:
  - selecting a KST midnight range does not create `selectedStart - 1` zero rows;
  - a DB bucket at UTC `15` is displayed as the intended KST date;
  - same calendar date counts do not differ merely because the selected start date changed, except for intentionally excluded edge buckets.
