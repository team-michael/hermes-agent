ws ~/.hermes/workspace; JDK ~/.hermes/jdks/jdk-17; Android ~/.hermes/android-sdk; GH=profile .env; terminal sanitized.
§
Notifly: project_id→DDB product; tenant PG `table_${pid}`; DDL onboarding/preflight. FCM 404/UNREGISTERED may null device_token; test sends need native token. project_statistics long-form.
§
Docs: `notifly-event/docs`, `notifly-web`, `notifly-product-knowledge`; KR=노티플라이.
§
Slack: URL→replies(token); private files auth→vision; @jeff reactions.write, 완료 alert=✅. GDrive Kelly: gws; `~/.config/gws`.
§
Git: `Jeff Dean <engineering@greyboxhq.com>`; Gunwoo Park→`gunoooo`.
§
Notifly ECS SC: inspect `deployments[].serviceConnectConfiguration`; request timeout 15s.
§
Notifly console: `NOTIFLY_AUTH`; Michael slug `michael`; delivery list uses derived/Redis status; monitor completion Redis-only, no PG recovery unless reopened.
§
Notifly MCP OAuth façade uses existing api/web Cognito user pool/client policy; do not introduce a separate COGNITO_MCP_* user pool.
§
SDK Tracker: crm-sdk-tracker/andrej; Android=승인 customer setup 기반 coexist/shadow.
§
Notifly Alimtalk: direct/API; BZM PUBLIC lookup 불가; B/D/P; send wrapper.
§
Notifly Sentinel RCA: campaign/UJ·channel first, deploy later; pricing=impact 설명만.
§
Notifly IDs: message_id=전 채널 recipient×channel UUIDv5; 기존 Push/SDK notifly_message_id만 동일값 alias. execution/SQS/provider/event ID 분리; delivery_result casing=NHN camel/Bizm snake.
§
Notifly env: infra≠project.dev; Michael Prod=a0d696d1aba7535fad6710cddf3b1cab(false), Dev=b80c3f0e2fbd5eb986df4f1d32ea2871(true); Catalog test=prod infra+Dev; hourly scans existing `catalogs_<pid>`.
§
Notifly Liquid: project:{id}; tag=ctx.environments.project?.id; Catalog provider explicit init; no import side effect; DB-neutral.
§
Notifly 인증: users_products.certified_at=product source; Cognito custom runtime 미사용; admin bypass; UI는 campaign/UJ SMS selector·sender profile만, side effect는 server guard; legacy 이전 double-apply(custom:phone 제외).
§
Catalog API: 17 routes; v1 envelope; list cursor/links; mutations 200+null; unscheduled/shared rate limit; requires non_personal declaration; public/Liquid fail closed; no heuristic DLP. CDI UTC `*/N`; Sync Now keeps schedule.