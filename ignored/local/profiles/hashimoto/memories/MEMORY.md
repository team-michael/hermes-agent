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
check skill SKILL.md is ~100,472 chars and exceeds the 100,000-char skill_manage patch limit. In-place SKILL.md patches fail. New triage guidance must be added as reference files under the skill until the SKILL.md is split.