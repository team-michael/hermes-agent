# scheduled-batch-text-message-delivery lambda error — `failover_reason: "API_ERROR"` false positive

## Pattern

Alarm: `scheduled-batch-text-message-delivery lambda error` (namespace `ConsoleErrors`,
metric filter `%ERROR|Status: timeout%` on `/aws/lambda/scheduled-batch-text-message-delivery`).

The Lambda logs the full inbound SQS payload at `INFO` level:
`INFO Received event from SQS: {...}`.

When a message is a Kakao Alimtalk → SMS failover (`event_params.is_failover_text_message: true`,
`event_params.failover_reason: "API_ERROR"`), the literal substring `ERROR` inside the JSON
value trips the coarse filter even though:
- the log line is `INFO`, not `ERROR`
- the invocation completes normally: `outcome: success`, `NHNCloudApiSend` success,
  `DbInsert` success, `success_count:1, failure_count:0`
- `AWS/Lambda Errors=0` and `Throttles=0` for the whole alarm window
- `Duration` is well under `Timeout` (typically <200ms for a single-recipient batch)

## Verification steps

1. From `describe-alarms` / helper `current_alarm_window`, get the exact breaching datapoint
   window (e.g., `startDate`/`evaluatedDatapoints[].timestamp`).
2. `filter_log_events` with `filterPattern="ERROR"` bounded to that window on
   `/aws/lambda/scheduled-batch-text-message-delivery`. If the only match is an `INFO Received
   event from SQS` line containing `"failover_reason": "API_ERROR"`, this is the false-positive
   pattern.
3. Confirm end-to-end: read the full stream for that `RequestId` (`START` → `END`/`REPORT`).
   No genuine `ERROR`-level line, no `Status: timeout`, `Duration` normal.
4. Cross-check `AWS/Lambda` `Errors`/`Throttles` metrics for the window — both should be 0.

## Scope

`project_id`/`campaign_id` are present directly in the SQS payload
(`event.project_id`, `event.campaign_id`). Map `project_id` via DynamoDB `project`.
Note: campaigns with `manual_kakao_alimtalk_public_api_*` IDs and `project_id` resolving to
Notifly's own internal `notifly` project/product are Notifly-internal test/demo sends, not
customer campaigns — flag explicitly when this is the case.

## Classification

`no_action` when:
- the sole ERROR-matching line in the window is this `failover_reason: "API_ERROR"` INFO log
- Lambda `Errors=0`, `Throttles=0`
- the invocation's own metrics show `outcome: success`

Escalate to `needs_fix` only if this pattern recurs at materially higher volume than the
existing ~1/week baseline, or if `outcome: error`/non-zero `failure_count` appears in the same
payload (that would indicate a genuine downstream delivery failure, not just filter noise).

## Long-term fix direction

The metric filter pattern `%ERROR|Status: timeout%` on this log group should either:
- be scoped to `?level = "ERROR"` (structured field) instead of a raw substring match, or
- have the SQS payload dump moved to a field that isn't scanned by the coarse filter (e.g.
  truncate/redact `failover_reason` before logging, or log payload at `DEBUG`).

Terraform location: `infra/terraform/prod/ap-northeast-2/lambda/functions.tf`, metric filter
`scheduled-batch-text-message-delivery lambda error` (~line 7846).
