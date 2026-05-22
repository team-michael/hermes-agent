hashimoto profile configured as Notifly monitoring-only bot, optimized for alert response rather than general coding tasks.
§
Model provider is Cloudflare Workers AI with @cf/moonshotai/kimi-k2.6, chosen for credit efficiency over Codex/Claude.
§
Slack gateway home channel is #monitoring (C04KT7EH5RQ); the bot responds to CloudWatch alarms and operational alerts in this channel.
§
User expects rigorous evidence chains for DLQ alarm conclusions. When classifying a DLQ as "transient AWS infrastructure error", must first show explicit supportive evidence (Lambda Errors=0, Throttles=0, no ERROR logs, maxReceiveCount=1, zero log-match for DLQ message content) before stating the hypothesis. Avoid stating conclusions as certainties without showing the supporting pattern.