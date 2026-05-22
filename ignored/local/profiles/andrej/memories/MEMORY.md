Notifly andrej `.env` path `/home/ubuntu/.hermes/profiles/andrej/.env` (`$HOME` may be tflint-home); Google Workspace uses `google-workspace` + `gws` config from profile env.
§
Notifly project lookup: project_id→DynamoDB project product_id/name; per-project PG tables `table_${project_id}`; AI Agent auth allows Cognito service_role=admin fallback after project resolves, otherwise users_products.
§
Notifly API/fact data default: PG/read-model first; Athena raw only explicit debug/audit. Campaign-user facts route as `/campaigns/{campaignId}/users/{notiflyUserId}/eligibility` and `/deliveries`.
§
Notifly docs live site `docs.notifly.tech` is Mintlify-backed from `notifly-tech/notifly-docs`; old `team-michael/notifly-docs` is deprecated Docusaurus/GitHub Pages.
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