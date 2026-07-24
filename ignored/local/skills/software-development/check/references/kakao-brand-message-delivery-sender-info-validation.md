# Kakao Brand Message Delivery: Missing sender_info validation error

## Summary

`kakao-brand-message-delivery` Lambda logs `Missing required data: invalid kakao_bizmessage sender info from event data` at `ERROR` level in `lib/utils.ts:51`. This is a **handled validation rejection** — the caller (`index.ts:70`) returns `false` from `isValidEventData()`, the handler skips the record with `continue`, and the Lambda completes normally with `Errors=0`.

## Why the alarm fires

The coarse `%ERROR|Status: timeout%` metric filter on `/aws/lambda/kakao-brand-message-delivery` matches the literal substring `ERROR` in `console.error('Missing required data: ...')`. Because the log line is emitted at `ERROR` level, it increments the `ConsoleErrors` metric even though no invocation failure occurred.

## Trigger string

```
Missing required data: invalid kakao_bizmessage sender info from event data
```

## Code path

- `services/lambda/kakao-brand-message-delivery/lib/utils.ts:51`
- Called from `services/lambda/kakao-brand-message-delivery/index.ts:70`

## Scope attribution

The ERROR log line itself does **not** carry `projectId` or `campaignId`. The calling handler in `index.ts` emits an EMF metric with `project_id` and `campaign_id` on the skipped path, but that metric line uses `console.log` (INFO). Therefore the alarm-window log query for `ERROR` may show only the generic `Missing required data` line. To recover scope:

1. Look at adjacent `INFO` lines in the same log stream for the `BatchCompletion` EMF metric or `Received event` SQS payload (both contain `project_id` and `campaign_id`).
2. The helper's `scope_attribution.scope_kind` may default to `user_journey` because the stream carries mixed `resource_type` values. Always verify the `resource_type` on the specific `BatchCompletion` or SQS payload line tied to the `ERROR` timestamp.

## INFO payload ERROR-embedding pitfall

This Lambda logs the full SQS `Received event` JSON body at `INFO` level. When the payload contains a field whose value includes the literal string `ERROR` (e.g. a base64-escaped byte sequence, a provider response code, or a template placeholder), the coarse metric filter may match the INFO line even though the actual ERROR log (`Missing required data`) is the root cause. When `current_top_signatures` contains only `INFO Received event` patterns but the metric filter demonstrably breached, run a bounded `filter_log_events` with `filterPattern='ERROR'` on the exact alarm window to isolate the true trigger line.

## Classification

- `no_action` when isolated and `AWS/Lambda Errors == 0`.
- The rejection is handled behavior: the batch is skipped because `eventData.sender_info` is missing or invalid (e.g. `channel_id` absent).
- Use `needs_fix` only when recurrence becomes noisy (e.g. daily sustained).

## Action target (when noise threshold crossed)

- In `services/lambda/kakao-brand-message-delivery/lib/utils.ts`, downgrade the validation-rejection `console.error` lines to `console.warn`.
- Keep the `return false` semantics unchanged (`index.ts:70` must still skip the record).
- Alternative: remove `console.error` entirely and rely on the EMF `BatchCompletion outcome=error` metric for observability.

## Bounded log check

```bash
python3 -c "
import boto3, datetime
session = boto3.Session(region_name='ap-northeast-2')
logs = session.client('logs')
start = int(datetime.datetime(YYYY, MM, DD, HH, MM, tzinfo=datetime.timezone.utc).timestamp() * 1000)
end   = int(datetime.datetime(YYYY, MM, DD, HH, MM, tzinfo=datetime.timezone.utc).timestamp() * 1000)
resp = logs.filter_log_events(
    logGroupName='/aws/lambda/kakao-brand-message-delivery',
    startTime=start, endTime=end,
    filterPattern='Missing required data',
    limit=20
)
for e in resp.get('events', []):
    print(e['message'].strip()[:400])
"
```
