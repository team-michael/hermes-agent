# web-console `MODULE_NOT_FOUND` API Route Error

## Pattern

`web-console` ECS ConsoleErrors 알람이 `Error: Cannot find module '<package-name>'`로 트리거되는 케이스.

**First observed:** 2026-06-19

## Error signature

```
Error: Cannot find module 'google-spreadsheet'
Require stack:
- /app/services/server/web-console/.next/server/pages/api/projects/[projectId]/campaigns/[campaignId]/iplusn-cost-savings.js
- ...next.js route-module-loader.js...
code: 'MODULE_NOT_FOUND'
```

HTTP 응답: 500. 해당 API 라우트를 호출하는 모든 요청이 실패.

## Root cause

Next.js SSR API 라우트 파일이 `require()`/`import`하는 npm 패키지가:
1. `web-console/package.json`에 선언되지 않았거나
2. pnpm 빌드 시 번들에 포함되지 않은 상태로 ECS에 배포된 경우

발생. 패키지가 devDependency로만 존재하거나, 다른 workspace 패키지의 의존성에만 선언된 경우에도 동일하게 발생한다.

## Classification

- **`needs_fix`**: 해당 API 라우트 기능이 완전 불능이고 콘솔 사용자에게 직접 영향을 미침
- `no_action`이 **아닌** 이유: 기능 실패가 반복되고 있으며 배포 수정 필요

## Scope attribution

Access log에서 실제 projectId와 campaignId를 직접 추출 가능:

```
GET /api/projects/<project_id>/campaigns/<campaign_id>/iplusn-cost-savings HTTP/1.1" 500
Referer: https://console.notifly.tech/ko/console/products/<product_id>/campaign/<campaign_id>/stats
```

`product_id`를 DynamoDB `project` table GSI `product_id-project_id-index`로 매핑.

## 2026-06-19 incident details

- **Project:** class101 (project_id: `b2b4a8f879a75673b755bff42fc1deb6`, product_id: `class101`)
- **Campaigns affected:** iViRLM, vKayDg
- **Missing package:** `google-spreadsheet`
- **API route:** `services/server/web-console/pages/api/projects/[projectId]/campaigns/[campaignId]/iplusn-cost-savings.ts`
- **Caller IP:** 112.220.222.90 (class101 콘솔 사용자)
- **Frequency (30d/7d/1d/10m):** 80 / 26 / 5 / 2 — 지속 반복

## Fix

`services/server/web-console/package.json`에 누락 패키지(`google-spreadsheet`) 의존성 추가 후 프로덕션 재배포.

또는 해당 라우트가 외부 패키지 없이 동작하도록 리팩토링.

## Note — `iplusn-cost-savings` 라우트

Google Sheets API를 통해 비용 절감 데이터를 조회하는 class101 전용 기능으로 보임. 패키지 재추가 시 Google Sheets API service account credential 설정도 함께 확인 필요.

## Alarm config

- Terraform: `infra/terraform/prod/ap-northeast-2/ecs/services.tf:1013`
- Namespace: `ConsoleErrors`
- Threshold: 1.0 (1건 이상 시 알람)
- Period: 60s, DatapointsToAlarm: 1
