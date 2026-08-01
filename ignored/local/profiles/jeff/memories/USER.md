Infra/DB: live config/code/data/EXPLAIN; index rewrite 우선, DDL·수동 recovery는 승인 후; env 구분; 상태 matrix 선호.
§
Notifly RCA: terse KR·evidence first; observed≠inferred; SDK blame 전 live code/data/timing 확인; signOut/deleteToken은 timestamp 필수; FCM404≠401.
§
DM 인프라 설명은 Mobile/iOS·SDK Eng 배경 기준; 정확한 비유만, contract/retry/offline/telemetry/DX 영향 표시.
§
코드/PR=Ponytail full·최소 diff·작은 수정 direct; final 전 push/반복 review 금지·CI 1회; 대기=bg 알림 후 즉답; Knex=QB; DDL=bootstrap/기존-table 수동 분리·추측 default/backfill 금지·단일 rollout·*_at 타입 유지; UI=native+i18n.
§
Vendor/MSP: no internal refs; cause-only; paste-ready plain text.
§
CS/SaaS: source-only; facts≠estimates; preserve visuals; MCP discovery.
§
Docs/UX: KR humanized; facts≠inference; 실제값 예시; ambiguous UI는 구현 전 options; research MD=요약→사례→작업→링크; Notion 도식=Mermaid.
§
GFSA 외부심사: 내부 ID/PR/티켓/SHA/Slack 링크 제외; 기능·KR 진행률·근거만.
§
Linear: 신규=Todo, 진행=In Progress. Done 전 issue criteria→PR/main·test·live matrix 대조; project Done 누락도 확인.
§
코드/API: 기존·stdlib·최소 diff; API 응답은 live 기존 패턴 확인 후 일관성 우선; 추측 abstraction·중복 guard 금지; architecture=contract; active_messages(message_id/status core); review=current head.
§
독립 작업은 병렬·origin/main PR. workflow_dispatch는 deploy/upload/update/apply 부재 확인 전 금지; notifly lambda_ci_cd dispatch는 prod deploy.
§
UX 계약: 화면 용어와 실제 동작 일치. 삭제≠비활성화; soft delete를 삭제로 표시하지 않음.
§
Slack 링크는 channel/thread_ts를 추출해 API로 조회하길 기대.