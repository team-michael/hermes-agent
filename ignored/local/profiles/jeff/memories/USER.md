Infra/DB: live config/code/data/EXPLAIN; index rewrite 우선, DDL·수동 recovery는 승인 후; env 구분; 상태 matrix 선호.
§
Notifly RCA: terse KR·evidence first; observed≠inferred; SDK blame 전 live code/data/timing 확인; signOut/deleteToken은 timestamp 필수; FCM404≠401.
§
DM 인프라 설명은 Mobile/iOS·SDK Eng 배경 기준; 정확한 비유만, contract/retry/offline/telemetry/DX 영향 표시.
§
코드/PR=Ponytail·최소 diff; final 전 push/재리뷰 금지·CI 1회; Ready 후 CodeRabbit/Codex; Knex=QB; DDL=bootstrap/기존수동 분리·추측 default/backfill 금지·*_at 유지; Catalog schedule/timezone=함께 nullable·no default/CHECK; UI=native+i18n.
§
Vendor/MSP: 외부 안전·원인 중심·자연스러운 KR·바로 붙여넣는 plain text.
§
CS/SaaS=source-only·facts≠estimates·visuals 유지·MCP discovery.
§
Docs/UX=KR humanized·facts≠inference·실제값 예시; ambiguous UI 전 options; research MD=요약→사례→작업→링크; Notion=Mermaid.
§
GFSA 외부심사: 내부 ID/PR/티켓/SHA/Slack 링크 제외; 기능·KR 진행률·근거만.
§
Linear: 신규=Todo, 진행=In Progress. Done 전 issue criteria→PR/main·test·live matrix 대조; project Done 누락도 확인.
§
코드/API: 기존·stdlib·최소 diff; API 응답은 live 기존 패턴 확인 후 일관성 우선; 추측 abstraction·중복 guard 금지; architecture=contract; active_messages(message_id/status core); review=current head.
§
독립 작업=병렬·origin/main PR; workflow_dispatch 전 deploy/upload/update/apply 부재 확인; notifly lambda_ci_cd=prod deploy.
§
UX 계약: 화면 용어와 실제 동작 일치. 삭제≠비활성화; soft delete를 삭제로 표시하지 않음.
§
외부 링크는 원본 API로 확인; GWS 가능 시 disposable Sheet를 직접 생성·정리해 E2E.