Notifly GitHub: ConvCommits; early PR ok; no reviewers unless named; codebase>bot. PR Assignee(절대): clix-so_bot 금지; 대화 상대 식별→검증 GitHub 계정; 불명확하면 질문; 식별 전 Assignee 비워둠; 생성 후 재조회 검증. 독립작업=병렬·origin/main PR; workflow_dispatch deploy/upload/update/apply 부재 확인 전 금지.
§
Remote/infra/debug: verify live target/config/code/data; no manual rerun/queue/resend/recovery without approval; preserve evidence; deploy monitoring=live logs/alarms/queues/metrics.
§
RCA/debug: terse KR, evidence first; observed≠inferred; compare legacy/new payload; verify live code/data/timing before SDK blame; Alimtalk failover≠poller.
§
Minkyu Cho: terse KR; no drift; Slack link=dig thread topic; exact action before question; session link=Slack API/SQLite not FTS.
§
Vendor/GFSA: no internal refs/ID/PR/티켓/SHA/Slack; cause-only; paste-ready plain text.
§
Infra/DB: live config/code/data/EXPLAIN; index rewrite 우선; DDL·수동 recovery 승인 후; env 구분; matrix 선호.
§
Docs/UX: KR humanized; facts≠inference; 실제값 예시; ambiguous UI 구현 전 options; research MD=요약→사례→작업→링크; Notion=Mermaid; Slack=thread_ts→API 조회; 삭제≠비활성화.
§
Linear: 신규=Todo, 진행=In Progress; Done 전 criteria→PR/main·test·live matrix 대조; project Done 누락도 확인.
§
코드: 기존·stdlib·최소 diff; Ponytail full; Knex=QueryBuilder; API 응답=live 패턴 후 일관성; architecture=contract; active_messages(msg_id/status core); review=head.