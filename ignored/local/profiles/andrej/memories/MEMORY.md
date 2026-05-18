Notifly andrej `.env`: `SLACK_BOT_TOKEN`, `LINEAR_API_KEY`; Google Workspace uses `google-workspace` skill + `gws` CLI config dir from profile `.env`.
§
Notifly project lookup: project_id→DynamoDB project product_id/name; per-project PG tables `table_${project_id}`; AI Agent auth allows Cognito service_role=admin fallback after project resolves, otherwise users_products.
§
Notifly API data default: PG ETL/read-model aggregations first for LLM statistics/events/messages; Athena/S3 raw ledger only explicit fallback/debug/audit. Athena tables `notifly_event_logs`,`notifly_message_events`; filter `dt,h,project_id`.
§
Notifly docs live site `docs.notifly.tech` is Mintlify-backed from `notifly-tech/notifly-docs`; old `team-michael/notifly-docs` is deprecated Docusaurus/GitHub Pages.
§
Slack media Qs: if channel/thread IDs exist, fetch root/thread via Web API, inspect files/attachments, download authorized images, run vision.
§
CloudCheckr AU 2000841/a4dcbb7d uses `cloudcheckr-service-cost-api-fetch`; MaxSessionsNotice may end sessions; parallel backfills can OIDC `invalid_grant`, retry sequentially.
§
Git commit identity used in prior Notifly agent work: `Andrej Karpathy <team@greyboxhq.com>`.
§
For `team-michael/cloudflare-containers` Access-protected endpoints, Cloudflare Access service-token headers `cf-access-client-id` and `cf-access-client-secret` can be used when available; their values are secrets and should not be stored or printed.
§
Remote/container ops: local Hermes isn't target; verify hostname/whoami/pwd before filesystem/service mutations.
§
Notifly ECS SC: check `deployments[].serviceConnectConfiguration` (top-level may be null). Slack #engineering 2026-01-09: SC imposes 15s request timeout.
§
Notifly console: use `NOTIFLY_AUTH` email:password for `/ko/auth/login`; Michael Product is slug `michael` dashboard path.
§
Hermes `tarantino`: profile `/home/ubuntu/.hermes/profiles/tarantino`; related to `just-went-viral.com`; dashboard host `dashboard.just-went-viral.com`.
§
Notifly web/demo: English IDs; Korean docs; prod-like events; SDK projectId/username, password dummy; no public password env; `.env.example` not gate.