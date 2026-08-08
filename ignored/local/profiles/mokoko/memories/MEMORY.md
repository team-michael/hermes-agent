사고문서: tech docs incidents/Draft, 설명→타임라인→영향→5 Whys→원인→교훈→조치. 확인 사실만 쓰고 미확정은 ‘작성 필요’. 복구·롤백·완료 migration은 Resolution/Timeline, Action Items는 정책/체크리스트가 아닌 시스템 강제형 재발방지만 둠.
§
카카오 직접/NHN Brand 경계 엄격. gap=requested_at cohort accepted↔checkpoint-persisted collected. 실측은 project/product/dev 귀속 확인, 내부 test≠고객 baseline. settle≠retry budget; 표본 부족 시 민감 정책→실관측 조정.
§
사용자는 설계·코드·배포·실관측을 구분함. tenant DDL은 read-only→canary→전체. migration은 검증된 V0 중앙 ledger→version/checksum→onboarding·배포 gate를 선호함. 배포는 SHA→artifact→runtime·queue/DLQ·로그/checkpoint를 검증함. 비용은 유사 traffic 기준.
§
사용자는 AI Agent usage를 완료된 14일 KST 기준 대시보드·일별·프로젝트/모델/MCP·Top4 대화·Raw 탭으로 선호함.
§
Notifly 조회는 고객사↔project ID를 먼저 매핑하고, DDB에 없으면 Git history·UUIDv5·offboarding 이력으로 식별함. PG 변수는 POSTGRES_*.
§
Payple 접근 정책: 공유 키 O(n) scan·명시적 race. 확정 무효만 web-console 7일 유예 후 차단, 미확인 오류는 영구 fail-open·marker 유지. 저장 후 transient는 0/1/3/10초 status-only 재확인하며 key 재발급 금지. blocked-origin 잠금은 blocked 관측이 아니라 사용자가 recovery를 시작한 때부터 유지함.
§
PR Assignee `TheClevers`; 인증≠commit author. 최소 변경·remote head·타인 변경 비덮기·scaffolding 제거 선호. 모든 리뷰어 확인→답변·resolve·재검토, push 직후 CI 대기 없이 알림. Linear는 본인 할당·PR 상호 링크, PR 설명은 배경→동작→기준→검증과 다른 PR의 Linear 표기 형식 선호.
§
사용자는 Notifly MCP 연결 문서에서 ChatGPT 데스크톱·웹·Codex·Claude 설정을 구분하고 설치·인증·도구 갱신에 집중하길 원함. 변경 중엔 게시 App보다 live Custom MCP를 선호하며 연결 폼 스크린샷 1장이면 충분하다고 봄.
§
Locale 정책: 유저 속성 우선, 없으면 지원 신규 SDK 기기값; exact→base→default. title/body/imageUrl/link는 locale별, importance/disableBadge/customizedMessageData/isAd는 전 locale 동기화. 다국어 설정은 메시지 설정 1번 항목이며 tooltip은 사용자 최신 커밋 문구가 기준.
§
사용자는 legacy read의 실제 실행 SQL을 추적해 prod가 `users_` only면 죽은 `user_`/shadow helper를 제거함. 비암호화 read는 `executeQuery`로 직접 전환하고, 변경은 Lambda/ECS 배포·관측 단위 PR로 나누며 write·복호화 경로는 섞지 않음.
§
사용자는 MCP 계약(timezone·형식·경계·freshness·빈 결과·집계)을 schema/description에 명시하고 실패 payload를 동일 parser/tool schema로 재현한 뒤 교정 payload의 실제 통과까지 검증함. 생성 리소스는 web-console Zod 기준 public→view_state→detail/edit 왕복을 맞추며 무의미한 래퍼·UI fallback을 싫어함. writer/backfill을 분리하고 OpenAPI·MCP ref도 검증함. AI Assistant는 내부 tool명만 숨기고 공개 API/SDK명은 유지하며 결과·필요 입력만 사용자 관점으로 말하길 원함.
§
사용자는 핵심 위험 계약의 극소수 테스트만 선호함. API/MCP는 create→save→detail 왕복·adapter 변환만 남기고 내부구조·중복 assertion·UI exact-match/mock spec을 피함.