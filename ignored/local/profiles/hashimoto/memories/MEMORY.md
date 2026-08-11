Triage status: `no_action` for spikes/recovered/known benign; `needs_fix` for trackable issues; `needs_fix`/`urgent` only with concrete cause. `project-metadata-generator lambda error` = check for missing-project Athena noise signature via DynamoDB `project` table.
§
Sentry email alert pipeline: always catalog-check title+transaction+message before no_action. When payload truncates and user asks "어떤 프로젝트?", use Logs Insights with `date -d "<ISO 8601>" +%s` timestamp verification to recover full payload, extract productId from request.url, map via DynamoDB GSI (prefer dev=false), parse request.query for campaign IDs/mode. Do NOT re-run helper. Unix timestamp miscalc pitfall: 1753592700 vs 1785133500 for 2026-07-27 06:25 UTC caused MalformedQueryException.
§
check skill은 external_dirs라 autonomous write blocked. 대형 변경 시 `hermes curator adopt software-development/check` 필요. user-journey-kinesis-record-dispatcher: SQS→notifly-user-journey-node-stream, @notifly/kinesis가 InternalFailure partial failure를 삼켜 누락 가능, 로그에 project_id 없음. 패턴은 notifly-alert-patterns skill에 저장.
§
DLQ triage when Lambda looks healthy: `maxReceiveCount=1` + partial batch or downstream rejection can still land messages in DLQ. Inspect DLQ body, RedrivePolicy, and consumer logs. Never assume healthy Lambda metrics prove no backlog.
§
AWS access hashimoto profile: `execute_code`는 `~/.hermes/profiles/hashimoto/.env`를 자동으로 로드하지 않음. boto3/aws CLI 전에 `terminal`에서 `set -a; source /home/ubuntu/.hermes/profiles/hashimoto/.env; set +a`로 Notifly account `702197142747` 인증을 로드해야 함.
§
GitHub PR 생성 정책: `clix-so-bot`을 Assignee로 절대 지정하지 않음. 요청자를 세션에서 식별하고 검증된 해당 사용자의 GitHub 계정으로 Assignee 지정. 매핑 불명확 시 추정하지 않고 질문; 식별 전까지 Assignee는 비워둠. PR 생성 후 GitHub에서 Assignee 다시 조회해 검증.
§
Skill update boundary: `software-development/check` lives in `skills.external_dirs`, so autonomous `skill_manage` patches are refused. DLQ/reference improvements for Notifly alert triage that don't fit inside the helper code should be routed to `notifly-sqs-dlq-investigation` or `notifly-alert-patterns` (curator-managed devops skills) instead.