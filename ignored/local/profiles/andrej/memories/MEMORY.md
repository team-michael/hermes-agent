Andrej env: set `HOME=/home/ubuntu` for gh/GWS; workspace `/home/ubuntu/.hermes/workspace`; GWS node v24.15 path; JDK17 at `~/.hermes/jdks/jdk-17`.
§
Notifly: project_id→DDB product_id/name; per-project PG table_${pid}; DDL via onboarding/preflight. Push RCA: FCM 404/UNREGISTERED can null device_token; test sends require native device_token IS NOT NULL. project_statistics long-form metrics.
§
project_statistics: billing rows independent (`session_starts`,`events`,`user_property_updates`), no `data_point`; event-log granularity; billing UTC/KST09; use count/value+dimensions/window predicates.
§
Notifly docs: docs=`notifly-event/docs`; web=`notifly-web`; Product KB=`notifly-product-knowledge`. KR docs use ‘노티플라이’.
§
Slack links: use SLACK_BOT_TOKEN replies/history; url_private images→vision.
§
Git identity: `Andrej Karpathy <team@greyboxhq.com>`.
§
Cloudflare: never print tokens. Redis proxy: ECS `cache-proxy`, host `cache-proxy-prod-internal.notifly.tech`; tunnel edit uses Cloudflare One Connector, fallback Legacy Edit.
§
Remote/workflow ops: local Hermes isn't target; verify host; env/VPN/secrets tests use workflow_dispatch.
§
Notifly ECS SC: check `deployments[].serviceConnectConfiguration` (top-level may be null). Slack #engineering 2026-01-09: SC imposes 15s request timeout.
§
Notifly console: `NOTIFLY_AUTH`; Michael slug `michael`; delivery list uses derived/Redis status; monitor completion Redis-only, no PG recovery unless reopened.
§
Hermes `tarantino`: profile `/home/ubuntu/.hermes/profiles/tarantino`; related to `just-went-viral.com`; dashboard host `dashboard.just-went-viral.com`.
§
Notifly MCP OAuth façade uses existing api/web Cognito user pool/client policy; do not introduce a separate COGNITO_MCP_* user pool.
§
SDK Tracker paths: `~/.hermes/workspace/crm-sdk-tracker`, `~/.hermes/profiles/andrej/crm-sdk-tracker`; Android migration: private customer setup skills from authorized code; start coexist/shadow.
§
Notifly Alimtalk: snapshot create/update; direct branch only; no broad Any*. BZM PUBLIC not lookupable; send rendered msg/buttons.
§
Notifly CE: SDK-compatible clean-room self-host; AGPL; feeds Cloud Standard.
§
Kyungseo Jeong is male.