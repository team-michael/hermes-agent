# kds-consumer null byte → PG error → timeout → ConsoleErrors false positive

## Symptom

CloudWatch alarm `kds-consumer lambda error` (namespace `ConsoleErrors`, metric `kds-consumer lambda console error`) fires intermittently, **or** `kds-consumer-queue-dlq has been created` / `kds-consumer-dlq` (`AWS/SQS ApproximateNumberOfMessagesVisible >= 1`) fires. The `AWS/Lambda` `Errors` metric may be zero (timeout path) or show isolated spikes (DLQ path).

## Root cause chain

A Kinesis record contains `\u0000` (null byte) inside `event_params`.

**Manifestation A — ConsoleErrors / timeout path:**
1. `kds-consumer` calls `upsertEventCounterData()` → `constructEventIntermediateCountData()` builds `segmentationEventParams` with the raw null byte.
2. The resulting `INSERT INTO event_intermediate_counts_<project_id> ...` binds that value to a PostgreSQL `text` or `jsonb` column.
3. PostgreSQL rejects it with error `22021` / `invalid byte sequence for encoding "UTF8": 0x00`.
4. `async-retry` retries the query up to 10 times. Each attempt fails instantly because the data is still invalid.
5. Total Lambda duration hits the 900-second timeout.
6. The final `REPORT RequestId: ... Status: timeout` log line matches the `ConsoleErrors` metric filter `%ERROR|Status: timeout%`.
7. The alarm fires even though the Lambda runtime itself did not throw an unhandled exception.

**Manifestation B — DLQ / unhandled exception path:**
1. Same PG `22021` error as in A, but instead of being wrapped in async-retry, the error surface may trigger a Lambda unhandled exception or the Kinesis EventSourceMapping exhausts `MaximumRetryAttempts` (default 2) after `approximateInvokeCount` failures.
2. The individual Kinesis record is routed to the DLQ (`kds-consumer-dlq`) with `condition: RetryAttemptsExhausted`.
3. The Lambda log contains the `ERROR invalid byte sequence for encoding "UTF8": 0x00` line but no long-duration timeout.
4. DLQ alarm fires (`ApproximateNumberOfMessagesVisible >= 1`).

## Distinguishing from a real Lambda bug

- ConsoleErrors path: `AWS/Lambda Errors` (Sum) should be zero or very low; `Duration` average is normal most of the time, with occasional 900,000 ms spikes. The log group contains the PG ERROR line (`invalid byte sequence for encoding "UTF8": 0x00`) shortly before the `Status: timeout` REPORT line.
- DLQ path: `AWS/Lambda Errors` may show isolated spikes around the alarm window. Inspect `/aws/lambda/kds-consumer` with `filter-log-events` using the alarm datapoint timestamp for `ERROR` and `"invalid byte sequence for encoding"`. The DLQ message body contains `requestContext.functionArn` pointing to `arn:aws:lambda:ap-northeast-2:702197142747:function:kds-consumer` and `KinesisBatchInfo` with the failing shard and sequence numbers.

## DLQ message inspection for this pattern

```bash
aws sqs receive-message \
  --queue-url https://sqs.ap-northeast-2.amazonaws.com/702197142747/kds-consumer-dlq \
  --max-number-of-messages 10 --visibility-timeout 5 --region ap-northeast-2
```

Expected body shape:
```json
{
  "requestContext": {
    "requestId": "...",
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
    "shardId": "shardId-...",
    "startSequenceNumber": "...",
    "batchSize": 1,
    "streamArn": "arn:aws:kinesis:ap-northeast-2:702197142747:stream:notifly-event-stream"
  }
}
```

After confirming the DLQ body points to `kds-consumer`, correlate to the Lambda log with `filter-log-events` around the DLQ `timestamp` field (converted to epoch ms). Look for `ERROR invalid byte sequence for encoding "UTF8": 0x00` followed by the table name `event_intermediate_counts_<project_id>`. Map the project suffix via DynamoDB `project` for scope attribution.

## Scope

The project ID is embedded in the table name: `event_intermediate_counts_<project_id>`. Map it via DynamoDB `project` table for product attribution.

Historical pattern: 30-day recurrence of ~10–30 alarms, often clustered on days when the offending project receives bad events. Example project: `b57754a9497a545ab9b0e4aadd6f53b6` (product `regather`).

## Customer impact

- Event intermediate count (EIC) records are lost for the affected events, so campaign/event-counter segmentation may be slightly stale for that project.
- No direct message delivery failure, but downstream analytics and trigger conditions that depend on exact counts can be off.

## Fix target

- **Data sanitization**: `services/lambda/kds-consumer/lib/event_counter_utils.ts`, function `constructEventIntermediateCountData()`. Strip `\u0000` from `segmentationEventParams` values (or JSON-stringify + replace) before returning the payload.
- **Fast-fail on known bad data**: In `upsertEventCounterData()`, catch PG error code `22021` explicitly and skip retry for that record, logging a compact WARN with project ID and event name instead of retrying to timeout.

## Verification after fix

1. Deploy the sanitization change.
2. Watch `ConsoleErrors` metric for `kds-consumer` drop to zero over the next hour.
3. Confirm `AWS/Lambda Errors` remains zero and `Duration` spikes (900s) disappear.
4. Optionally add a unit test in `test/lib/event_counter_utils.spec.ts` asserting that `constructEventIntermediateCountData` strips null bytes.
