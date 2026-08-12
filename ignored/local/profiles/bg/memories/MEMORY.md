- Grey Box builds Notifly and Clix. Notifly is a Korean CRM for data, segmentation, journeys, multichannel messaging, and analytics. Its public AI Assistant creates reviewable drafts/diagnoses/summaries; it is approval-based, not fully autonomous, and is not ISMS-P certified.
- Clix is an English developer-first iOS/Android push platform built around `clix install`, FCM/APNs, diagnostics, analytics, REST API, MCP, and Agent Skills. Retention/OpenClix/AI-agency narratives are historical.
§
BG AWS는 `notifly-internal-agent` IAM 사용자로 DynamoDB `transactions` 조회가 가능하다.
§
Notifly 2026-06 KST historical benchmark: paid-plan production projects 205; active customers 138, inactive/MAU=0 67. MAU=monthly distinct notifly_user_id in raw event logs. Data points apply the current counting contract, deduplicate event IDs daily in KST, then sum monthly. Customer-level min–max by MAU: ≤3만 n80 DP 1–2,402,872 ratio 1.0–311.9; 3–5만 n5 352,830–4,069,704 / 7.3–88.9; 5–10만 n5 1,115,720–9,841,814 / 17.8–163.5; 10–20만 n19 393,645–12,944,022 / 2.7–81.1; 20–30만 n7 1,400,733–722,567,463 / 6.7–3,347.3; 30–50만 n7 2,074,970–387,119,689 / 5.6–945.0; 50–100만 n10 6,087,071–122,427,543 / 9.1–198.8; ≥100만 n5 14,250,927–115,805,471 / 2.5–112.0. For pricing/capacity, prefer median and P10–P90 because maxima are outlier-sensitive.
§
BG profile has separate encrypted Google OAuth access for minyong@greyboxhq.com with GA analytics.readonly and Search Console webmasters.readonly; existing Workspace OAuth is unaffected. Verified GA4 properties: notifly 353051031, docs-notifly 373488755, notifly-blog 412745496. Verified GSC access: sc-domain:notifly.tech and www/docs/blog URL-prefix properties.
§
BG Slack 채널 히스토리는 네이티브 Slack 도구가 보이지 않아도 프로필 소유 `slack_history.py`와 Bot API로 조회 가능하며, 채널 접근 판단은 실제 `--check` 결과가 기준이다.
§
Notifly 전역 product-capability descriptor는 Kakao·LINE을 포함한 실제 전체 지원 채널을 열거하며, locale별 채널 노출 제한은 localized landing copy에 적용한다.