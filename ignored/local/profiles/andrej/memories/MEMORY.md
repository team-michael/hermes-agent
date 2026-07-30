Env: ws `~/.hermes/workspace`; gh in profile `.env`; JDK `~/.hermes/jdks/jdk-17`; Android SDK `~/.hermes/android-sdk`.
§
Notifly: project_id→DDB product_id/name; per-project PG table_${pid}; DDL via onboarding/preflight. Push RCA: FCM 404/UNREGISTERED can null device_token; test sends require native device_token IS NOT NULL. project_statistics long-form metrics.
§
Notifly 2026-06 KST customer MAU/data-point benchmark: payments 등록 non-dev prod 205개 중 active 138(무활동 67 제외). MAU=distinct notifly_user_id; DP=current data_points contract, KST daily event-id dedupe 후 월합. Bins `n; DP min~max; DP/MAU min~max`: ≤3만 `80;1~2,402,872;1.0~311.9`, 3~5만 `5;352,830~4,069,704;7.3~88.9`, 5~10만 `5;1,115,720~9,841,814;17.8~163.5`, 10~20만 `19;393,645~12,944,022;2.7~81.1`, 20~30만 `7;1,400,733~722,567,463;6.7~3,347.3`, 30~50만 `7;2,074,970~387,119,689;5.6~945.0`, 50~100만 `10;6,087,071~122,427,543;9.1~198.8`, ≥100만 `5;14,250,927~115,805,471;2.5~112.0`.
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