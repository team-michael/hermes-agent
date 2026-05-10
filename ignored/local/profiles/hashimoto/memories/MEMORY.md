Notifly AWS default region is ap-northeast-2; primary account ID observed in alerts is 702197142747.
§
CloudWatch alarm responses use `[[hermes:processing_status=no_action]]` for false positives or recovered spikes, `[[hermes:processing_status=needs_fix]]` for non-urgent engineering work, and `[[hermes:processing_status=urgent]]` only for active outages requiring immediate @engineers escalation.
§
Hashimoto Slack alert replies use a compact Korean five-field shape: 원인, 범위, 빈도, 고객 영향도, 즉시 조치 필요 여부. The final hidden directive remains `[[hermes:processing_status=...]]` for Slack reactions.
§
Hashimoto Slack completion reactions require `message_subscriptions` with the target channel, source bot, and `reactions=true`; `channel_skill_bindings` only controls skill auto-loading and does not enroll messages in the reaction lifecycle.
§
Notifly recurring `ScheduledBatchDelivery-P2-FCMLatencyP99` alerts usually indicate FCM external p99 latency, not message loss; when `outcome=success`, Lambda Errors are zero, and SQS/DLQ are clear, the customer impact is delayed push delivery only.
§
Notifly `api-service` 4xx and console-error alerts are frequently noise from `/authenticate` 400 bursts, PostgreSQL 23505 set-user-properties races, or payload strings containing `ERROR`; distinguish client rejection/log-filter noise from real 5xx/ECS task failure.
§
Notifly `anomaly-delivery-monitoring lambda error` means routine inspection logs at ERROR (NHN pending backlog or scheduled-but-not-delivered gap), not a Lambda crash. Verify `AWS/Lambda Errors==0` and check `references/anomaly-delivery-monitoring-lambda-consoleerrors.md` for triage.
§
Notifly Lambda `ConsoleErrors` alarms can false-positive on broad `%ERROR|Status: timeout%` filters, including receiptHandle/base64 substrings, deprecation warnings, and expected external-provider rejections; runtime Lambda Errors=0 changes the interpretation materially.
§
For DLQ alerts, useful triage includes directly inspecting DLQ message bodies/attributes and summarizing project, campaign/user journey, metadata, queue lifecycle, and retry context; post-redrive/purge verification should show no visible/not-visible messages.