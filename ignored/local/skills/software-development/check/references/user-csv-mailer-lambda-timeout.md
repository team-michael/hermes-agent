# user-csv-mailer Lambda Timeout on Large CSV Export

## Pattern

`user-csv-mailer` Lambda (`Timeout: 900s`, `MemorySize: 10240 MB`) processes SQS messages requesting CSV user-list exports. It runs an Athena query, then streams results through batch serialization and S3 multipart upload. Large date ranges (multi-month) can exceed the 900-second invocation limit.

## Triage

1. The metric filter `%ERROR|Status: timeout%` matches `REPORT ... Status: timeout` even when zero ERROR application logs exist.
2. `filter-log-events` with `ERROR` returns empty — this is expected for a pure timeout.
3. Use `get-log-events` on the most recent log stream to read the `START`/`REPORT` lines and the `Received event:` JSON payload. The `Received event:` body is the primary scope source because `user-csv-mailer` does not log `project_id` elsewhere.
4. In the SQS `body` JSON:
   - `projectId` — scope project
   - `projectName` — human-readable project name
   - `type` — e.g. `USER_JOURNEY_METRIC_USER_LIST`, `CAMPAIGN_METRIC_USER_LIST`
   - `userJourneyId` / `campaignId` — scope campaign or user journey
   - `startDate`, `endDate` — the queried range (format `YYYY-MM-DD-HH`)
5. Check `SQSmessage.attributes.ApproximateReceiveCount` in the payload:
   - `1` means this is the first receive; timeout will DLQ the message immediately when `maxReceiveCount=1`.
   - A value greater than `1` means SQS redelivery is occurring.
6. Inspect the DLQ to count how many messages actually landed there. The `user-csv-mailer-queue` uses `maxReceiveCount=1`, so every timeout goes straight to DLQ with zero main-queue retry.
7. If the same `md5OfBody` appears in multiple invocations within the same stream, it is likely a duplicate console/API request rather than an SQS retry.

## Classification

- **Root cause**: Athena query usually completes quickly (~10–20s). Bottleneck is the sequential batch retrieval, formatting, and S3 multipart upload for large result sets.
- **No ERROR logs**: Timeout is a capacity/limit issue, not a code exception.
- **Customer impact**: One CSV export job fails. Because `maxReceiveCount=1`, there is **no automatic main-queue retry**; the message moves to DLQ (`user-csv-mailer-queue-dlq`). No data loss, but the user must re-request the export unless an operator re-drives the DLQ.
- **Status**: `no_action` when isolated and the date range is clearly large (e.g., 3+ months). Use `needs_fix` only if timeouts become frequent for normal-range requests (under 1 month).

## Commands

```bash
# Read the active stream for the timeout invocation
aws logs get-log-events --region ap-northeast-2 \
  --log-group-name /aws/lambda/user-csv-mailer \
  --log-stream-name '2026/06/12/[$LATEST]<stream>' \
  --start-from-head --limit 200 \
  --output json | jq -r '.events[] | select(.message | contains("START") or contains("Received event") or contains("REPORT")) | .message'

# Extract project scope from DynamoDB
aws dynamodb get-item --region ap-northeast-2 \
  --table-name project --key '{"id":{"S":"<projectId>"}}' \
  --projection-expression 'id, product_id, #n' \
  --expression-attribute-names '{"#n":"name"}'

# Check DLQ depth (how many failed exports are waiting)
aws sqs get-queue-attributes --region ap-northeast-2 \
  --queue-url https://sqs.ap-northeast-2.amazonaws.com/702197142747/user-csv-mailer-queue-dlq \
  --attribute-names ApproximateNumberOfMessages,ApproximateNumberOfMessagesNotVisible
```

## Real payload example (2026-06-12)

```json
{
  "type": "USER_JOURNEY_METRIC_USER_LIST",
  "recipient": "hailey@munice.com",
  "projectId": "031b18009978590188e49e6777447fc2",
  "projectName": "MUNICE",
  "userJourneyId": "3RfBke",
  "userJourneyName": "(iOS/Android) 취침 시간 알림",
  "userJourneyNodeId": "55tZEX",
  "userJourneyNodeName": "메시지 발송",
  "metricType": "standard",
  "eventName": "send_success",
  "eventKoreanName": "발송 성공",
  "startDate": "2026-03-06-15",
  "endDate": "2026-06-12-14",
  "selectedAttributes": [],
  "isProductAdmin": false
}
```

- Date range: ~3 months (`2026-03-06` → `2026-06-12`)
- Result: two identical payloads sent ~25 minutes apart, both timed out at 900s.

## Remediation options

- Increase Lambda `Timeout` (currently 900s) if large-range exports are a supported use case.
- Add a max date-range guard in the web-console or API before enqueueing the export.
- Parallelize the result streaming or switch to Athena UNLOAD + direct S3 copy for very large extracts.
- Consider raising `maxReceiveCount` on the main queue to allow at least one retry for transient errors, keeping in mind that timeout is deterministic for a given payload size.
