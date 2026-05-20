# Daily mentoring: campaign statistics path

Use this note when a scheduled daily mentoring prompt asks for a short Notifly systems explanation around metrics/statistics.

## Compact teaching frame

Topic: 캠페인 통계 숫자가 UI까지 오는 길

One-line model:
- UI의 “발송 성공”은 raw log를 그대로 세는 값이 아니라, raw event → `campaign_statistics_${projectId}` 집계 → 채널별 metric mapping을 거친 derived metric이다.

## Mechanism to explain

1. Raw event level
   - `delivery_result_${projectId}`: message delivery result rows.
   - `message_events_${projectId}`: SDK/user-side interaction or outcome event rows.
   - For push, `send_success`, `push_delivered`, and `push_click` are different semantic layers.

2. Campaign statistics level
   - `CampaignStatisticRepository.findTotalCountsByCampaignIdAndDateRange()` reads `campaign_statistics_${projectId}`.
   - `CampaignStatisticService.getStatsBetween()` converts UTC hourly bucket keys to KST display dates and aggregates metric counts/sums.
   - If no campaign statistics rows exist, web-console falls back to `DeliveryResultRepository.findEventCountsByCampaignIdAndDateRangeAsCampaignStatistics()` and aliases `event_name AS metric_name`.

3. API/UI mapping level
   - API v1 `CHANNEL_METRIC_MAP` maps channel-specific raw metric names into common fields like `message_sent`, `message_failed`, `delivered`, and `click`.
   - `aggregateMetricByChannel()` applies this map.
   - Example mappings:
     - Push: `send_success` → `message_sent`, `push_delivered` → `delivered`, `push_click` → `click`.
     - Email: `email_send` → `message_sent`, `email_delivery` → `delivered`, `email_click` → `click`.
     - Kakao/SMS/Webhook: usually `send_success` → `message_sent`.

## Files cited in the session

- `services/server/web-console/src/services/CampaignStatisticService.ts`
- `services/server/web-console/src/repositories/CampaignStatisticRepository.ts`
- `services/server/web-console/src/repositories/DeliveryResultRepository.ts`
- `services/server/api-service/lib/api/v1/statistics/constants.js`
- `services/server/api-service/lib/api/v1/statistics/utils/aggregateMetricByChannel.js`
- `services/server/api-service/lib/api/v1/statistics/services/campaignService.js`
- `services/server/api-service/lib/api/v1/statistics/services/index.js`

## SDK/iOS implication wording

`send_success` is not proof that the device displayed a push. Treat it more like server/provider send-request success. Actual device-side receipt/display should be interpreted with SDK-side events such as `push_delivered`, `push_not_delivered`, permission state, and click events.

## Daily mentoring style

Keep it short:

1. 제목: `오늘의 Notifly: <주제>`
2. 한 줄 요약
3. 2–3 bullets, each shaped as `무엇인지 → 어떻게 동작하는지 → 왜 중요한지`
4. One SDK/iOS implication if useful
5. `내일은 <후보 주제>`

Avoid comprehensive frameworks in the daily cron. One small mechanism per day is enough.