Env: ws=`~/.hermes/workspace`; gh=.env; AWS: Nico=EC2CloudWatchAgentRole, Andrej=notifly-internal-agent keys.
§
Notifly data: project_id→DDB product_id/name; per-project PG table_${pid}; DDL onboarding/preflight; FCM404/UNREGISTERED may null token; test sends need native token; project_statistics long-form UTC/KST09 billing rows.
§
Slack links: use SLACK_BOT_TOKEN replies/history; url_private images→vision.
§
Git: Notifly commit author=`Kyungseo Jaden Jeong <jerion7474@gmail.com>`; Gunwoo→`gunoooo`.
§
Cloudflare: never print tokens; Redis proxy ECS `cache-proxy` host `cache-proxy-prod-internal.notifly.tech`.
§
Remote/workflow ops: local Hermes isn't target; verify host; env/VPN/secrets tests use workflow_dispatch.
§
Notifly ECS ServiceConnect: inspect `deployments[].serviceConnectConfiguration`; SC timeout 15s.
§
Notifly console: `NOTIFLY_AUTH`; Michael slug `michael`; delivery list uses derived/Redis status; monitor completion Redis-only, no PG recovery unless reopened.
§
Notifly MCP OAuth façade uses existing api/web Cognito user pool/client policy; do not introduce a separate COGNITO_MCP_* user pool.
§
SDK Tracker paths: `~/.hermes/workspace/crm-sdk-tracker`, `~/.hermes/profiles/andrej/crm-sdk-tracker`; Android migration: private customer setup skills from authorized code; start coexist/shadow.
§
Notifly Alimtalk: direct/API split; BZM PUBLIC not lookupable; no `is_ad`/`failover_is_ad`; B/D/P scope; send wrapper `alimtalk_builder_delivery_send_and_query.sh`.
§
Notifly CE: SDK-compatible clean-room self-host; AGPL; feeds Cloud Standard.
§
Notifly Sentinel: RCA=campaign/UJ first, deploy later; decompose by channel. Biz/AM workflow lives in `notifly-bdm-sdr-am-playbook`. Pricing=business impact, not cause.
§
Trackit/GTM: `NOTIFLY_TRACKIT_API_KEY`; load `trackit-open-api-query` + BDM playbook; writes need approval; merge/relink unverified. Kyungseo says dedupe complete. Sheets: no-history prospects `1jnX98bW-KP-cXFQ9VeWzO3g_N8JBTRKywxBGGEpRZ6g`; SMTP people DB `1v9z5DGpWn98lKaIEaTSzhlieQq10V0VPjVg8BHzfHn4`.
§
Braze migration: official API first; browser Console only for proven required gaps; one read-only GET/resource; preserve raw JSON+metadata.