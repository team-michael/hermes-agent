# web-console `iplusn-cost-savings` — MODULE_NOT_FOUND (`google-spreadsheet`)

## Pattern Summary

**Alarm**: `/aws/ecs/notifly-services-prod/web-console/sentry alert`  
**First seen**: 2026-06-11 (PR #3741 머지 2026-06-08 이후)  
**Error**: `Cannot find module 'google-spreadsheet'`  
**Transaction**: `GET /api/projects/[projectId]/campaigns/[campaignId]/iplusn-cost-savings`

## Dependency Chain

```
iplusn-cost-savings.ts  (web-console Next.js API route)
  └─ import { PriceTagRepository } from '@notifly/pricing'
       └─ packages/pricing/src/repository/PriceTagRepository.ts
            └─ require('google-spreadsheet')   ← not found in .next bundle
```

`packages/pricing/package.json`에 `google-spreadsheet: ^4.1.1`이 `dependencies`로 선언되어 있지만,
web-console `.next` 서버 사이드 번들 빌드 시 해당 모듈이 포함되지 않아 런타임 에러 발생.

이 패턴은 `references/web-console-module-not-found-api-route.md`(workspace dep 심볼릭 링크 누락)와
**다른** 유형: pnpm 모노레포 내 로컬 패키지(`@notifly/pricing`)의 **transitive dependency**가
Next.js 서버 번들에서 externalize되지 않아 발생하는 빌드 누락.

## Introducing PR

- **PR #3741** `feat(web-console): 브랜드 메시지 I+N 타겟 UI + 비용 절감 카드 [NOTIFLY-893]`
- 머지: 2026-06-08, 첫 알람: 2026-06-11

핵심 파일:
- `services/server/web-console/src/pages/api/projects/[projectId]/campaigns/[campaignId]/iplusn-cost-savings.ts`
- `packages/pricing/package.json` — `google-spreadsheet: ^4.1.1`

## Alarm History Pattern

이 알람은 `INSUFFICIENT_DATA → ALARM` 전환을 사용한다 (`OK → ALARM` 아님).
Sentry 이벤트가 발생할 때만 metric filter가 값을 기록하고, 이벤트 간 quiet 구간에서는
`INSUFFICIENT_DATA`로 돌아가기 때문. 헬퍼의 `alarm_count_7d/30d` (OK→ALARM 집계)는 0으로
반환되지만 `raw HistoryData`에서 `INSUFFICIENT_DATA → ALARM` 전환을 집계하면 실제 빈도가 나온다.

빈도 (2026-06-19 기준): 30d 50회 / 7d 28회 / 1d 7회  
빈도 (2026-06-21 기준): 30d 63회 / 7d 22회 / 1d 1회 (동일 패턴 지속 재발 확인)

## Impact

- 브랜드 메시지(I+N) 비용 절감 카드 API 100% 실패
- 캠페인 통계 화면에서 I+N 비용 절감 데이터 표시 불가
- 메시지 발송 자체는 영향 없음 (읽기 경로만 영향)

## Fix Direction

1. `next.config.js`의 `transpilePackages`에 `@notifly/pricing` 추가 (Next.js가 패키지를 직접 번들링)
2. 또는 `serverExternalPackages`에서 `google-spreadsheet` 명시적 externalize 후 빌드 이미지에 포함
3. 또는 `iplusn-cost-savings.ts`에서 `PriceTagRepository` 대신 `google-spreadsheet` 없이
   동작 가능한 별도 repository 클래스 분리 (가장 안전)

## Classification

- **Status**: `needs_fix`
- **Scope**: 브랜드 메시지 I+N 기능 사용 전 프로젝트 (특정 project/campaign 불특정)
- **Service**: web-console ECS
- **Tracking**: 2026-06-11 최초 발생 이후 2026-06-21까지 `needs_fix` 미처리 상태 지속.
  알람 발생 시 위 빈도 수치를 갱신하고 Fix Direction 중 하나가 적용됐는지 PR 여부를 확인할 것.
