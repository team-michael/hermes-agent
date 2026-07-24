Env: ws `~/.hermes/workspace`; gh in profile `.env`; JDK `~/.hermes/jdks/jdk-17`; Android SDK `~/.hermes/android-sdk`.
§
Notifly: project_id→DDB product_id/name; per-project PG table_${pid}; DDL via onboarding/preflight. Push RCA: FCM 404/UNREGISTERED can null device_token; test sends require native device_token IS NOT NULL. project_statistics long-form metrics.
§
project_statistics: billing rows independent (`session_starts`,`events`,`user_property_updates`), no `data_point`; event-log granularity; billing UTC/KST09; use count/value+dimensions/window predicates.
§
Notifly docs: docs=`notifly-event/docs`; web=`notifly-web`; Product KB=`notifly-product-knowledge`. KR docs use ‘노티플라이’.
§
Slack links: use SLACK_BOT_TOKEN replies/history; url_private images→vision.
§
Git: `Andrej Karpathy <team@greyboxhq.com>`; Gunwoo Park→`gunoooo`.
§
Cloudflare: tokens 비공개. Redis proxy=ECS `cache-proxy`/`cache-proxy-prod-internal.notifly.tech`; tunnel=One Connector, fallback Legacy Edit.
§
Remote ops: 대상 host 검증; env/VPN/secret 점검은 workflow_dispatch 사용.
§
Notifly ECS SC: check `deployments[].serviceConnectConfiguration` (top-level may be null). Slack #engineering 2026-01-09: SC imposes 15s request timeout.
§
Notifly console: `NOTIFLY_AUTH`; Michael slug `michael`; delivery list uses derived/Redis status; monitor completion Redis-only, no PG recovery unless reopened.
§
Notifly MCP: api/web Cognito 재사용. Non-app-push draft는 Kakao/SMS/email sender 정보 오류 위험.
§
Notifly Kakao: Alimtalk no ad flags. templateId row→row.template.sender_platform; missing row→legacy provider code. NHN resend≠BZM params.
§
Kyungseo Jeong is male.
§
Notifly Sentinel: trend RCA = campaign/UJ first, deploy later; decompose by channel; pricing only business-impact explanation, not cause/priority.
§
Notifly 다국어: 프로젝트 설정 없음. 일반 캠페인·비제어 variant는 message(단일)와 localized_messages(다국어)를 상호배타 저장; 제어군만 둘 다 null. UJ node는 details.message/details.localizedMessages 동일 규칙. localized map default 필수; resolver=$locale→$last_observed_locale→exact/base/default. 집필·발송 지원=app/web push·popup; popup은 locale별 기존 템플릿 선택, 자동번역 X.
§
Stage api-service는 prod Redis 설정을 사용하므로 SSE smoke/load는 고유 synthetic channel만 사용한다.