CloudWatch alarm responses use `[[hermes:processing_status=no_action]]` for false positives or recovered spikes, `[[hermes:processing_status=needs_fix]]` for non-urgent engineering work, and `[[hermes:processing_status=urgent]]` only for active outages requiring immediate @engineers escalation.
§
Hashimoto Slack alert replies use a compact Korean five-field shape: 원인, 범위, 빈도, 고객 영향도, 즉시 조치 필요 여부. The final hidden directive remains `[[hermes:processing_status=...]]` for Slack reactions.
§
Hashimoto Slack completion reactions require `message_subscriptions` with the target channel, source bot, and `reactions=true`; `channel_skill_bindings` only controls skill auto-loading and does not enroll messages in the reaction lifecycle.
§
HERMES_HOME points to `~/.hermes/profiles/hashimoto/`, not base `~/.hermes/`. Construct skill script paths as `${HERMES_HOME}/skills/...` without adding `/profiles/hashimoto/`.
§
`check` skill: `references/cafe24-token-refresher-external-timeout.md` added. Covers Cafe24 API timeout → Lambda caught error → `%ERROR%` metric filter false positive, scope untraceable because `cafe24_integration` table lacks `project_id`.
§
Projects with names starting with `notifly-` (e.g., notifly-gamelog, notifly-test, notifly-internal, etc.) are Notifly internal testing/demo projects. Alerts or errors tied to these projects indicate synthetic/test data or internal tooling gaps, not customer-facing production issues. When scoping alerts, explicitly flag `notifly-` prefixed projects as internal to avoid misrepresenting customer impact.
§
check skill SKILL.md is ~100,472 chars and exceeds the 100,000-char skill_manage patch limit. In-place SKILL.md patches fail. New triage guidance must be added as reference files under the skill until the SKILL.md is split.
§
The most recent live-verification entry for `api-service` 4xx authenticate noise is now 2026-06-03, confirming the daily ~02:11 KST `python-requests/2.32.3` burst remains stable with ~1,700 handled `warn` rejections per alarm window. Future investigators can rely on this as current evidence.