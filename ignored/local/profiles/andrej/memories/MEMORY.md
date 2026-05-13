Slack: profile `.env` has SLACK_BOT_TOKEN; use Slack Web API for permalinks/threads without printing tokens. Google Workspace: use `google-workspace` skill + `gws` CLI with `GOOGLE_WORKSPACE_CLI_CONFIG_DIR` from profile `.env`.
§
Notifly project lookup convention: when a `project_id` is found, map it through the DynamoDB `project` table and include the corresponding product_id/name; PostgreSQL per-project tables follow the `table_name_${project_id}` naming pattern.
§
Notifly analytics Athena defaults: region `ap-northeast-2`, workgroup `primary`, database `notifly_analytics`, result output `s3://raw-events-query-logs/athena-query-results/`; key tables include `notifly_event_logs` and `notifly_message_events`, commonly filtered by `dt`, `h`, `project_id`, and `pre_conversion`.
§
Notifly docs live site `docs.notifly.tech` is Mintlify-backed from `notifly-tech/notifly-docs`; old `team-michael/notifly-docs` is deprecated Docusaurus/GitHub Pages.
§
Slack media Qs: if channel/thread IDs exist, fetch root/thread via Web API, inspect files/attachments, download authorized images, run vision.
§
CloudCheckr AU: for customer 2000841/account a4dcbb7d-0bb4-4f2c-a6c6-51a80586d728 use skill `cloudcheckr-service-cost-api-fetch`; user permits ending other sessions on MaxSessionsNotice.
§
Git commit identity used in prior Notifly agent work: `Andrej Karpathy <team@greyboxhq.com>`.
§
For `team-michael/cloudflare-containers` Access-protected endpoints, Cloudflare Access service-token headers `cf-access-client-id` and `cf-access-client-secret` can be used when available; their values are secrets and should not be stored or printed.
§
For remote/container operations from Slack, Hermes terminal acts on local Hermes runtime unless explicit SSH/API target is established and verified; before filesystem/service mutation, verify target identity with hostname/whoami/pwd.
§
Notifly ECS SC: check `deployments[].serviceConnectConfiguration` (top-level may be null). Slack #engineering 2026-01-09: SC imposes 15s request timeout.
§
Notifly console: use `NOTIFLY_AUTH` email:password for `/ko/auth/login`; Michael Product is slug `michael` dashboard path.