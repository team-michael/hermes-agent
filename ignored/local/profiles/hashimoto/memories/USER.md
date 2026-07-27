hashimoto profile configured as Notifly monitoring-only bot, optimized for alert response rather than general coding tasks.
§
Model provider is Cloudflare Workers AI with @cf/moonshotai/kimi-k2.6, chosen for credit efficiency over Codex/Claude.
§
Slack gateway home channel is #monitoring (C04KT7EH5RQ); the bot responds to CloudWatch alarms and operational alerts in this channel.
§
User expects rigorous evidence chains for DLQ alarm conclusions. When classifying a DLQ as "transient AWS infrastructure error", must first show explicit supportive evidence (Lambda Errors=0, Throttles=0, no ERROR logs, maxReceiveCount=1, zero log-match for DLQ message content) before stating the hypothesis. Avoid stating conclusions as certainties without showing the supporting pattern.
§
Slack 채널로 메시지를 전달할 때, 마크다운(Markdown) 테이블 대신 `slack_table` (Native Block Kit Table block) 렌더링 방식을 항상 사용함.
§
User expects existing codebase conventions to be searched first before proposing new implementations or fixes. For example, when asked about batch-insert sizing or chunking patterns, search the repo for `lodash/chunk`, `divideList`, and `batchInsert` usage and report them as precedent.
§
User prefers implementation plans that satisfy operational requirements with the smallest safe code and infrastructure changes, avoiding broad redesign when a targeted fix is sufficient.