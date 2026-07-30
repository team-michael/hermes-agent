Alert status: `no_action` for false positives/spikes/recovered, `needs_fix` for trackable non-urgent work, `urgent` only for active outages. Internal `internal-api-service` AI_AGENT_METRIC chat_aborted without error stack is noise. Korean replies use compact bullets (원인/범위/빈도/고객영향도/즉시조치) in that order; `no_action` = 5 bullets, no action-item line.
§
Sentry email alert pipeline: always catalog-check title+transaction+message before no_action. When payload truncates and user asks "어떤 프로젝트?", use Logs Insights with `date -d "<ISO 8601>" +%s` timestamp verification to recover full payload, extract productId from request.url, map via DynamoDB GSI (prefer dev=false), parse request.query for campaign IDs/mode. Do NOT re-run helper. Unix timestamp miscalc pitfall: 1753592700 vs 1785133500 for 2026-07-27 06:25 UTC caused MalformedQueryException.
§
kakao-delivery-result-poller-queue-dlq: Lambda Errors=0, DLQ ApproximateReceiveCount=4(>maxReceiveCount=3), poll_attempt=0(producer가 백어넣은 값). Root: Kakao completed_failure(handled) → batchItemFailure → 3번 재시도 후 DLQ. depth<50 안정=no_action; 수백+증가추세 단일캠페인>80%=needs_fix. 새 DLQ에 오래된 메시지(>100k s)+단 답변 대상 주 queue=0 → 과거 잔재물, no_action. `notifly-`/`michael`/console-stage.notifly.tech = 내벀용, 고객무영향.
§
사용자는 Slack 영어 알럿에 대한 한국어 답변을 간략하게 작성하길 원함. sentry email alert pipeline(no_action) 답변은 3~4줄 내외로 압축.
§
kakao-brand-message-delivery Lambda: INFO `request_body` logs match `%ERROR|Status: timeout%` filter as false positives. When alarm fires and Lambda Errors=0/Throttles=0/Duration normal with INFO dominating `current_top_signatures`, classify `no_action`. Real ERRORs are handled biz rejections (`resultCode: -3002`). Cannot persist to external `check` skill.
§
cafe24-worker DLQ redrive: redrive via `start_message_move_task` only when last `inertia22 rate limited` log is >15 min old (backoff window expired). If active within 15 min, schedule a 15-minute cron recheck rather than ask user to wait.