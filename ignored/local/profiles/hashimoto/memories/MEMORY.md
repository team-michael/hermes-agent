Triage status: `no_action` for spikes/recovered/known benign; `needs_fix` for trackable issues; `needs_fix`/`urgent` only with concrete cause. `project-metadata-generator lambda error` = check for missing-project Athena noise signature via DynamoDB `project` table.
§
Sentry email alert pipeline: always catalog-check title+transaction+message before no_action. When payload truncates and user asks "어떤 프로젝트?", use Logs Insights with `date -d "<ISO 8601>" +%s` timestamp verification to recover full payload, extract productId from request.url, map via DynamoDB GSI (prefer dev=false), parse request.query for campaign IDs/mode. Do NOT re-run helper. Unix timestamp miscalc pitfall: 1753592700 vs 1785133500 for 2026-07-27 06:25 UTC caused MalformedQueryException.
§
Skill library: `software-development/check`는 external_dirs에 등록되어 autonomous skill_manage write_file이 차단됨. reference 추가/큰 변경 시 foreground에서 `hermes curator adopt software-development/check` 권장. 사용자가 `korean-martech-prospect-research` 스킬 업데이트를 요구함 — autonomous skill_manage write_file이 가능한지 확인 후 시도, blocked 시 `hermes curator adopt` 방식 안내.
§
DLQ triage when Lambda looks healthy: `maxReceiveCount=1` + partial batch or downstream rejection can still land messages in DLQ. Inspect DLQ body, RedrivePolicy, and consumer logs. Never assume healthy Lambda metrics prove no backlog.
§
AWS access hashimoto profile: `execute_code`는 `~/.hermes/profiles/hashimoto/.env`를 자동으로 로드하지 않음. boto3/aws CLI 전에 `terminal`에서 `set -a; source /home/ubuntu/.hermes/profiles/hashimoto/.env; set +a`로 Notifly account `702197142747` 인증을 로드해야 함.
§
GitHub PR 생성 정책: `clix-so-bot`을 Assignee로 절대 지정하지 않음. 요청자를 세션에서 식별하고 검증된 해당 사용자의 GitHub 계정으로 Assignee 지정. 매핑 불명확 시 추정하지 않고 질문; 식별 전까지 Assignee는 비워둠. PR 생성 후 GitHub에서 Assignee 다시 조회해 검증.
§
ECS console error/log-derived alarm 트라이어지: `원인:`은 현재 alarm window의 정확 ERROR/Exception/SQL signature로 시작. 보존 항목: error message, constraint/table, rowCount, duration/requestId, projectId. helper가 empty면 Logs Insights ERROR/Exception fallback 실행 후에도 없으면 `can_answer=false`. 빈도·상태는 `빈도:`에만.