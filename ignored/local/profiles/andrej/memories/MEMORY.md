Notifly andrej `.env` path `/home/ubuntu/.hermes/profiles/andrej/.env` (`$HOME` may be tflint-home); Google Workspace uses `google-workspace` + `gws` config from profile env.
§
Notifly project lookup: project_id→DynamoDB project product_id/name; per-project PG tables `table_${project_id}`; AI Agent auth allows Cognito service_role=admin fallback after project resolves, otherwise users_products.
§
Notifly API/fact data default: PG/read-model first; Athena raw only explicit debug/audit. Campaign-user facts route as `/campaigns/{campaignId}/users/{notiflyUserId}/eligibility` and `/deliveries`.
§
Notifly docs live site `docs.notifly.tech` is Mintlify-backed from `notifly-tech/notifly-docs`; old `team-michael/notifly-docs` is deprecated Docusaurus/GitHub Pages.
§
Slack media: fetch thread/root, download authorized files/images, then vision.
§
CloudCheckr AU 2000841/a4dcbb7d uses `cloudcheckr-service-cost-api-fetch`; MaxSessionsNotice may end sessions; parallel backfills can OIDC `invalid_grant`, retry sequentially.
§
Git commit identity used in prior Notifly agent work: `Andrej Karpathy <team@greyboxhq.com>`.
§
For `team-michael/cloudflare-containers` Access-protected endpoints, Cloudflare Access service-token headers `cf-access-client-id` and `cf-access-client-secret` can be used when available; their values are secrets and should not be stored or printed.
§
Remote/workflow ops: local Hermes isn't target; verify host; env/VPN/secrets tests use workflow_dispatch.
§
Notifly ECS SC: check `deployments[].serviceConnectConfiguration` (top-level may be null). Slack #engineering 2026-01-09: SC imposes 15s request timeout.
§
Notifly console: use `NOTIFLY_AUTH` email:password for `/ko/auth/login`; Michael Product is slug `michael` dashboard path.
§
Hermes `tarantino`: profile `/home/ubuntu/.hermes/profiles/tarantino`; related to `just-went-viral.com`; dashboard host `dashboard.just-went-viral.com`.
§
Notifly web/demo: English IDs; Korean docs; prod-like events; SDK projectId/username, password dummy; no public password env; `.env.example` not gate.
§
CRM SDK Tracker shadow paths: code `~/.hermes/workspace/crm-sdk-tracker`; runtime `~/.hermes/profiles/andrej/crm-sdk-tracker`.