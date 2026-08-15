Env: ws `~/.hermes/workspace`; gh: GITHUB_TOKEN at ~/.hermes/profiles/andrew/.env (not in shell env). export GITHUB_TOKEN=$(grep ^GITHUB_TOKEN= ~/.hermes/profiles/andrew/.env|cut -d= -f2-). git push: -c credential.helper=!f(){echo username=x-access-token;echo password $GITHUB_TOKEN;}f push origin BRANCH.
§
Notifly: project_id→DDB product_id/name; per-project PG table_${pid}; DDL via onboarding/preflight. Push RCA: FCM 404/UNREGISTERED nulls device_token; test sends need IS NOT NULL. project_statistics: billing indep(session_starts,events); event-log granularity; UTC/KST09.
§
Notifly docs: docs=`notifly-event/docs`; web=`notifly-web`; Product KB=`notifly-product-knowledge`. KR docs use '노티플라이'.
§
Slack: SLACK_BOT_TOKEN replies/history; url_private→vision.
§
Cloudflare: never print tokens. Redis: ElastiCache Valkey cluster mode ON (2 node groups) behind Envoy cache-proxy; app=standalone ioredis to proxy. `{}` hash tags matter for CROSSSLOT in Lua eval. Key convention: snake_case, colon-separated.
§
Remote/workflow ops: local Hermes isn't target; verify host; env/VPN/secrets tests use workflow_dispatch.
§
Notifly console: `NOTIFLY_AUTH`; Michael slug; delivery list=Redis status; monitor Redis-only.
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
Notifly CE: SDK clean-room self-host; AGPL.
§
Sentinel: trend RCA=campaign/UJ first, deploy later; decompose by channel.
§
Linear: LINEAR_API_KEY in shell env. GraphQL https://api.linear.app/graphql Bearer. Issue query: {issue(id:"NOTIFLY-XXXX"){id title description state{name} assignee{name} labels{nodes{name}} priority createdAt updatedAt}}