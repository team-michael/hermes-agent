ws ~/.hermes/workspace; JDK ~/.hermes/jdks/jdk-17; Android ~/.hermes/android-sdk; GH=profile .env; terminal sanitized.
§
Notifly: project_id→DDB product; tenant PG `table_${pid}`; DDL onboarding/preflight. FCM 404/UNREGISTERED may null device_token; test sends need native token. project_statistics long-form.
§
Docs: `notifly-event/docs`, `notifly-web`, `notifly-product-knowledge`; KR=노티플라이.
§
Slack: URL→conversations.replies(token); private files auth-download→vision. GDrive Kelly: gws cache; config `/home/ubuntu/.config/gws`.
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
Notifly Sentinel RCA: campaign/UJ·channel first, deploy later; pricing=impact 설명만.
§
Notifly delivery_result: provider casing 유지(NHN camel/Bizm snake); phone search future-only(no history/migration).
§
Notifly env: infra≠project.dev; Michael Prod=a0d696d1aba7535fad6710cddf3b1cab(false), Dev=b80c3f0e2fbd5eb986df4f1d32ea2871(true); Catalog test=prod infra+Dev; hourly scans existing `catalogs_<pid>`.
§
Notifly Liquid: project:{id}; tag=ctx.environments.project?.id; Catalog provider explicit init; no import side effect; DB-neutral.
§
Notifly 인증: users_products.certified_at=product source; Cognito custom runtime 미사용; admin bypass; UI는 campaign/UJ SMS selector·sender profile만, side effect는 server guard; legacy 이전 double-apply(custom:phone 제외).
§
Braze Catalog API: official 17-route input; v1 `{data,error}` output(list plural+next_cursor+links, single resource, no-resource mutation null, validation details); API unscheduled. CDI=UTC `*/N`; Sync Now keeps schedule.