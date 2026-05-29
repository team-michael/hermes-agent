Andrej GWS: source `/home/ubuntu/.hermes/profiles/andrej/.env`; if `gws` missing use `/home/ubuntu/.nvm/versions/node/v24.15.0/bin/gws`.
§
Notifly project: MCP/CS agents know requester project; gold flows don't call `list_projects` to resolve it. project_id→DDB product/name; per-project PG `table_${project_id}`; AI admin fallback after lookup.
§
Notifly API/fact data default: PG/read-model first; Athena raw only explicit debug/audit. Campaign-user facts route as `/campaigns/{campaignId}/users/{notiflyUserId}/eligibility` and `/deliveries`.
§
Notifly docs: live `docs.notifly.tech` from `notifly-tech/notifly-docs`; old `team-michael/notifly-docs` deprecated. Product KB repo: `team-michael/notifly-product-knowledge` private main, has `llms*.txt`.
§
Slack links: use SLACK_BOT_TOKEN API first; url_private images→vision.
§
CloudCheckr AU 2000841/a4dcbb7d uses `cloudcheckr-service-cost-api-fetch`; MaxSessionsNotice may end sessions; parallel backfills can OIDC `invalid_grant`, retry sequentially.
§
Git commit identity used in prior Notifly agent work: `Andrej Karpathy <team@greyboxhq.com>`.
§
Cloudflare: for Access-protected endpoints, use available service-token headers when present; for Notifly front-door/config debugging, use `CLOUDFLARE_READONLY_API_TOKEN` read-only API before relying only on Terraform. Token values are secrets; never print/store.
§
Remote/workflow ops: local Hermes isn't target; verify host; env/VPN/secrets tests use workflow_dispatch.
§
Notifly ECS SC: check `deployments[].serviceConnectConfiguration` (top-level may be null). Slack #engineering 2026-01-09: SC imposes 15s request timeout.
§
Notifly console: use `NOTIFLY_AUTH` email:password for `/ko/auth/login`; Michael Product is slug `michael` dashboard path.
§
Hermes `tarantino`: profile `/home/ubuntu/.hermes/profiles/tarantino`; related to `just-went-viral.com`; dashboard host `dashboard.just-went-viral.com`.
§
Notifly MCP OAuth façade uses existing api/web Cognito user pool/client policy; do not introduce a separate COGNITO_MCP_* user pool.
§
CRM SDK Tracker shadow paths: code `~/.hermes/workspace/crm-sdk-tracker`; runtime `~/.hermes/profiles/andrej/crm-sdk-tracker`.