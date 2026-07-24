# PR #3709 web-console/api-service 검증 작업 계획

## 목표

PR: https://github.com/team-michael/notifly-event/pull/3709

다음 작업을 실행하기 전에 검토 가능한 형태로 계획을 고정한다.

1. PR 변경사항 확인: `web-console`, `api-service`
2. `web-console` 기존 기능 회귀 가능성 검토
3. `api-service`에서 생성한 campaign/user-journey가 `web-console`에서 정상 표시/동작하는지 테스트 시나리오 준비
4. API 호출 + Chrome 브라우저 접근으로 실제 검증
5. 인증은 env의 `NOTIFLY_AUTH` 값을 사용하되, secret은 명령/로그/결과에 출력하지 않음

> 현재 단계에서는 PR diff 확인, API 호출, 브라우저 테스트, 데이터 생성은 수행하지 않는다.

## 확정된 실행 조건

- 테스트 환경: `stage`
- 테스트 product/project: `michael` dev
- web-console 접속 endpoint: Cloudflare endpoint 사용
  - login URL: `https://fix-agent-models-console.notifly.tech/auth/login`
  - ECS endpoint 직접 접근은 사용하지 않음
- 테스트 데이터 cleanup: 삭제/아카이브하지 않고 prefix로 남김
- 결과 공유: Slack 보고만 수행
  - GitHub PR comment/review는 남기지 않음

## 범위와 원칙

- 대상 repo: `team-michael/notifly-event`
- 대상 경로:
  - `services/server/web-console/**`
  - `services/server/api-service/**`
  - 필요 시 공유 타입/스키마/패키지 경로
- 테스트 데이터 prefix:
  - `PR3709_E2E_<YYYYMMDDHHMM>_*`
- 실행 원칙:
  - 작업 승인 전에는 read-only 계획만 제공
  - 실행 승인 후에도 최소 권한/최소 데이터 생성
  - 테스트 데이터는 가능한 한 draft/paused 상태로 만들고 실제 발송/고객 노출 경로는 피함
  - 테스트 데이터는 cleanup하지 않고 prefix로 추적 가능하게 남김
  - `NOTIFLY_AUTH`는 env에서 읽기만 하고 echo/export/log 출력 금지
  - token/cookie/password/base64 credential은 결과에 출력하지 않음
  - 임시 스크립트/쿠키/결과 파일은 `~/.hermes/profiles/andrej/pr-3709-test/` 아래에만 저장

## 실행 계획

### 0. 대상 환경 고정

승인 후 가장 먼저 아래 상태를 확인한다.

- Cloudflare endpoint `https://fix-agent-models-console.notifly.tech`가 stage web-console로 연결되는지
- PR #3709 변경사항이 해당 stage endpoint에 반영되어 있는지
- `michael` dev product/project에서 테스트 데이터 생성이 가능한지
- API 호출 대상도 stage/api-service 기준으로 맞는지

주의:

- web-console은 ECS endpoint가 아니라 Cloudflare endpoint로만 검증한다.
- Cloudflare preview/front-door와 backend stage 배포 commit이 다를 수 있으므로, UI smoke 전에 현재 배포 SHA 또는 observable version이 있으면 확인한다.

### 1. PR 변경사항 확인

목표: PR이 바꾸는 계약을 먼저 이해한다. UI를 누르기 전에 데이터 모델/계약을 고정한다.

절차:

1. GitHub PR 메타/파일 목록 확인
   - title/body/base/head/status/checks
   - changed files 중 `web-console`, `api-service`, shared schema/type 추출
2. PR branch를 별도 worktree로 checkout
   - 기존 repo가 있으면 `~/.hermes/workspace/notifly-event` 사용
   - 없으면 `~/.hermes/workspace` 아래 clone
   - 작업 branch/worktree는 read-only 분석용
3. diff를 세 층으로 분류
   - API contract: endpoint, auth, request/response schema, validation, default 값
   - persistence/side effect: campaign/user-journey 생성 시 DB/DDB/queue/cache에 쓰는 필드
   - web-console consumption: list/detail/edit/preview/canvas가 읽는 필드와 enum
4. 산출물
   - 변경 파일 표
   - API 생성 payload/response 계약 요약
   - web-console이 기대하는 필드와 API가 실제 생성하는 필드 간 gap 후보

검토 포인트:

- campaign/user-journey ID, slug, name/title, type/channel enum 불일치
- status 기본값: draft/active/paused/archived 등
- schedule/trigger/audience/condition 기본값 누락
- created_by/source/origin 같은 provenance 필드가 UI 필터나 badge에 영향 주는지
- 날짜/timezone/null 처리
- API-created object가 web-console edit/duplicate/delete/activate 액션의 전제조건을 만족하는지

### 2. web-console 기존 기능 회귀 검토

목표: 새 API-created 객체 지원 때문에 기존 console-created 객체 흐름이 깨지지 않는지 확인한다.

리뷰 축:

1. 목록 화면
   - campaign list, user-journey list
   - pagination/search/filter/sort/status badge
   - 빈 값/null 값 렌더링
2. 상세/편집 화면
   - campaign detail/edit/preview
   - user-journey detail/canvas/node 설정
   - save/duplicate/archive/delete/activate 등 기존 액션
3. 기존 생성 플로우
   - web-console에서 campaign 생성
   - web-console에서 user-journey 생성
   - 기존 생성 객체가 API-created 객체 대응 코드 때문에 payload가 바뀌지 않는지
4. API/UI contract
   - web-console API route/proxy가 api-service 응답 shape 변화에 취약한지
   - shared type이 없으면 런타임 guard 또는 fallback 필요 여부
5. i18n/UX
   - 새 label/message가 하드코딩됐는지
   - 한국어/영어 locale 둘 다 깨지지 않는지

산출물:

- 회귀 위험: Critical / Warning / Suggestion / Looks Good
- 실제 테스트해야 할 high-risk UI path 목록

### 3. 테스트 시나리오 준비

테스트 데이터 이름 prefix:

```text
PR3709_E2E_<YYYYMMDDHHMM>_campaign_minimal
PR3709_E2E_<YYYYMMDDHHMM>_campaign_full
PR3709_E2E_<YYYYMMDDHHMM>_journey_minimal
PR3709_E2E_<YYYYMMDDHHMM>_journey_with_campaign_node
```

#### A. Campaign API-created → web-console 표시/동작

1. Minimal campaign 생성
   - API가 허용하는 최소 필수 필드만 사용
   - 기대:
     - campaign list에 표시
     - status/type/channel/name/created time이 깨지지 않음
     - detail 진입 가능
     - preview/edit 화면이 crash 없이 열림
2. Full campaign 생성
   - audience/condition/schedule/message/template 등 PR이 다루는 필드 포함
   - 기대:
     - web-console에서 각 섹션이 동일 의미로 렌더링
     - 저장 없이 열고 닫기 가능
     - 필요한 경우 편집 후 저장 payload가 기존 객체와 호환
3. 기존 web-console-created campaign smoke
   - 기존 UI 생성/목록/상세 진입이 계속 정상
   - API-created 대응 코드가 기존 생성 payload를 변경하지 않았는지 확인

#### B. User-journey API-created → web-console 표시/동작

1. Minimal journey 생성
   - 최소 노드/엣지 또는 API가 허용하는 최소 구조
   - 기대:
     - journey list에 표시
     - detail/canvas 진입 가능
     - 빈/기본 노드 상태가 crash 없이 렌더링
2. Campaign node 포함 journey 생성
   - API-created campaign을 journey node에 연결
   - 기대:
     - canvas에서 campaign node 이름/상태 표시
     - node 설정 panel에서 campaign 참조 정상
     - 저장/닫기/재진입 후 구조 유지
3. 기존 web-console-created journey smoke
   - UI 생성/편집/canvas 이동이 계속 정상

#### C. Negative/edge 시나리오

- API-created 객체의 optional field 누락
- unknown/새 enum이 들어왔을 때 UI fallback
- 삭제/아카이브된 campaign reference는 cleanup 정책상 직접 만들지 않고, 기존 데이터가 있으면 read-only로만 관찰
- 권한 없는 product/project 접근 시 web-console이 적절히 차단하는지
- 브라우저 console/network error 없음

### 4. 인증 및 API 호출 방식

`NOTIFLY_AUTH` 사용 원칙:

- env에서 `email:password` 형태로 읽음
- 값 자체, prefix, base64, token, cookie를 로그에 출력하지 않음
- shell command에 secret literal을 직접 넣지 않음
- 인증/요청 스크립트가 env를 읽고 request body를 구성
- 결과 출력은 HTTP status, object id/name, sanitized response summary만 남김

예상 흐름:

1. `.env` 로드
   - `/home/ubuntu/.hermes/profiles/andrej/.env`에서 환경변수 사용
2. Cloudflare web-console endpoint로 로그인
   - login URL: `https://fix-agent-models-console.notifly.tech/auth/login`
   - endpoint path는 실제 app route에 맞게 `/auth/login` 또는 locale route를 확인 후 사용
   - cookie jar 또는 session token 획득
3. API 호출
   - stage/api-service의 campaign 생성 endpoint 호출
   - stage/api-service의 user-journey 생성 endpoint 호출
   - 생성 결과에서 object id/name만 기록
4. 검증용 조회
   - API read endpoint로 생성 객체 shape 확인
   - Cloudflare web-console에서 동일 object가 조회/표시되는지 비교

### 5. Chrome/browser 검증 방식

브라우저 검증은 API 생성이 끝난 뒤 수행한다.

절차:

1. Chrome/browser context 준비
   - `https://fix-agent-models-console.notifly.tech/auth/login` 접속
   - `NOTIFLY_AUTH` 기반 인증 사용
   - Cloudflare endpoint 기준으로 session 유지
2. Campaign 검증
   - `michael` dev product/project 진입
   - list에서 `PR3709_E2E_*` 검색
   - detail/preview/edit 진입
   - status/type/channel/schedule/audience/message 섹션 확인
   - console error/network failed request 확인
3. User-journey 검증
   - list에서 `PR3709_E2E_*` 검색
   - canvas/detail 진입
   - node/edge/campaign reference 표시 확인
   - 저장 없이 닫기, 필요 시 safe edit 저장
   - console error/network failed request 확인
4. Evidence 수집
   - screenshot
   - sanitized API status/response summary
   - browser console/network error summary

### 6. 결과 보고 형식

실행 후 Slack에만 아래 형식으로 보고한다.

```text
결론: pass / fail / partial

1. PR 변경사항 요약
   - web-console: ...
   - api-service: ...
   - shared contract: ...

2. 회귀 검토
   - Critical: ...
   - Warning: ...
   - Suggestion: ...
   - Looks good: ...

3. 실제 테스트 결과
   - campaign minimal: pass/fail + evidence
   - campaign full: pass/fail + evidence
   - journey minimal: pass/fail + evidence
   - journey with campaign node: pass/fail + evidence
   - existing console-created smoke: pass/fail + evidence

4. 이슈/권장 수정
   - file/path 또는 화면 기준
   - 재현 단계
   - 기대/실제
   - 최소 수정 방향

5. 남은 리스크
   - Cloudflare endpoint와 backend stage 배포 SHA 차이 가능성
   - 테스트 데이터는 prefix로 남김
   - 실제 발송 경로 미검증 등
```

## 승인 후 바로 시작할 순서

1. PR #3709 메타/changed files/read-only diff 확인
2. `web-console`과 `api-service` 변경 계약 매핑
3. 회귀 위험 path 선정
4. stage + `michael` dev + Cloudflare endpoint 접근성 확인
5. env의 `NOTIFLY_AUTH`로 Cloudflare web-console 로그인 준비
6. API로 campaign/user-journey 테스트 데이터 생성
7. Chrome으로 `https://fix-agent-models-console.notifly.tech` 접속해 표시/동작 검증
8. 생성 데이터는 cleanup하지 않고 prefix로 남김
9. GitHub에는 남기지 않고 Slack에만 결과 보고
