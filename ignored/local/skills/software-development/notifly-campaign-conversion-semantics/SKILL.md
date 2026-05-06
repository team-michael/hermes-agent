---
name: notifly-campaign-conversion-semantics
description: Trace how Notifly campaign conversion events are validated, stored, and displayed, especially when multiple conversion events share the same event name but differ by filters.
version: 1.0.0
author: Hermes Agent
license: MIT
---

# Notifly campaign conversion semantics

Use this when someone asks questions like:
- "If I set 4 conversion events with the same event name, are they treated as one?"
- "Can I see conversion 1 vs conversion 4 separately?"
- "Why does the campaign list show only one conversion count?"
- "Do same-name conversion events merge, or does filter make them distinct?"

## Goal

Answer in three layers:
1. **Validation layer**: what combinations are allowed in campaign setup
2. **Storage/identity layer**: how conversion events are distinguished internally
3. **Display/reporting layer**: what the UI/API actually shows, especially first-conversion-only behavior

## High-signal files

### Validation and identity
- `services/server/web-console/src/schemas/campaign/view/index.ts`
- `services/server/web-console/src/utils/util.ts`
- `services/server/web-console/src/utils/campaign/adapter/index.ts`

### Campaign list / summary display
- `services/server/web-console/src/pages/api/projects/[projectId]/campaigns/conversion_counts.ts`
- `services/server/web-console/src/repositories/CampaignStatisticRepository.ts`
- `services/server/web-console/src/clients/CampaignClient.ts`
- `services/server/web-console/src/components/campaign/list/CampaignListComponent.tsx`
- `services/server/web-console/src/components/campaign/compose/flow/analytics/FirstConversionEventTip.tsx`
- `services/server/web-console/public/locales/en/products.json`

### Campaign analytics page
- `services/server/web-console/src/pages/console/products/[productId]/analysis/stats.tsx`
- `services/server/web-console/src/pages/api/lib/message_analytics.ts`
- `services/server/web-console/src/services/CampaignStatisticService.ts`
- `services/server/web-console/src/utils/campaign_stats_utils.ts`

### Message data viewer / delivery-status dashboard
- `services/server/api-service/lib/api/v1/statistics/services/index.js`
- `services/server/api-service/lib/api/v1/statistics/services/campaignService.js`
- `services/server/api-service/lib/api/v1/statistics/utils/aggregateMetricByChannel.js`
- `services/server/web-console/src/repositories/MessageDataRepository.ts`
- `services/server/web-console/src/domains/message-data-viewer/utils/extraction.ts`
- `services/server/web-console/src/domains/message-data-viewer/utils/aggregation.ts`
- `services/server/web-console/src/domains/message-data-viewer/components/MessageDataMetricSelector.tsx`

## Core findings

### 1. Duplicate detection is by `eventName + filters`, not by event name alone

In `schemas/campaign/view/index.ts`, conversion event duplicates are rejected by comparing the canonicalized string form of each conversion event.

That canonical form comes from `conversionEventsToString` in `utils/util.ts`:
- no filters -> `eventName`
- with filters -> `eventName?key1=value1&key2=value2`

Filters are sorted before stringification.

Implication:
- same event name + same filters -> duplicate, not allowed
- same event name + different filters -> allowed, treated as distinct conversion events

This is the key answer when a user asks whether same-name conversions are all "the same".

### 2. Storage preserves raw event name and filters separately

In `utils/campaign/adapter/index.ts`, conversion events are stored in `conversion_events` as objects like:
- `event_name`
- `filters`
- optionally `param_key` for sales conversion

So internally the identity is not just the bare event name. The filter configuration matters.

### 3. Campaign list conversion count is first-conversion-only

The campaign list path is very important:
- `CampaignListComponent.tsx` calls `CampaignClient.getCampaignConversionCounts`
- API route `campaigns/conversion_counts.ts` explicitly uses `campaign.conversion_events?.[0]`
- it then queries `CampaignStatisticRepository.countConversionByCampaignIdAndEventName(...)`

So the campaign list conversion metric only uses the **first conversion event**.

This is also reflected in UI copy:
- `FirstConversionEventTip.tsx`
- locale string `first_conversion_tip`: "This conversion event will be displayed as a conversion metric in the campaign list."

Implication:
- even if 4 conversion events are configured, the campaign list does **not** show all 4 separately
- it shows the representative first conversion event only

### 4. Campaign analytics page also has first-conversion limitations

In `pages/api/lib/message_analytics.ts` there is an explicit comment:
- `// TODO: support multiple conversion events`
- logic uses `const conversionEvent = metrics[0]?.eventName`

So at least this analytics path only handles the first conversion metric passed into it.

In `analysis/stats.tsx`, `_getConversionEventMetric(campaign)` uses `campaign?.conversion_event_name`, singular, for the displayed conversion metric.

Implication:
- analytics UX is not a clean fully-expanded "conversion 1 / conversion 2 / conversion 3 / conversion 4" view
- multiple conversion events may exist in data, but reporting surfaces can still behave as first-conversion-centric

### 5. Message data viewer / "발송 현황 대시보드" is event-name-and-type based, not slot-number based

For the newer message-data viewer path:
- API v1 statistics aggregation returns conversion rows as `{ name: row.metric_name, type: row.conversion_type, count: ... }` via `aggregateMetricByChannel.js`
- web-console parses these as `conversion_N_name`, `conversion_N_type`, `conversion_N_count`
- conversion options are then built from unique **conversion names** plus conversion types, not from "conversion 1/2/3/4" slots

Important consequences:
- this surface does **not** label things as "전환 1" or "전환 4"
- it shows conversions by **event name + type** (`direct`, `total`, `sales`)
- if internal `metric_name` contains the canonical filtered form (e.g. `purchase?brand=A`), filtered conversions can remain distinguishable here
- if a surface only shows `campaign.conversion_events.map(({ event_name }) => ...)`, filters are lost in the human-readable summary and same-name conversions can look deceptively identical

Two high-signal examples:
- `CampaignStatsDescription.tsx` shows `campaign.conversion_event_name || campaign.conversion_events?.map(({ event_name }) => event_name).join(', ')`, so summary text can hide filter differences
- `message-data-viewer/utils/extraction.ts` derives available conversion metrics from `conv.name`, and `MessageDataMetricSelector.tsx` builds selectable metrics from conversion names × types

One more caveat: `selectionCount.ts` currently counts total conversion options as `conversionNames.length * 2`, while the metric selector actually iterates `direct`, `total`, and `sales`. So the selector/model is event-name-based, but some counting UX still under-assumes conversion variants.

## Recommended answer pattern

When replying, separate **semantic truth** from **UI truth**.

### Good answer shape

1. **Configuration / semantics**
   - same event name alone does not force all conversions into one
   - same event name with different filters is treated as different conversion events

2. **Duplicate rule**
   - exact same event name + exact same filter combination is treated as duplicate and cannot be configured twice

3. **Display limitation**
   - campaign list conversion metric is based on the first conversion event
   - some analytics code paths still only support the first conversion event
   - therefore conversion 1 and conversion 4 may not both be separately visible in current UI

## Suggested concise wording

> 같은 이벤트명이어도 필터가 다르면 별도 전환 이벤트로 취급됩니다. 다만 현재 화면에서는 첫 번째 전환 이벤트를 대표 전환 지표로 보여주는 부분이 있어서, 전환 1/전환 4를 각각 완전히 분리해서 확인하는 데는 제한이 있습니다.

## Pitfalls

- Do **not** answer "same event name means all merged" without checking filters.
- Do **not** answer only from validation code; you must also inspect reporting/display code.
- Do **not** assume multiple configured conversion events are all surfaced equally in UI.
- Distinguish campaign list behavior from deeper stats/storage semantics.
