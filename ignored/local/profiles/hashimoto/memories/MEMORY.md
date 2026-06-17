CloudWatch alarm responses use `[[hermes:processing_status=no_action]]` for false positives or recovered spikes, `[[hermes:processing_status=needs_fix]]` for non-urgent engineering work, and `[[hermes:processing_status=urgent]]` only for active outages requiring immediate @engineers escalation.
§
Hashimoto Slack alert replies use a compact Korean five-field shape: 원인, 범위, 빈도, 고객 영향도, 즉시 조치 필요 여부. The final hidden directive remains `[[hermes:processing_status=...]]` for Slack reactions.
§
Projects with names starting with `notifly-` (e.g., notifly-gamelog, notifly-test, notifly-internal, etc.) and project slug `michael` or URLs under `console-stage.notifly.tech` are Notifly internal testing/demo scopes. Alerts or errors tied to these indicate synthetic/test data or internal tooling gaps, not customer-facing production issues. When scoping alerts, explicitly flag them as internal to avoid misrepresenting customer impact.
§
`web-console/sentry` is an intentional Sentry proxy (`ops-email-receiver` Lambda → SES → CloudWatch ERROR logs). Triage the actual Sentry payload (title, message, transaction, request.url). Map `productId` via DynamoDB `project` GSI. The Sentry `project.id` is not a Notifly project_id.
§
Cloudflare Workers AI: `@cf/moonshotai/kimi-k2.7-code` ignores `reasoning_effort` except `"none"`. Hermes `_is_kimi` checks `moonshot.ai` / `api.kimi.com` hostnames only.
§
Lambda timeouts: `user-csv-mailer` S3 multipart bottleneck (needs_fix); `api-service` 4xx KST 02:10 daily (no_action). integration-service Mixpanel "Invalid credentials" = client Authorization header mismatch with DynamoDB `cognitoApiAuth`. API auth reverse-trace workflow: /authenticate failures with unknown projectId use 4-step triage (client IP→request body char→Cognito map→project correlation). See `notifly-api-authentication-failure-triage` skill (devops) and integration-service example.
§
Check helper scope attribution bug (fixed 2026-06-16): `collect_surrounding_log_contexts()` was analyzing full log stream for project_ids, mixing invocations. Now triggers only — prevents cross-stream false scope. Test: kds-consumer 12 ERRORs all from storepick, helper wrongly reported moyo/regather.