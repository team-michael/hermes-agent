Env: ws `~/.hermes/workspace`; gh in profile `.env`; JDK `~/.hermes/jdks/jdk-17`; Android SDK `~/.hermes/android-sdk`.
§
Notifly: project_id→DDB product_id/name; per-project PG table_${pid}; DDL via onboarding/preflight. Push RCA: FCM 404/UNREGISTERED can null device_token; test sends require native device_token IS NOT NULL. project_statistics long-form metrics.
§
Notifly: docs=notifly-event/docs; web=notifly-web; KB=notifly-product-knowledge; KR ‘노티플라이’. 딥테크팁스 RS-2026-25607785=2026-07-01~2029-06-30/TIPA; 노트=IRIS 주간.
§
Slack links: use SLACK_BOT_TOKEN replies/history; url_private images→vision.
§
Git: `Andrej Karpathy <team@greyboxhq.com>`; Gunwoo Park→`gunoooo`.
§
Notifly console: `NOTIFLY_AUTH`; Michael slug `michael`; delivery list uses derived/Redis status; monitor completion Redis-only, no PG recovery unless reopened.
§
Notifly MCP: api/web Cognito 재사용. Non-app-push draft는 Kakao/SMS/email sender 정보 오류 위험.
§
Notifly Kakao: Alimtalk no ad flags. templateId row→row.template.sender_platform; missing row→legacy provider code. NHN resend≠BZM params.
§
Kyungseo Jeong is male.
§
Notifly 다국어: 프로젝트 설정 없음. 캠페인·비제어 variant는 message/localized_messages 상호배타, 제어군만 둘 다 null; UJ node도 동일. map default 필수, locale 선택 후 exact→base→default. Push는 1개만 SQS 전달. 팝업·UJ 팝업은 /user-state에서 user language로 1개 resolve해 기존 message로 전달하고 SDK가 segment를 로컬 평가하므로 SDK 변경 불필요. 팝업은 locale별 기존 템플릿 선택, 자동번역 X.
§
Stage api-service는 prod Redis 설정을 사용하므로 SSE smoke/load는 고유 synthetic channel만 사용한다.
§
복구 제안은 고객에게 별도 PG 화면·DevTools 같은 비정상 UX를 요구하지 않고, 앱 접근과 PG 자격증명 복구를 분리하며 live 검증 전 성공을 단정하지 않길 원함.
§
GitHub PR 정책: clix-so-bot은 Assignee로 절대 지정하지 않는다. 세션에서 작업 요청자를 식별하고 검증된 GitHub 계정을 Assignee로 지정한다. 매핑이 불명확하면 추정하지 말고 질문하며, 식별 전에는 Assignee를 비워둔다. PR 생성 후 GitHub에서 Assignee를 재조회해 검증한다.