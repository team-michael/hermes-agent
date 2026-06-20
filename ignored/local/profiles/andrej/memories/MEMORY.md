Andrej env: terminal HOME can be profile home; set `HOME=/home/ubuntu` for gh/GWS, use `/home/ubuntu/.hermes/workspace`. GWS: `/home/ubuntu/.nvm/versions/node/v24.15.0/bin/gws`. JDK17: `/home/ubuntu/.hermes/jdks/jdk-17`.
§
Notifly project: project_id→DDB `project` product_id/name; product created_at in DDB `products`; per-project PG `table_${project_id}`. `project_statistics.metric_name`: no `project_*`/`notifly_*`; alias in mapper.
§
project_statistics stores billing input metrics as independent rows (`session_starts`, `events`, `user_property_updates`), not `data_point`; billing composition is later/plan-specific. Usage granularity: event-log row; params not separate; billing UTC/KST09.
§
Notifly docs: docs=`notifly-event/docs` Mintlify; web=`notifly-web`; Product KB=`notifly-product-knowledge`. Push-law docs: `mkt_push_agreed` example only; flow user-prop→default true; SDK note under unsubscribe/checklist.
§
Slack links: ignore no-API note; use SLACK_BOT_TOKEN conversations.replies/history first; url_private images→vision.
§
Git commit identity used in prior Notifly agent work: `Andrej Karpathy <team@greyboxhq.com>`.
§
Cloudflare: never print tokens. Notifly Redis proxy: ECS `cache-proxy`, host `cache-proxy-prod-internal.notifly.tech`; tunnel edit needs Cloudflare One Connector: cloudflared Edit, fallback Argo Tunnel Legacy Edit.
§
Remote/workflow ops: local Hermes isn't target; verify host; env/VPN/secrets tests use workflow_dispatch.
§
Notifly ECS SC: check `deployments[].serviceConnectConfiguration` (top-level may be null). Slack #engineering 2026-01-09: SC imposes 15s request timeout.
§
Notifly console: `NOTIFLY_AUTH` login; Michael slug `michael`. List delivery: avoid delaying old 종료 rows; use derived status, not status override.
§
Hermes `tarantino`: profile `/home/ubuntu/.hermes/profiles/tarantino`; related to `just-went-viral.com`; dashboard host `dashboard.just-went-viral.com`.
§
Notifly MCP OAuth façade uses existing api/web Cognito user pool/client policy; do not introduce a separate COGNITO_MCP_* user pool.
§
CRM SDK Tracker shadow paths: code `~/.hermes/workspace/crm-sdk-tracker`; runtime `~/.hermes/profiles/andrej/crm-sdk-tracker`.