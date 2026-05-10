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

5. **Extract event type from payload for deeper context**
   Notifly DLQ payloads often contain Kinesis-style dispatch commands. Parse the JSON body for:
   - `streamName` — e.g. `notifly-message-events-stream`, `notifly-triggering-events-stream`
   - `records[].data.name` — event name, e.g. `send_success`, `send_fail`
   - `records[].data.resource_type` — e.g. `campaign`, `user_journey`
   - `records[].data.triggering_event_id` — for triggering events
   - `records[].data.event_params` — may contain channel, token, message_id (sanitize sensitive fields)

   Example payloads seen in practice:
   - `streamName: notifly-message-events-stream` with `campaign_id`, `resource_type: campaign`, `name: send_success` → push notification delivery success event.
   - `streamName: notifly-triggering-events-stream` with `campaign_id`, `experiment_id`, `variant_id`, `triggering_event_id` → event-triggered campaign activation event.

6. **Check redrive policy on source queue**
   ```bash
   aws sqs get-queue-attributes \
     --queue-url <main-queue-url> \
     --attribute-names RedrivePolicy \
     --region ap-northeast-2
   ```
   If `maxReceiveCount` is 1, flag it as a structural root cause in the final answer.

## Pitfalls

- Do not call `delete-message` during investigation. Use `receive_message` with short visibility only.
- `ApproximateNumberOfMessages` is eventually consistent. A value of 2 with `receive_message` returning 0 can mean another consumer is currently processing the messages.
- `SentTimestamp` in message attributes is the original send time to the **source** queue, not the DLQ arrival time. DLQ arrival time is derived from `ApproximateAgeOfOldestMessage`.
- If DLQ messages contain FCM tokens, device IDs, or email addresses, sanitize them in the final answer; report only the presence of sensitive fields, not their values.
