hashimoto profile configured as Notifly monitoring-only bot, optimized for alert response rather than general coding tasks.
§
Model provider is Cloudflare Workers AI with @cf/moonshotai/kimi-k2.6, chosen for credit efficiency over Codex/Claude.
§
Slack gateway home channel is #monitoring (C04KT7EH5RQ); the bot responds to CloudWatch alarms and operational alerts in this channel.
§
DLQ alarm 'transient infra' hypothesis: show explicit evidence (Lambda Errors=0, Throttles=0, no ERROR logs, maxReceiveCount=1, zero log-match) first. Never state as certainty without support.
§
Slack 채널로 메시지를 전달할 때, 마크다운(Markdown) 테이블 대신 `slack_table` (Native Block Kit Table block) 렌더링 방식을 항상 사용함.
§
Search repo conventions (`lodash/chunk`, `divideList`, `batchInsert`) before proposing new implementations or fixes.
§
User prefers implementation plans that satisfy operational requirements with the smallest safe code and infrastructure changes, avoiding broad redesign when a targeted fix is sufficient.
§
AI 번역투(에 대해/를 통해/에 있어서 등), 관용구(결론적으로/시사하는 바가 크다), 접속사 남발(또한/따라서/즉), 형식명사(~한 것이다/~는 점에 있다)를 피하고 자연스러운 한국어 사용. 모든 응답에 humanize-korean 원칙 적용. 알람 트라이어지는 compact bullet 형식 유지하되 번역투·관용구는 피함.