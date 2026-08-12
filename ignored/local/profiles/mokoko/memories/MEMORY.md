문서: 사고는 Draft에 사실만, 미확정=‘작성 필요’; 복구=Timeline, 조치=강제형. Tech spec은 1pager로 짧게 쓰고 append 대신 재조립. 구현은 내부 checkpoint로 연속 진행하고 권한·credential만 요청.
§
카카오 직접/NHN/Brand 경계 엄격. 직접연동 알림톡 anomaly는 metric gap보다 PG stale pending·LIMIT1을 선호하며 초기 window는 30~40분. PG pending은 insert/checkpoint 실패 blind spot. 내부≠고객 baseline. 누락 1건도 중요.
§
설계·코드·배포·실관측 구분. tenant DDL=RO→canary→전체. create_tables CI=PG16.11 base/merge diff↔DDB project·prod catalog. 검증은 test tenant 하나에 probe 컬럼만 적용해 나머지 mismatch 실패 확인. 비-required; 전용 PG role 전엔 기존 read-only+timeout·catalog-only.
§
Notifly 조회는 고객사↔project ID를 먼저 매핑하고, DDB에 없으면 Git history·UUIDv5·offboarding 이력으로 식별함. PG 변수는 POSTGRES_*.
§
Payple 접근 정책: 공유 키 O(n) scan·명시적 race. 확정 무효만 web-console 7일 유예 후 차단, 미확인 오류는 영구 fail-open·marker 유지. 저장 후 transient는 0/1/3/10초 status-only 재확인하며 key 재발급 금지. blocked-origin 잠금은 blocked 관측이 아니라 사용자가 recovery를 시작한 때부터 유지함.
§
PR Assignee `TheClevers`; 인증≠commit author. 최소 변경·remote head·타인 변경 비덮기 선호. 코드 변경의 ‘커밋’ 요청은 원격 branch push까지 포함함. 리뷰어 확인→답변·resolve·재검토하며 push 직후 CI 대기 없이 알림. Linear는 작업별 새 이슈를 본인 할당하고 관련 없는 parent/subissue 연결 금지.
§
사용자는 Notifly MCP 연결 문서에서 ChatGPT 데스크톱·웹·Codex·Claude 설정을 구분하고 설치·인증·도구 갱신에 집중하길 원함. 변경 중엔 게시 App보다 live Custom MCP를 선호하며 연결 폼 스크린샷 1장이면 충분하다고 봄.
§
Locale: priority=`$locale`→project configured→`$last_observed_locale`→default(exact→language); localized 없으면 legacy `message`. Popup API 다국어 생성 불필요, API 단일언어 캠페인은 Web Console에서 열려야 함. `/user-state`는 localized popup만 단일 `message`로 resolve하고 `localized_messages` 제거. campaign-only는 localized 때 `user_properties`만 좁게 조회(full getUserData/device 금지), `userData` 숨김. runtime 선배포→authoring.
§
`user_` DROP은 후순위. legacy SQL·shadow/dual-write부터 제거. `executeQueryWithShadowing`은 현재 `query`를 무시하고 `shadowing.query`(`users_`) 1회만 실행·복호화함. cleanup Linear 하나 아래 deploy-unit별 병렬 PR, 전부 배포 후 공통 helper 삭제; write 분리.
§
사용자는 MCP 실패를 동일 parser/tool schema로 재현하고 web-console Zod 통과만으로 정상 판정하지 않으며 source-handle/edge ID 인코딩까지 실제 렌더 경로로 검증함.
§
사용자는 위험 계약의 극소수 테스트·실제 호출 순서를 선호함. guard만으로 실행을 단정하지 않고 경계를 구분함. API/MCP는 create→save→detail 왕복·adapter만, schema CI는 local PG 실제 ADD/DROP pass/fail을 선호하며 내부구조·중복 assertion·mock spec을 피함.