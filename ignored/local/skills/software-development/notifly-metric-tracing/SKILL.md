---
name: notifly-metric-tracing
description: Trace how a Notifly metric label (e.g. send_success, failover_text_message_send_success) is produced from delivery_result/message_events through campaign statistics and API aggregation.
version: 1.0.0
author: Hermes Agent
license: MIT
---

# Notifly metric tracing

Use this when a question asks what a metric in Notifly "really means", whether one event is included in another, or why a campaign stat differs from raw delivery logs.

## Goal

Map a user-facing metric label to:
1. the raw event rows written into `delivery_result_*` or `message_events_*`
2. any intermediate aggregation into `campaign_statistics_*`
3. the final API/UI mapping that shows the number to users

## Workflow

### 1. Find the UI/API metric label

Search for the metric label in the web console and API layers.

Typical files:
- `services/server/web-console/src/models/campaignStatistics.ts`
- `services/server/api-service/lib/api/v1/statistics/constants.js`
- `services/server/api-service/lib/api/v1/statistics/services/campaignService.js`
- `services/server/api-service/lib/api/v1/statistics/services/index.js`
- `services/server/api-service/lib/api/v1/statistics/utils/aggregateMetricByChannel.js`

Questions to answer:
- What exact internal metric name is displayed? (`send_success`, `failover_text_message_send_success`, etc.)
- Does the API map `message_sent` to `send_success` for that channel?
- Does aggregation use the row's real `channel`, or does it overwrite channel from campaign metadata?
- In the API v1 statistics path, `services/index.js` may reattach `channel` from `campaigns_${projectId}` / user journey node details before `aggregateMetricByChannel`, so verify whether channel semantics come from raw rows or campaign metadata.

### 2. Trace raw event writers

Search the lambdas that write delivery results.

Useful search patterns:
- `send_success|send_failure`
- `failover_text_message_send_success|failover_text_message_send_failure`
- `is_failover_text_message`
- `origin_channel|failover_reason`

Important source areas:
- `services/lambda/*delivery*/`
- `services/lambda/*result-poller*/`
- `services/lambda/delivery-result-webhook-receiver/`
- `services/lambda/notifly-nhn-delivery-result-collector/`

Check:
- which `channel` is written
- which `event_name` is written
- whether failover is encoded as a separate event name or as normal `send_success/send_failure` plus a flag

### 3. Check fallback path when campaign statistics are empty

Web console falls back to raw `delivery_result` if `campaign_statistics_*` has no rows.

Relevant file:
- `services/server/web-console/src/services/CampaignStatisticService.ts`
- `services/server/web-console/src/repositories/DeliveryResultRepository.ts`

Key behavior to verify:
- fallback query groups by `campaign_id` and `event_name`
- it aliases `event_name AS metric_name`
- it may NOT preserve raw `channel` separation

This is a common source of semantic drift: text-message failover rows can be counted under a brand-message campaign if grouped only by campaign and event.

### 4. Distinguish old vs new pipelines

Notifly has at least two materially different Kakao/failover paths:

#### Legacy NHN collector path
Files:
- `services/lambda/notifly-nhn-delivery-result-collector/lib/constants.js`
- `services/lambda/notifly-nhn-delivery-result-collector/lib/kakao_brand_message.js`

Behavior:
- failover text results are written as distinct event names:
  - `failover_text_message_send_success`
  - `failover_text_message_send_failure`

Implication:
- failover is explicitly separate from `send_success`

#### New kakao_bizmessage + poller path
Files:
- `services/lambda/kakao-brand-message-delivery/lib/kakao_bizmessage/send_kakao_brand_message.ts`
- `services/lambda/kakao-delivery-result-poller/service/result_service.ts`
- `services/lambda/kakao-delivery-result-poller/service/failover_service.ts`
- `services/lambda/scheduled-batch-text-message-delivery/`
- `services/lambda/delivery-result-webhook-receiver/lib/delivery_result.ts`

Behavior:
- original brand message final result becomes `send_success` / `send_failure`
- failover text message payload is marked with:
  - `event_params.is_failover_text_message = true`
  - `origin_channel`
  - `failover_reason`
- downstream text-message delivery writes normal text-message results with `send_success` / `send_failure`
- webhook receiver also marks failover text rows by setting `extra_data.is_failover_text_message = true`

Implication:
- raw rows distinguish failover by flag, not by distinct event name
- campaign-level fallback aggregation can therefore merge failover successes into `send_success`

## Heuristic for answering inclusion questions

If the user asks "Does send_success include failover SMS success?" answer in layers:

1. **Raw event semantics**: usually no — the original brand-message row and the failover text row are separate rows.
2. **Displayed campaign metric semantics**: maybe yes — if the campaign stat path groups by `campaign_id + event_name` and ignores/folds channel, failover text-message `send_success` can appear inside campaign `send_success`.
3. **Pipeline caveat**: legacy NHN collector uses explicit `failover_text_message_send_success`, while newer `kakao_bizmessage` pipeline uses `send_success` + failover flags.

## Campaign statistics date-boundary / one-day shift triage

Use this path when campaign stats / 발송 현황 shows dates shifted by one day, a selected period's previous day appears as `0`, or the same calendar date has different counts depending on selected start/end date.

1. Prioritize thread detail over the parent summary if the user says the parent is not reproducible. Look for concrete symptoms like "DB 수와 일치하는데 하루씩 뒤로 밀림" or "설정한 기간 -1 날짜가 0으로 표기".
2. Trace UI → API → DB range conversion:
   - `services/server/web-console/src/components/stats/CampaignStats.tsx` sends `startDate.toISOString()` / `endDate.toISOString()`.
   - `services/server/web-console/src/pages/api/projects/[projectId]/campaigns/[campaignId]/stats/index.ts` parses query dates.
   - `services/server/web-console/src/services/CampaignStatisticService.ts` converts to `yyyy-MM-dd_HH` UTC bucket strings and also builds display zero-fill date ranges.
   - `services/server/web-console/src/repositories/CampaignStatisticRepository.ts` filters `collected_from >= from` and `collected_to <= to`.
3. Remember KST midnight datepicker values serialize as prior-day `15:00Z`; e.g. 5/7 KST 00:00 becomes `5/6T15:00Z`. This can be correct for DB buckets but wrong for display zero-fill if mixed with raw `Date` intervals.
4. Treat `collected_from='YYYY-MM-DD_15'` as the next KST calendar day at 00:00 before calling it a one-day data shift.
5. Compare web-console behavior with `services/server/api-service/lib/api/campaigns/stats.js`, which has explicit KST-midnight end-date adjustment when building display date ranges.
6. Recommended fix shape: normalize the selected period once as a KST day range, then derive both DB UTC bucket bounds and display zero-fill labels from that same range.

See `references/campaign-statistics-kst-utc-date-boundary.md` for reproduction commands, exact files, and regression-test ideas.

## Statistics read slowness / timeout triage

Use this path when a user asks why Notifly metrics/statistics reads are very slow, timeout, or feel unusable.

1. Separate **freshness lag** from **read latency**. Raw events may exist while `campaign_statistics_*` is not yet collected, but large statistics API reads can also be slow even after aggregation.
2. Identify the path: API v1 aggregate statistics, CSV export, web-console campaign detail, or web-console fallback to raw `delivery_result_*`.
3. Inspect `api-service/lib/api/v1/statistics/services/index.js`: `aggregateStatistics()` runs campaign statistics and user-journey statistics under a hard `TIMEOUT = 29000`.
4. Inspect `campaignService.js` and `userJourneyService.js` for computed date filters like `replace(collected_from, '_', ' ')::timestamp + interval '9 hours'`. This can prevent efficient btree-index use and lead to `Parallel Seq Scan` on large per-project tables.
5. For production-sized tables, prefer `EXPLAIN` over `EXPLAIN ANALYZE` unless explicitly approved; `EXPLAIN ANALYZE` executes the expensive query.
6. Check per-project table sizes via PostgreSQL catalog estimates and inspect table-specific indexes. Whole-project date-range reads may not match indexes whose leading columns start with `campaign_id` or other dimensions.
7. Remember CSV has a 2MB limit and timeout/limit messages may be returned as HTTP 200 text, which can look like “export is broken.”
8. Frame “아예 못 쓴다” carefully: large project + long date range + CSV/export can be effectively unusable, while small/narrow/short queries may still work.

See `references/statistics-read-performance.md` for a compact query-plan checklist, key files, and explanation template.

## User-level push history with missing current device

Use this path when a user has push delivery history but the current user detail screen shows no device information.

1. Resolve the current user row from `users_<projectId>` by `external_user_id`; note `notifly_user_id`, `created_at`, and `updated_at`.
2. Check `device_<projectId>` both by current `notifly_user_id` and by `external_user_id`; absence here only means the user has no **current** device row.
3. Query `delivery_result_<projectId>` by the resolved `notifly_user_id`, grouped by `channel,event_name`; inspect recent rows and `extra_data` keys.
4. If push rows have `extra_data.token`, join that token to current `device_<projectId>.device_token`. If it now belongs to a different `notifly_user_id` with blank `external_user_id`, suspect logout/anonymous transition rather than data loss.
5. Query `message_events_<projectId>` for the same old `notifly_user_id`. Pair `delivery_result.send_success` with SDK-side events such as `push_delivered`, `push_not_delivered`, and `push_click`; `send_success` is provider/send-request success, not proof of device display.
6. Use Athena `notifly_event_logs` around the device/user transition window for `session_start`, `set_user_properties`, and `remove_external_user_id` filtered by old/new `notifly_user_id`, `external_user_id`, and `notifly_device_id`.
7. Code proof for identity movement: `services/lambda/kds-consumer/lib/event_utils.ts` makes `remove_external_user_id` return device data with `force_update_user_id=true`; `services/lambda/kds-consumer/lib/device_utils.ts` then updates `notifly_user_id` and `external_user_id` on conflict for the same `notifly_device_id`.

Common interpretation:
- Past push rows can remain attached to the old identified user while the same physical device has moved to a new anonymous `notifly_user_id` after `remove_external_user_id`.
- If `message_events.event_name='push_not_delivered'` and `event_params.reason='missing POST_NOTIFICATIONS permission'`, the UI may show “메시지 발송 성공” from `delivery_result.send_success`, but the actual device-side outcome was push receipt/display failure due to Android notification permission.

See `references/user-push-history-missing-device.md` for a compact SQL/Athena recipe from an investigated case.

## Statistics / PA-style analysis request triage

Use this path when a user asks whether Notifly can satisfy prospect requests for deep campaign performance analysis, e.g. brand/product/category/store/AOV breakdowns or PA/ad-hoc BI-like slicing.

1. Separate **campaign attribution/reporting** from **free-form analytics**. Notifly can reasonably own campaign execution, conversion attribution, and fixed POC reports; arbitrary multi-dimensional exploration is closer to BI/PA.
2. Check whether the requested metric is already in campaign statistics (`metric_type`, `conversion_type`, `count`, `sum`, `dimension_key`, `dimension_value`) or only available in raw event params/Athena.
3. Remember the current conversion analytics path may be first-conversion-centric (`_getConversionEventStats()` uses `metrics[0]`) and event counter aggregation keeps only the first `segmentation_event_param_keys[0]`; do not promise arbitrary brand × product × store breakdowns as a standard console capability.
4. Safe proposal shape: **4–6 week fixed-scope POC report** with pre-agreed dimensions/metrics, delivered as CSV/Google Sheet or managed analysis; route true ad-hoc exploration to the customer's BI/PA.
5. Minimal implementation shape: purchase event contract (`amount`/`event_value` plus 1–2 dimensions such as `brand` or `category`) + one fixed breakdown export/query. Avoid arbitrary multi-dimension UI scope in first pass.

See `references/pa-ad-hoc-analysis-vs-poc-reporting.md` for code evidence and customer-facing wording.

## High-signal files to cite

- `services/server/web-console/src/models/campaignStatistics.ts`
- `services/server/web-console/src/services/CampaignStatisticService.ts`
- `services/server/web-console/src/repositories/DeliveryResultRepository.ts`
- `services/server/api-service/lib/api/v1/statistics/constants.js`
- `services/server/api-service/lib/api/v1/statistics/services/campaignService.js`
- `services/lambda/notifly-nhn-delivery-result-collector/lib/constants.js`
- `services/lambda/notifly-nhn-delivery-result-collector/lib/kakao_brand_message.js`
- `services/lambda/kakao-delivery-result-poller/service/result_service.ts`
- `services/lambda/kakao-delivery-result-poller/service/failover_service.ts`
- `services/lambda/delivery-result-webhook-receiver/lib/delivery_result.ts`
- `services/lambda/kds-consumer/lib/event_utils.ts`
- `services/lambda/kds-consumer/lib/device_utils.ts`
- `services/server/web-console/src/components/users/list/PushLogListComponent.tsx`

## Pitfalls

- Do not assume the UI metric label equals raw `delivery_result.event_name` semantics.
- Do not assume failover always uses separate event names; this changed across pipelines.
- Do not answer from a single file. You need raw writer + aggregation layer + UI/API mapping.
- Watch for fallback logic: when `campaign_statistics_*` is absent, web console derives stats directly from `delivery_result_*`, which can materially change semantics.

## Output template

For Slack product/sales advisory threads, keep the first answer concise and limited to the exact question. Avoid comprehensive frameworks unless asked; give a recommendation, 2–4 bullets of rationale/scope, and one safe customer-facing sentence if useful.

For scheduled daily mentoring about Notifly metrics/statistics, prefer one small mechanism, not a broad survey. Shape the answer as: `오늘의 Notifly: <주제>`, one-line summary, 2–3 bullets where each bullet follows `무엇인지 → 어떻게 동작하는지 → 왜 중요한지`, optional SDK/iOS implication, and one `내일은 ...` line. See `references/daily-mentoring-campaign-statistics-path.md` for a compact campaign-statistics example and file citations.

Important daily-mentoring guardrail: this skill may be attached to the cron job even when the user asked for broad Notifly infra/service mentoring. Do **not** let the presence of this skill force a metrics/statistics topic. First inspect recent `오늘의 Notifly` outputs when possible; if metrics/statistics appeared recently, avoid `raw event → campaign_statistics → UI metric` entirely and use the broader `notifly-systems-investigation` daily mentoring workflow instead.

For metric semantics debugging, answer with three layers:
- **Raw event level:** what rows are written
- **Campaign/statistics level:** what gets grouped into displayed metric
- **Pipeline caveat:** legacy vs current behavior
