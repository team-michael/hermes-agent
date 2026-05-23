CloudWatch alarm responses use `[[hermes:processing_status=no_action]]` for false positives or recovered spikes, `[[hermes:processing_status=needs_fix]]` for non-urgent engineering work, and `[[hermes:processing_status=urgent]]` only for active outages requiring immediate @engineers escalation.
§
Hashimoto Slack alert replies use a compact Korean five-field shape: 원인, 범위, 빈도, 고객 영향도, 즉시 조치 필요 여부. The final hidden directive remains `[[hermes:processing_status=...]]` for Slack reactions.
§
Hashimoto Slack completion reactions require `message_subscriptions` with the target channel, source bot, and `reactions=true`; `channel_skill_bindings` only controls skill auto-loading and does not enroll messages in the reaction lifecycle.
§
HERMES_HOME points to `~/.hermes/profiles/hashimoto/`, not base `~/.hermes/`. Construct skill script paths as `${HERMES_HOME}/skills/...` without adding `/profiles/hashimoto/`.
§
NHN Cloud template limit (`The maximum number of registered templates.`) in web-console campaign/user_journey saves → not AWS SES (6,269/10,000). Resolution: GitHub workflow `cleanup-nhncloud-unused-templates.yml` for manual NHN Cloud unused template cleanup.
§
Projects with names starting with `notifly-` (e.g., notifly-gamelog, notifly-test, notifly-internal, etc.) are Notifly internal testing/demo projects. Alerts or errors tied to these projects indicate synthetic/test data or internal tooling gaps, not customer-facing production issues. When scoping alerts, explicitly flag `notifly-` prefixed projects as internal to avoid misrepresenting customer impact.
§
경고 `/aws/ecs/notifly-services-prod/web-console/sentry alert`은 `ops-email-receiver` Lambda의 CloudWatch Log Group이다. `%ERROR%` 필터가 Sentry 페이로드 문자열과 매칭되어 ConsoleErrors 알람이 발생하며 Lambda 자체는 항상 정상(Errors=0)이다. 

판단 순서: 1) Lambda Errors=0 확인, 2) URL에 `127.0.0.1`/`console-stage`/`michael` 포함 여부 확인 → 내부 테스트면 무시, 3) `SyntaxError` + `/user-journey/.../stats` 패턴이면 API가 HTML(5xx) 응답을 반환한 것으로 `api-service` 로그에서 해당 endpoint 5xx 여부 확인, 4) 나머지는 Sentry가 이미 추적 중이므로 별도 조치 불필요. 

실제 오류는 web-console(Next.js)의 Sentry 이슈이며, 이 알람 자체는 metric-filter 노이즈이다.