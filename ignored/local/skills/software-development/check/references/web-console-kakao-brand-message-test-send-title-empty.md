# web-console — Kakao Brand Message Test Send: "The title can not be empty."

## Pattern

알람: `/aws/ecs/notifly-services-prod/web-console console error`  
트리거: `Error: The title can not be empty.`  
코드 경로: `POST /api/projects/[projectId]/test_send/kakao_brand_message` → `failoverTextMessage` → `inline` → LMS 대체 문자 title 필드 필수값 검증 실패 → HTTP 500

## 분류

**처리된 클라이언트 입력 검증 오류** (handled business validation). 실 발송 경로가 아닌 테스트 발송 API(`test_send`)에서만 발생. 서비스 헬스 정상, 실 수신자 미영향. → `no_action`

## 스택 트레이스 특징

```
Error: The title can not be empty.
  at u (…/chunks/71260.js:1:1071)
  at async d (…/chunks/71260.js:1:2043)
  at async m (…/chunks/71260.js:1:1560)
  at async g.failoverTextMessage (…/chunks/71260.js:2:10940)
  at async T.inline (…/chunks/71260.js:2:985)
  at async Array.q (…/pages/api/projects/[projectId]/test_send/kakao_brand_message.js:1:6277)
```

`failoverTextMessage` → `inline` → `test_send/kakao_brand_message` 경로가 특징. access log에서 HTTP 500으로 확인됨.

## Scope 추출 방법

로그 컨텍스트에 `project_id`가 직접 노출되지 않음. access log에서 추출:

```python
logs.filter_log_events(
    logGroupName='/aws/ecs/notifly-services-prod/web-console',
    startTime=start_ms,
    endTime=end_ms,
    filterPattern='test_send',
    limit=30
)
# access log 라인 예시:
# 112.220.222.90 - - [...] "POST /api/projects/<project_id>/test_send/kakao_brand_message HTTP/1.1"
#   500 39 "https://console.notifly.tech/console/products/<productId>/campaign/create?...&id=<campaignId>"
```

Referer에서 `productId` 및 `campaignId` 추출 → DynamoDB `project` 테이블로 `product_id-project_id-index` GSI 조회.

## 패턴 특징

- 동일 IP에서 수 분 간격으로 반복 요청하는 양상 (사용자가 계속 재시도)
- rapid_recurrence status='rapid' 가능 (4~5분 간격 2회 이상) — 이 경우에도 서비스 장애 아님
- LMS 대체 문자 타입 선택 시 title 필드가 필수이나, 사용자가 미입력 상태로 테스트 발송 시도

## 관련 소스 파일

- `services/server/web-console/src/components/campaign/compose/flow/message/kakao/shared/FailoverTextMessage.tsx` — UI (LMS type 선택 시 title 필드 표시)
- `services/server/web-console/src/pages/api/projects/[projectId]/test_send/kakao_brand_message.js` (빌드 번들 → chunks/71260.js)

## 장기 개선 방향

1. 서버 응답 코드 HTTP 500 → 400 변경 (클라이언트 입력 오류는 4xx가 적절)
2. 클라이언트 측 폼 검증 강화 (LMS 선택 시 title 필드 필수 UI 표시)
3. 검증 오류 로그 레벨 `console.error` → `console.warn` 하향 (ConsoleErrors 알람 노이즈 제거)

## 빈도 기준선 (2026-06 관측)

- 알람 transition 30일: 76회, 7일: 20회 (ConsoleErrors 서비스 전체, 이 패턴만은 아님)
- 해당 class101/HAd0VR 캠페인 세션 내에서 10분간 6~8회 반복 관측
