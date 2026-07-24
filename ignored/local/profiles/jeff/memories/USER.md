Infra/DB: live config/code/data/EXPLAIN; index rewrite 우선, DDL·수동 recovery는 승인 후; env 구분; 상태 matrix 선호.
§
Notifly RCA: terse KR·evidence first; observed≠inferred; SDK blame 전 live code/data/timing 확인; signOut/deleteToken은 timestamp 필수; FCM404≠401.
§
In DMs, user wants infra explanations tailored to Mobile/iOS+SDK Eng background: use analogies only when mechanisms match; flag SDK implications for contracts/retries/offline/telemetry/DX.
§
PR 최소 diff; Knex=QueryBuilder 우선(raw 최소); UI 필수=native bubble+앱 i18n.
§
Vendor/MSP tickets: no internal refs; cause-only/minimal; paste-ready plain text, no code fences.
§
CS/SaaS: source-only; public docs/review counts; facts≠estimates; preserve sheet visuals; MCP discovery.
§
Docs/UX: KR humanized; facts≠inference; examples=actual values·semantics·vendor syntax; ambiguous UI는 구현 전 options; research MD=요약→사례→작업→링크.
§
GFSA 외부심사: 내부 ID/PR/티켓/SHA/Slack 링크 제외; 기능·KR 진행률·근거만.
§
Linear: 신규=Todo, 진행=In Progress. Done 전 issue criteria→PR/main·test·live matrix 대조; project Done 누락도 확인.
§
코드: 기존/stdlib·최소 diff; 추측 abstraction/중복 guard 금지; 설정·파일명·합의 architecture=contract; merge review=current head 계약 drift 확인; 장시간 승인.
§
독립 작업은 병렬·origin/main PR. workflow_dispatch는 deploy/upload/update/apply 부재 확인 전 금지; notifly lambda_ci_cd dispatch는 prod deploy.
§
UX 계약: 화면 용어와 실제 동작 일치. 삭제≠비활성화; soft delete를 삭제로 표시하지 않음.