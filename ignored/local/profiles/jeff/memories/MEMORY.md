ws ~/.hermes/workspace; JDK ~/.hermes/jdks/jdk-17; Android ~/.hermes/android-sdk; GH=profile .env; terminal sanitized.
§
Notifly: project_id→DDB product; tenant PG `table_${pid}`; DDL onboarding/preflight. FCM 404/UNREGISTERED may null device_token; test sends need native token. project_statistics long-form.
§
Docs repos: `notifly-event/docs`, `notifly-web`, `notifly-product-knowledge`; KR ‘노티플라이’.
§
Slack: SLACK_BOT_TOKEN; private images→vision. Google Drive/Docs: Kelly(sdr)=cached gws `/home/ubuntu/.hermes/cache/gws-install/gws`, config `/home/ubuntu/.config/gws`.
§
Git: `Jeff Dean <engineering@greyboxhq.com>`; Gunwoo Park→`gunoooo`.
§
Notifly ECS SC: inspect `deployments[].serviceConnectConfiguration`; request timeout 15s.
§
Notifly console: `NOTIFLY_AUTH`; Michael slug `michael`; delivery list uses derived/Redis status; monitor completion Redis-only, no PG recovery unless reopened.
§
Notifly MCP OAuth façade uses existing api/web Cognito user pool/client policy; do not introduce a separate COGNITO_MCP_* user pool.
§
SDK Tracker: `~/.hermes/workspace/crm-sdk-tracker` 및 andrej profile; Android는 승인된 customer setup 기반 coexist/shadow migration.
§
Notifly Alimtalk: direct/API; BZM PUBLIC lookup 불가; is_ad/failover_is_ad 없음; B/D/P; send wrapper.
§
Notifly Sentinel: trend RCA = campaign/UJ first, deploy later; decompose by channel; pricing only business-impact explanation, not cause/priority.
§
Notifly delivery_result: extra_data provider casing 유지(NHN camel, Bizm snake); phone search future-only, no historical fallback/migration.
§
Notifly env axes independent: infra prod/stage/dev vs project.dev. Michael Prod=a0d696d1aba7535fad6710cddf3b1cab(false), Dev=b80c3f0e2fbd5eb986df4f1d32ea2871(true). Catalog test=infra prod+b80. UI source-agnostic. Hourly batch scans existing `catalogs_<pid>` tables only; missing tables are skipped.
§
Notifly Liquid: project:{id}; tag=ctx.environments.project?.id; Catalog provider explicit init; no import side effect; DB-neutral.
§
Notifly 본인인증: users_products(user_id,product_id).certified_at가 source; Cognito custom:certified_at은 runtime 미사용; service-admin bypass; legacy 이전은 조건부 double-apply, custom:phone 제외.