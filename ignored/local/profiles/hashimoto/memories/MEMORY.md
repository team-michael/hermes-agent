Notifly AWS default region is ap-northeast-2; primary account ID observed in alerts is 702197142747.
§
CloudWatch alarm responses use `[[hermes:processing_status=no_action]]` for false positives or recovered spikes, `[[hermes:processing_status=needs_fix]]` for non-urgent engineering work, and `[[hermes:processing_status=urgent]]` only for active outages requiring immediate @engineers escalation.
§
Hashimoto Slack alert replies use a compact Korean five-field shape: 원인, 범위, 빈도, 고객 영향도, 즉시 조치 필요 여부. The final hidden directive remains `[[hermes:processing_status=...]]` for Slack reactions.
§
Hashimoto Slack completion reactions require `message_subscriptions` with the target channel, source bot, and `reactions=true`; `channel_skill_bindings` only controls skill auto-loading and does not enroll messages in the reaction lifecycle.
§
Notifly `anomaly-delivery-monitoring lambda error` means routine inspection logs at ERROR (NHN pending backlog or scheduled-but-not-delivered gap), not a Lambda crash. Verify `AWS/Lambda Errors==0` and check `references/anomaly-delivery-monitoring-lambda-consoleerrors.md` for triage.
§
Notifly Lambda `ConsoleErrors` alarms can false-positive on broad `%ERROR|Status: timeout%` filters, including receiptHandle/base64 substrings, deprecation warnings, and expected external-provider rejections; runtime Lambda Errors=0 changes the interpretation materially.
§
NHN Cloud template limit (`The maximum number of registered templates.`) in web-console campaign/user_journey saves → not AWS SES (6,269/10,000). Resolution: GitHub workflow `cleanup-nhncloud-unused-templates.yml` for manual NHN Cloud unused template cleanup.
§
Lambda `invalid input syntax for type json` scope workflow: parse `delivery_result_<project_id>` table suffix → extract `campaign_id` from VALUES tuple → map `project_id` via DynamoDB `project` → read PostgreSQL `where`/`detail` for broken surrogate. Skill `notifly-lambda-json-surrogate-error` created.