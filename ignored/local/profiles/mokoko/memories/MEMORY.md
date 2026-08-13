문서: 사고는 Draft에 사실만, 미확정=‘작성 필요’; 복구=Timeline, 조치=강제형. Tech spec은 1pager로 짧게 쓰고 append 대신 재조립. 구현은 내부 checkpoint로 연속 진행하고 권한·credential만 요청.
§
설계·코드·배포·실관측 구분. tenant DDL=RO→canary→전체. create_tables CI=PG16.11 base/merge diff↔DDB project·prod catalog. 검증은 test tenant 하나에 probe 컬럼만 적용해 나머지 mismatch 실패 확인. 비-required; 전용 PG role 전엔 기존 read-only+timeout·catalog-only.
§
Notifly 조회는 고객↔project 먼저 매핑. DDB 부재는 Git·offboarding 확인. 수동 차단은 blame·live activity 확인. SDK 공개 경로는 API key를 가정하지 않고 middleware→tenant binding→shard ID를 추적. PG 변수는 POSTGRES_*.
§
Payple 접근 정책: 공유 키 O(n) scan·명시적 race. 확정 무효만 web-console 7일 유예 후 차단, 미확인 오류는 영구 fail-open·marker 유지. 저장 후 transient는 0/1/3/10초 status-only 재확인하며 key 재발급 금지. blocked-origin 잠금은 blocked 관측이 아니라 사용자가 recovery를 시작한 때부터 유지함.
§
PR Assignee `TheClevers`; 인증≠commit author. 최소 변경·remote head·타인 변경 비덮기 선호. 코드 변경의 ‘커밋’ 요청은 원격 branch push까지 포함함. 리뷰어 확인→답변·resolve·재검토하며 push 직후 CI 대기 없이 알림. Linear는 작업별 새 이슈를 본인 할당하고 관련 없는 parent/subissue 연결 금지.
§
사용자는 Notifly MCP 연결 문서에서 ChatGPT 데스크톱·웹·Codex·Claude 설정을 구분하고 설치·인증·도구 갱신에 집중하길 원함. 변경 중엔 게시 App보다 live Custom MCP를 선호하며 연결 폼 스크린샷 1장이면 충분하다고 봄.
§
Popup 다국어 authoring은 앱·웹 모두 지원. Web Console locale key는 zh-CN/zh-TW이며 사용자 locale `zh`는 어느 쪽도 추정하지 않고 `zh` key 부재 시 default로 fallback. API 단일언어 캠페인은 Console에서 열려야 함.
§
User table: `users_`=encrypted SoT. Read는 `executeUserQuery`; shadow helper 복원 금지. Write transformer 정리는 별도 후속이며 `user_` DROP 전 user_-only 프로젝트 조사.
§
사용자는 API/MCP를 동일 parser·schema·실 렌더 경로로 검증하며 jq 생성 필드와 원 응답을 구분함. 보안은 credential≠tenant binding, 기존 취약점≠PR 확장으로 판단.
§
사용자는 위험 계약의 극소수 실경로 테스트를 선호함. schema CI는 merge 전 prod test tenant probe→전체 mismatch 실패→복구로 확인하며 mock·중복 assertion은 피함. tenant/global schema는 변경된 쪽만 독립 검사하고 둘 다 변경 시 두 check를 원함.
§
Brand Message: stale pending은 동일 ID pending→terminal 이력·request terminal과 SQS/DLQ·Poller 로그로 검증. #4201은 identity 전파이며 사후 pending 수정 아님. Poller는 `batchItemFailures` 반환만 merge됐고 prod ESM retry는 꺼져 있음. 순수 poll retry는 안전하나 SMS failover·N resend는 enqueue→checkpoint 틈의 중복 위험 때문에 멱등성 후 `ReportBatchItemFailures`를 켜야 함.
§
유저 여정/API 계약 설명은 validation 성공 여부와 downstream 변환·저장 실패를 구분하고, helper 변경은 ‘로직 변화’와 ‘중첩 함수 이동·재사용’을 코드 레벨로 분리해 설명한다.