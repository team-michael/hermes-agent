Env: ws `~/.hermes/workspace`; gh in profile `.env`; JDK `~/.hermes/jdks/jdk-17`; Android SDK `~/.hermes/android-sdk`.
§
Notifly: project_id→DDB product_id/name; per-project PG table_${pid}; DDL via onboarding/preflight. Push RCA: FCM 404/UNREGISTERED can null device_token; test sends require native device_token IS NOT NULL. project_statistics long-form metrics.
§
project_statistics: billing rows independent (`session_starts`,`events`,`user_property_updates`), no `data_point`; event-log granularity; billing UTC/KST09; use count/value+dimensions/window predicates.
§
Notifly docs: docs=`notifly-event/docs`; web=`notifly-web`; Product KB=`notifly-product-knowledge`. KR docs use '노티플라이'.
§
Slack links: use SLACK_BOT_TOKEN replies/history; url_private images→vision.
§
Git: `Andrej Karpathy <team@greyboxhq.com>`; Gunwoo Park→`gunoooo`.
§
Cloudflare: never print tokens. Redis proxy: ECS `cache-proxy`, host `cache-proxy-prod-internal.notifly.tech`; tunnel edit uses Cloudflare One Connector, fallback Legacy Edit.
§
Remote/workflow ops: local Hermes isn't target; verify host; env/VPN/secrets tests use workflow_dispatch.
§
Notifly ECS SC: check `deployments[].serviceConnectConfiguration` (top-level may be null). Slack #engineering 2026-01-09: SC imposes 15s request timeout.
§
Notifly console: `NOTIFLY_AUTH`; Michael slug `michael`; delivery list uses derived/Redis status; monitor completion Redis-only, no PG recovery unless reopened.
§
Notifly MCP OAuth façade uses existing api/web Cognito user pool/client policy; do not introduce a separate COGNITO_MCP_* user pool.
§
SDK Tracker paths: `~/.hermes/workspace/crm-sdk-tracker`, `~/.hermes/profiles/andrej/crm-sdk-tracker`; Android migration: private customer setup skills from authorized code; start coexist/shadow.
§
Notifly Kakao: Alimtalk no ad flags. templateId row→row.template.sender_platform; missing row→legacy provider code. NHN resend≠BZM params.
§
delivery_result: provider casing 유지(NHN camel/Bizm snake); phone search future-only(no history/migration).
§
env: infra≠project.dev; Michael Prod=a0d696d1aba7535fad6710cddf3b1cab(false), Dev=b80c3f0e2fbd5eb986df4f1d32ea2871(true); Catalog test=prod infra+Dev; hourly scans existing `catalogs_<pid>`.
§
Liquid: project:{id}; tag=ctx.environments.project?.id; Catalog provider explicit init; no import side effect; DB-neutral.
§
인증: users_products.certified_at=product source; Cognito custom runtime 미사용; admin bypass; UI는 campaign/UJ SMS selector·sender profile만, side effect는 server guard; legacy 이전 double-apply(custom:phone 제외).
§
Braze Catalog API: official 17-route input; v1 `{data,error}` output(list plural+next_cursor+links, single resource, no-resource mutation null, validation details); API unscheduled. CDI=UTC `*/N`; Sync Now keeps schedule.
§
GDrive: gws cache; config `/home/ubuntu/.config/gws`.
§
Notifly CE: SDK-compatible clean-room self-host; AGPL; feeds Cloud Standard.
§
Kyungseo Jeong is male.
§
Notifly Sentinel: trend RCA = campaign/UJ first, deploy later; decompose by channel; pricing only business-impact explanation, not cause/priority.