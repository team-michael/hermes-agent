# PA/ad-hoc 분석 요구 vs Notifly POC 리포팅

Use when a prospect asks for campaign performance analysis that sounds like Product Analytics / BI / ad-hoc slicing: brand, product, category, store, AOV, purchase amount, etc.

## Core interpretation

If the ask is “campaign-driven purchase by arbitrary brand/product/category/store combinations,” this is closer to PA/BI than Notifly campaign operations. Avoid promising Notifly as a free-form analysis tool.

Recommended positioning:
- Notifly owns campaign execution + attribution/event collection.
- Customer BI/PA owns arbitrary exploratory analysis when they need many joins/dimensions.
- For sales/POC, Notifly can provide a **fixed-scope POC report** from pre-agreed fields.

## Evidence from current code paths

- Campaign statistics can carry dimensions via `dimension_key` / `dimension_value` and UI service accepts requested `dimensionKeys`:
  - `CampaignStatisticRepository.findTotalCountsByCampaignIdAndDateRange(... dimensionKeys ...)`
  - `CampaignStatisticService.getStatsBetween(... dimensionKeys ...)`
- Aggregated statistics display handles count vs sum-based conversion types:
  - `sales_conversion` / `total_sum_conversion` use `sum`
  - count conversions use `count`
- Message analytics conversion path is not general-purpose BI:
  - `_getConversionEventStats()` has `// TODO: support multiple conversion events`
  - it only uses `metrics[0]`
  - it joins campaign success rows to `event_intermediate_counts_*` by user/time/window and event name.
- Event counter aggregation stores only one segmentation param for event counts:
  - `constructEventIntermediateCountData()` uses `segmentation_event_param_keys[0]`
  - id is `{notifly_user_id}_{eventName}_{date}_{segmentationKey}_{segmentationValue}`
  - so arbitrary multi-dimensional breakdown is not naturally supported there.
- Athena-backed event analytics can inspect event params, but broad ad-hoc slicing should be treated as a managed/offline analysis path, not a guaranteed product UI capability.

## Safe sales/product answer

Recommend one of two routes:

1. Customer BI/PA route
   - Notifly exports/provides campaign/user/event identifiers and conversion events.
   - Customer joins POS/CDP/order data in their BI/PA.
   - Safest if they need arbitrary brand/product/category/store slicing.

2. POC fixed-report route
   - 4–6 week POC.
   - Predefine exactly 1–2 dimensions and 3–5 metrics.
   - Example fields: `brand`, `category`, `amount`, `store`.
   - Example metrics: conversion count, conversion revenue, AOV, top brand/category by campaign.
   - Deliver as CSV/Google Sheet or manually prepared analysis, not as “standard console feature.”

## Minimal implementation shape

Smallest viable product-side support:
- Define a purchase event contract for POC: `purchase` with `amount`/`event_value` plus one agreed dimension (`brand` or `category`; optionally `store`).
- Use existing conversion/sales conversion aggregation for campaign-level count/revenue.
- Add/export one fixed breakdown query/report, e.g. `campaign_id x date x brand` or `campaign_id x category`.
- Do not support arbitrary dimension combinations in the first pass.

## Unsafe promises

Avoid saying:
- “현재 콘솔에서 브랜드/상품/객단가를 자유롭게 분석할 수 있습니다.”
- “PA처럼 임의 조건 조합 분석이 가능합니다.”
- “여러 전환 이벤트/필터가 UI에서 모두 완전 분리되어 보입니다.”

Safer wording:

> 현재 Notifly를 자유 분석용 PA 도구처럼 사용하는 방식보다는, POC 기간에 사전에 정의한 캠페인 성과 리포트를 함께 검증하는 방식이 적절합니다. 구매 이벤트에 브랜드·카테고리·상품·결제금액·점포 정보를 연동하면, 정해진 캠페인 기준으로 전환수, 전환매출, 객단가, 주요 브랜드/카테고리별 성과를 리포트 형태로 제공할 수 있습니다. 다만 임의 조건을 실시간 조합하는 BI/PA 기능은 표준 기능으로 약속하지 않는 것이 안전합니다.
