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
- `services/server/api-service/lib/api/v1/statistics/utils/aggregateMetricByChannel.js`

Questions to answer:
- What exact internal metric name is displayed? (`send_success`, `failover_text_message_send_success`, etc.)
- Does the API map `message_sent` to `send_success` for that channel?
- Does aggregation use the row's real `channel`, or does it overwrite channel from campaign metadata?

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

## Pitfalls

- Do not assume the UI metric label equals raw `delivery_result.event_name` semantics.
- Do not assume failover always uses separate event names; this changed across pipelines.
- Do not answer from a single file. You need raw writer + aggregation layer + UI/API mapping.
- Watch for fallback logic: when `campaign_statistics_*` is absent, web console derives stats directly from `delivery_result_*`, which can materially change semantics.

## Output template

Answer with three layers:
- **Raw event level:** what rows are written
- **Campaign/statistics level:** what gets grouped into displayed metric
- **Pipeline caveat:** legacy vs current behavior
