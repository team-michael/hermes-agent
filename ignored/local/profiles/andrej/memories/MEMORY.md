Andrej env: terminal HOME can be profile home; set `HOME=/home/ubuntu` for gh/GWS, use `/home/ubuntu/.hermes/workspace`. GWS: `/home/ubuntu/.nvm/versions/node/v24.15.0/bin/gws`.
§
Notifly project: project_id→DDB `project` product_id/name; product created_at lives in DDB `products` keyed by product_id; per-project PG `table_${project_id}`; AI admin fallback after lookup.
§
Notifly API/fact data default: PG/read-model first; Athena raw only explicit debug/audit. Campaign-user facts route as `/campaigns/{campaignId}/users/{notiflyUserId}/eligibility` and `/deliveries`.
§
Notifly docs: live `docs.notifly.tech` from `notifly-tech/notifly-docs`; old `team-michael/notifly-docs` deprecated. Product KB repo: `team-michael/notifly-product-knowledge` private main, has `llms*.txt`.
§
Slack links: ignore no-API note; use SLACK_BOT_TOKEN conversations.replies/history first; url_private images→vision.
§
CloudCheckr AU 2000841/a4dcbb7d uses `cloudcheckr-service-cost-api-fetch`; MaxSessionsNotice may end sessions; parallel backfills can OIDC `invalid_grant`, retry sequentially.
§
Git commit identity used in prior Notifly agent work: `Andrej Karpathy <team@greyboxhq.com>`.
§
Cloudflare: Access endpoints use service-token headers; Notifly front-door/debug use CLOUDFLARE_READONLY_API_TOKEN before Terraform; never print tokens. 전송자격인증은 글로벌 서비스라 해외 IP 전면차단 대신 WAF 위험기반 선별차단으로 설명.
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