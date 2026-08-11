사고문서: tech docs incidents/Draft, 설명→타임라인→영향→5 Whys→원인→교훈→조치. 확인 사실만 쓰고 미확정은 ‘작성 필요’. 복구·롤백·완료 migration은 Resolution/Timeline, Action Items는 정책/체크리스트가 아닌 시스템 강제형 재발방지만 둠.
§
카카오 직접/NHN Brand 경계 엄격. gap=requested_at cohort accepted↔checkpoint-persisted collected. 실측은 project/product/dev 귀속, 내부 test≠고객 baseline. settle≠retry budget. 경보 E2E는 공유 poller 정지보다 가역 metric 주입·상쇄를 선호함.
§
설계·코드·배포·실관측 구분. tenant DDL은 read-only→canary→전체. create_tables required PR CI는 base/head PG catalog diff의 변경 객체만 prod tenant 전체와 대조하고 미변경 PR은 즉시 통과, symlink는 무결성만 확인. DROP/RENAME은 경고+prod 일치로 허용하고 expand→전환→contract. 배포는 SHA→artifact→runtime·queue/DLQ·로그 검증, 비용은 유사 traffic 기준.
§
Notifly 조회는 고객사↔project ID를 먼저 매핑하고, DDB에 없으면 Git history·UUIDv5·offboarding 이력으로 식별함. PG 변수는 POSTGRES_*.
§
Payple 접근 정책: 공유 키 O(n) scan·명시적 race. 확정 무효만 web-console 7일 유예 후 차단, 미확인 오류는 영구 fail-open·marker 유지. 저장 후 transient는 0/1/3/10초 status-only 재확인하며 key 재발급 금지. blocked-origin 잠금은 blocked 관측이 아니라 사용자가 recovery를 시작한 때부터 유지함.
§
PR Assignee `TheClevers`; 인증≠commit author. 최소 변경·remote head·타인 변경 비덮기 선호. 코드 변경의 ‘커밋’ 요청은 원격 branch push까지 포함함. 리뷰어 확인→답변·resolve·재검토하며 push 직후 CI 대기 없이 알림. Linear는 작업별 새 이슈를 본인 할당하고 관련 없는 parent/subissue 연결 금지.
§
사용자는 Notifly MCP 연결 문서에서 ChatGPT 데스크톱·웹·Codex·Claude 설정을 구분하고 설치·인증·도구 갱신에 집중하길 원함. 변경 중엔 게시 App보다 live Custom MCP를 선호하며 연결 폼 스크린샷 1장이면 충분하다고 봄.
§
Locale 계약: 고객 `$locale`, SDK 관찰 `$last_observed_locale`은 encrypted user props에 저장하고 SDK는 observed만 갱신함. 발송은 `$locale`→observed, 후보별 exact→language-only→localized default; localized 없을 때만 legacy `message`; whole-object 선택. CSV user_id_based는 DB props, direct CSV는 row의 예약 key를 사용함.
§
`user_` 물리 DROP은 미루고 legacy SQL·shadow/dual-write 명칭을 먼저 제거함. 비암호화 read는 `users_` direct query로 deploy-unit별 병렬 PR, 모두 배포 후 공통 helper 삭제. write·복호화는 분리하며 구현세부 spec은 생략 가능.
§
사용자는 MCP 실패를 동일 parser/tool schema로 재현하고 web-console Zod 통과만으로 정상 판정하지 않으며 source-handle/edge ID 인코딩까지 실제 렌더 경로로 검증함.
§
사용자는 핵심 위험 계약의 극소수 테스트와 실제 호출 순서 추적을 선호함. guard 존재만으로 실행 여부를 단정하지 않고 resolver→payload→log→side effect 경계를 구분함. API/MCP는 create→save→detail 왕복·adapter 변환만 남기고 내부구조·중복 assertion·UI exact-match/mock spec을 피함.