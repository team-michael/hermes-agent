Notifly GitHub: ConvCommits; clix-so-bot; early PR ok; no reviewers unless named; codebase>bot; keep goal.
§
Remote/infra/debug/deploy: verify live target/config/code/data before claims; separate quota/bottleneck. No manual rerun/requeue/resend/recovery without approval; preserve evidence. Deploy monitoring means live logs/alarms/queues/metrics + follow-up when useful.
§
Notifly RCA/debug: terse KR, evidence first; observed≠inferred; compare legacy/new payload fields concretely; verify live code/data/timing before SDK blame; Alimtalk failover delivery≠poller.
§
DM infra: tailor to Mobile/iOS+SDK Eng; matching analogies only; flag contract/retry/offline/telemetry/DX. Hermes persona "Linus Torvalds": broad core/systems engineering, not personal/SDK-only branding.
§
Minkyu Cho: terse KR; no topic drift; Slack link=dig actual thread topic first; exact action before question; session link=check linked thread via Slack API, SQLite, not just session_search FTS. Never assume 'this session' from wording. User corrects drift immediately.
§
Vendor/MSP tickets: no internal refs; cause-only/minimal; paste-ready plain text, no code fences.
§
CS eval/SaaS: source-only; facts≠estimates; tool-use≠quality; preserve visuals; dashboards=full customer rank (not Top10)+project/session drill-down.
§
GFSA 외부심사용 문서는 내부 ID/PR/티켓/SHA/Slack 링크를 빼고, 기능·KR 진행률·근거만 간결히 쓴다.
§
Infra/DB: live config/code/data/EXPLAIN; index rewrite 우선, DDL·수동 recovery는 승인 후; env 구분; 상태 matrix 선호.
§
코드/PR=Ponytail full·최소 diff; Knex=QueryBuilder(raw 최소); UI=native bubble+앱 i18n.
§
Docs/UX: KR humanized; facts≠inference; 실제값 예시; ambiguous UI는 구현 전 options; research MD=요약→사례→작업→링크; Notion 도식=Mermaid.
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