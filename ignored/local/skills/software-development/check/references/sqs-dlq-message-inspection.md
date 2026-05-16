# SQS DLQ Message Inspection

Read-only recipe for inspecting DLQ message bodies to extract scope and root cause when Lambda logs are insufficient.

## When to use

- DLQ alarm fired (`ApproximateNumberOfMessagesVisible >= 1`).
- Lambda `Errors=0`, `Throttles=0`, `Duration` normal — function code is unlikely to be the cause.
- Lambda log group contains only `START/END/REPORT` lines, no ERROR logs.
- User asks for DLQ content (`dlq 내용 확인`) or root cause of why messages landed in DLQ.

## Inspection flow

1. **Get queue URL and current attributes**
   ```bash
   aws sqs get-queue-url --queue-name <queue-name>-dlq --region ap-northeast-2
   aws sqs get-queue-attributes --queue-url <dlq-url> --attribute-names All --region ap-northeast-2
   ```
   Record `ApproximateNumberOfMessages`, `ApproximateNumberOfMessagesNotVisible`, `VisibilityTimeout`.

2. **Peek messages (read-only, do not delete)**
   ```bash
   aws sqs receive-message \
     --queue-url <dlq-url> \
     --max-number-of-messages 10 \
     --visibility-timeout 5 \
     --wait-time-seconds 10 \
     --attribute-names All \
     --region ap-northeast-2
   ```
   - Use short `visibility-timeout` (5 s) so messages become visible again for any automated redrive.
   - If first call returns 0 messages but `ApproximateNumberOfMessages > 0`, another process may have consumed them; retry once after a few seconds.

3. **Parse body for scope IDs**
   DLQ messages for Notifly pipelines are typically JSON containing Kinesis/SQS dispatch commands. Extract:
   - `project_id` from `body.records[].data.project_id`
   - `campaign_id` from `body.records[].data.campaign_id`
   - `resource_type` from `body.records[].data.resource_type`
   - `name` (event name) from `body.records[].data.name`
   - `streamName` from `body.streamName`

4. **Map project through DynamoDB**
   ```bash
   aws dynamodb get-item \
     --table-name project \
     --key '{"id":{"S":"<project_id>"}}' \
     --projection-expression 'id, product_id, #n' \
     --expression-attribute-names '{"#n":"name"}' \
     --region ap-northeast-2
   ```
   Report `project_id + product_id + name` in the final scope field.

5. **Kinesis-specific DLQ body shape (e.g., `kds-consumer-dlq`)**
   When the source trigger is a Kinesis stream EventSourceMapping, the DLQ payload is not an SQS record but a Kinesis batch failure report:
   ```json
   {
     "requestContext": {
       "requestId": "<UUID>",
       "functionArn": "arn:aws:lambda:ap-northeast-2:702197142747:function:kds-consumer",
       "condition": "RetryAttemptsExhausted",
       "approximateInvokeCount": 2
     },
     "responseContext": {
       "statusCode": 200,
       "executedVersion": "$LATEST",
       "functionError": "Unhandled"
     },
     "KinesisBatchInfo": {
       "shardId": "shardId-000000002903",
       "startSequenceNumber": "...",
       "batchSize": 1,
       "streamArn": "arn:aws:kinesis:ap-northeast-2:702197142747:stream:notifly-event-stream"
     }
   }
   ```
   - `condition: RetryAttemptsExhausted` and `approximateInvokeCount` are the key fields showing retry exhaustion.
   - `timestamp` in the top-level body is the failure time; convert to epoch ms to search Lambda logs.
   - Do not search inside `KinesisBatchInfo` for project IDs; scope comes from the Lambda log itself.

6. **Extract event type from payload for deeper context**
   Notifly DLQ payloads often contain Kinesis-style dispatch commands. Parse the JSON body for:
   - `streamName` — e.g. `notifly-message-events-stream`, `notifly-triggering-events-stream`
   - `records[].data.name` — event name, e.g. `send_success`, `send_fail`
   - `records[].data.resource_type` — e.g. `campaign`, `user_journey`
   - `records[].data.triggering_event_id` — for triggering events
   - `records[].data.event_params` — may contain channel, token, message_id (sanitize sensitive fields)

   Example payloads seen in practice:
   - `streamName: notifly-message-events-stream` with `campaign_id`, `resource_type: campaign`, `name: send_success` → push notification delivery success event.
   - `streamName: notifly-triggering-events-stream` with `campaign_id`, `experiment_id`, `variant_id`, `triggering_event_id` → event-triggered campaign activation event.

7. **Check redrive policy on source queue**
   ```bash
   aws sqs get-queue-attributes \
     --queue-url <main-queue-url> \
     --attribute-names RedrivePolicy \
     --region ap-northeast-2
   ```
   If `maxReceiveCount` is 1, flag it as a structural root cause in the final answer.

## Scheduled-batch-delivery push-notification payload shape

When the source is `scheduled-batch-push-notification-queue` (or its DLQ), the message body is **not** a Kinesis dispatch command. It is the raw FCM batch payload produced by `services/lambda/scheduled-batch-delivery` (`sendPushV1ApiAndLogResult`):

```json
{
  "project_id": "<project_id>",
  "campaign_id": "<campaign_id>",
  "recipients": [
    {
      "id": "<recipient_id>",
      "token": "<fcm_token>",
      "platform": "android|ios",
      "device_id": "<device_id>"
    }
  ],
  "fcm_server_key": "<server_key>",
  "fcm_service_account": { ... },
  "firebase_project_id": "<project_slug>",
  "title": "...",
  "body": "...",
  "data": { ... },
  "image_url": "...",
  "badge": 1,
  "channel_id": "..."
}
```

Key extraction fields:
- `project_id` and `campaign_id` → map through DynamoDB `project` for scope.
- `fcm_server_key` and `fcm_service_account` are sensitive — report their **presence** only, never their values.
- `firebase_project_id` hints at the product slug (e.g., `cosmo-6edb5` → cosmo).
- `recipients[].token` and `recipients[].device_id` must be sanitized.

Because this is a raw batch payload (not a dispatch command), `SentTimestamp` is the **original scheduled enqueue time** to the main queue, often hours or even days before the Lambda actually processes the message. Do not confuse it with the DLQ arrival time or the Lambda error time.

## Pitfalls

- Do not call `delete-message` during investigation. Use `receive_message` with short visibility only.
- `ApproximateNumberOfMessages` is eventually consistent. A value of 2 with `receive_message` returning 0 can mean another consumer is currently processing the messages.
- `SentTimestamp` in message attributes is the original send time to the **source** queue, not the DLQ arrival time. DLQ arrival time is derived from `ApproximateAgeOfOldestMessage`.
- **For scheduled batch delivery**, `SentTimestamp` can be hours or days before actual Lambda processing because the message was scheduled in advance. The Lambda error that pushed the message to DLQ may have occurred at a completely different time.
- If DLQ messages contain FCM tokens, device IDs, or email addresses, sanitize them in the final answer; report only the presence of sensitive fields, not their values.
- **Campaign mismatch between DLQ payload and Lambda error logs**: In shared-pipeline or batch queues, the DLQ message body shows campaign A, but the actual Lambda error that caused DLQ routing may have occurred while processing campaign B in a different batch. If Lambda `Errors > 0` but no ERROR logs match campaign A, search Lambda logs for the exact error time from the `StateReasonData` rather than the DLQ message time.
- **`AWS/Lambda Errors > 0` with no ERROR application logs**: When the Lambda `Errors` metric is non-zero but `filter-log-events` with `ERROR` returns nothing, the cause is typically one of:
  1. **Invocation timeout / OOM** — produces `REPORT ... Status: timeout` without any application ERROR log.
  2. **Unhandled exception before logger initialization** — crashes the invocation before `console.error` is reached.
  3. **Error occurred in a different stream / shard** — Kinesis or SQS batch processing spreads work across multiple log streams; the ERROR may be in a different stream than the one inspected.
  In this state, anchor the manual `filter-log-events` window precisely to the CloudWatch alarm `StateReasonData.startDate` (converted to epoch ms), not to Slack message time. Inspect `REPORT` lines for `Status: timeout` and `Duration` ≈ `Timeout` as the primary fallback signal.