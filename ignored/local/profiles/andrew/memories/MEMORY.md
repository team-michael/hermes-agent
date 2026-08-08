Env: ws `~/.hermes/workspace`; gh in profile `.env`; JDK `~/.hermes/jdks/jdk-17`; Android SDK `~/.hermes/android-sdk`.
§
Notifly: project_id→DDB product_id/name; per-project PG table_${pid}; DDL via onboarding/preflight. Push RCA: FCM 404/UNREGISTERED can null device_token; test sends require native device_token IS NOT NULL. project_statistics long-form metrics.
§
project_statistics: billing independent(`session_starts`,`events`); event-log granularity; UTC/KST09.
§
Notifly docs: docs=`notifly-event/docs`; web=`notifly-web`; Product KB=`notifly-product-knowledge`. KR docs use '노티플라이'.
§
Slack links: use SLACK_BOT_TOKEN replies/history; url_private images→vision.
§
Git: `Andrej Karpathy <team@greyboxhq.com>`; Gunwoo Park→`gunoooo`.
§
Cloudflare: never print tokens. Redis proxy: ECS `cache-proxy`, host `cache-proxy-prod-internal.notifly.tech`.
§
Remote/workflow ops: local Hermes isn't target; verify host; env/VPN/secrets tests use workflow_dispatch.
§
Notifly ECS SC: `deployments[].serviceConnectConfiguration`; SC 15s timeout.
§
Notifly console: `NOTIFLY_AUTH`; Michael slug; delivery list=Redis status; monitor Redis-only.
§
Notifly MCP OAuth: existing api/web Cognito pool; no separate COGNITO_MCP_*.
§
SDK Tracker: `~/.hermes/workspace/crm-sdk-tracker`; Android=coexist/shadow.
§
Notifly Kakao: Alimtalk no ad flags; templateId→sender_platform; NHN resend≠BZM.
§
delivery_result: maxReceiveCount=1 intentional; provider casing 유지; phone search future-only.
§
env: infra≠project.dev; Michael Prod=a0d696d1aba7535fad6710cddf3b1cab, Dev=b80c3f0e2fbd5eb986df4f1d32ea2871.
§
Liquid: project:{id}; tag=ctx.environments.project?.id; Catalog explicit init; DB-neutral.
§
인증: certified_at=product source; admin bypass; legacy double-apply(custom:phone 제외).
§
Braze Catalog: 17-route; v1 `{data,error}`; CDI=UTC `*/N`.
§
CloudTrail: notifly-admin=Management only; SQS data events 미기록.
§
Notifly CE: SDK clean-room self-host; AGPL.
§
Kyungseo Jeong is male.
§
Sentinel: trend RCA=campaign/UJ first, deploy later; decompose by channel.