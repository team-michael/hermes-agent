# Lambda Kinesis PutRecords InternalFailure Partial Failure

## Pattern

`kinesis-record-dispatcher` Lambda logs `ERROR Failed to put <n> records out of <N>, failed records: [{"ErrorCode":"InternalFailure",...}]` and the `ConsoleErrors` metric filter (`%ERROR|Status: timeout%`) triggers an alarm.

- Lambda `AWS/Lambda Errors = 0`, `Throttles = 0`, `Duration` normal (~50–80 ms baseline, ~1,100–1,200 ms when partial failure occurs)
- Kinesis `PutRecords.FailedRecords` metric confirms partial failures on the target stream (commonly `notifly-message-events-stream`)

## Root cause

AWS Kinesis `PutRecords` returns a `200 OK` HTTP response even when some records in the batch fail. Individual record failures carry `ErrorCode` (e.g. `InternalFailure`, `ProvisionedThroughputExceededException`). The `kinesis-record-dispatcher` Lambda code logs these at `ERROR` level but then returns normally:

```typescript
// services/lambda/kinesis-record-dispatcher/lib/kinesis.ts:78-84
if (aggregated.FailedRecordCount) {
    const failedRecords = aggregated.Records?.filter((record) => record.ErrorCode);
    console.error(
        `Failed to put ${failedRecords?.length} records out of ${records.length}, failed records: `,
        JSON.stringify(failedRecords)
    );
}
return aggregated;
```

The same anti-pattern exists in the shared package:

```typescript
// packages/kinesis/src/lib/kinesis.ts:160-166
if (aggregated.FailedRecordCount) {
    const failedRecords = aggregated.Records?.filter((record) => record.ErrorCode);
    console.error(
        `Failed to put ${failedRecords?.length} records out of ${records.length}, failed records: `,
        JSON.stringify(failedRecords)
    );
}
```

Because the function returns normally, the SQS message is deleted and the failed records are **silently dropped** with no retry.

## Triage checklist

1. Confirm Lambda `Errors = 0` and `Throttles = 0`
2. Check Kinesis `PutRecords.FailedRecords` metric per stream around the alarm window
3. Read the Lambda log line to confirm `ErrorCode: InternalFailure` (not a timeout or unhandled exception)
4. Verify the target stream from the Lambda's `streamName` via `executeCommands` context or queue message shape

## Classification

- **Current behavior**: `no_action` if isolated and low-volume (AWS Kinesis transient internal failure)
- **Structural concern**: The silent drop of partial failures is a reliability issue that should be tracked as `needs_fix`
  - Fix: retry individual failed records, or throw so the SQS message retries the whole batch
  - Files: `services/lambda/kinesis-record-dispatcher/lib/kinesis.ts`, `packages/kinesis/src/lib/kinesis.ts`

## Code evolution note

- PR #2121 (2025-02-28): dispatcher SQS payload structure refactoring, `bypassSqs` option added — **partial failure retry logic not introduced**
- PR #2410 (2025-06-17): Kinesis SDK `retryMode: 'adaptive'` → `'standard'` change — **SDK-level transport retry only**, does **not** handle `PutRecords` response-level per-record `ErrorCode`

## Scope

The `kinesis-record-dispatcher-queue` is a shared pipeline queue; messages contain no per-project `project_id` in the log line itself. Declare scope as infra-wide / common pipeline unless DLQ message inspection reveals a concentrated project. The `notifly-message-events-stream` stream is a common target but its records carry per-project fields inside the JSON payload that are not surfaced in the ERROR log.

## Historical baseline

| Date (UTC) | Alarms | Failed Records | Notes |
|---|---|---|---|
| 2026-05-29 03:43 | 1 | ~1-4 | Isolated single failure |
| 2026-06-10 06:55–07:07 | 5 (4 within 10 min) | ~1-15/batch | Rapid recurrence burst |

- 30-day: ~6 ALARM transitions, concentrated on 2 days only
- On burst days, Duration p99 rises from ~100 ms to ~600–1,650 ms
- This is a low-frequency transient AWS issue, not a code regression, but the code's handling of partial failure creates silent data loss

## Helper parsing note

The alarm name `kinesis-record-dispatcher lambda error` is **not auto-parsed** by the helper text detector. Pass `--alarm-name 'kinesis-record-dispatcher lambda error'` explicitly.

## Related metric

- `AWS/Kinesis` `PutRecords.FailedRecords` by `StreamName` confirms real AWS-side partial failures
- Cross-check: this metric should be non-zero in the same window as the Lambda ERROR logs; if it is zero while Lambda ERRORs fire, the trigger is a different error pattern
