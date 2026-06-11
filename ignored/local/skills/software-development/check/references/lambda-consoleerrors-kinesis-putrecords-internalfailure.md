# Lambda ConsoleErrors — Kinesis PutRecords InternalFailure

## Pattern

`kinesis-record-dispatcher lambda error` alarm (namespace `ConsoleErrors`) fires with a coarse metric filter `%ERROR|Status: timeout%`. Lambda runtime `Errors` is zero, Duration is well under the 300s Timeout, and log lines show:

```
ERROR Failed to put N records out of M, failed records: [{"ErrorCode":"InternalFailure","ErrorMessage":"Internal service failure."}]
```

## Root cause

`@notifly/kinesis` `putRecords()` calls Kinesis `PutRecordsCommand` with `bypassSqs: true` (see `packages/kinesis/src/lib/kinesis.ts`). AWS Kinesis intermittently returns `InternalFailure` for individual records in the batch (HTTP 200 response with per-record `ErrorCode`). The SDK-level `PutRecordsCommand` succeeds, so no exception is thrown up to the Lambda. The helper function `_aggregateResults` detects `FailedRecordCount > 0` and logs the failed records via `console.error`. The coarse metric filter matches the literal `ERROR` string.

The Lambda invocation completes normally, so `AWS/Lambda Errors = 0` and `Throttles = 0`.

## Behavior

- The Lambda reads SQS messages, aggregates Kinesis records, and calls `putRecords`.
- Individual record failures are emitted as a single `console.error` line listing all failed records.
- No retry is attempted for the failed subset within the same invocation.
- Typical Duration during failure is ~1,100–1,600ms; normal Duration is ~30–80ms.

## Scope

No project, campaign, or user journey IDs appear in the `kinesis-record-dispatcher` logs (the SQS payload is consumed without logging `project_id`). This is an **infra-wide common pipeline** alert. Do not force a project scope.

## Classification

| Signal | Interpretation |
|--------|---------------|
| `AWS/Lambda Errors = 0` | Not an unhandled exception or timeout |
| `AWS/Lambda Throttles = 0` | Not Lambda throttling |
| `Duration < 300s` | Not a hang or timeout |
| Kinesis `InternalFailure` on a small subset of records | Transient AWS service error |

- **Default**: `no_action` when the daily transition count is low (e.g. ≤~5 transitions in a day) and isolated after a quiet baseline. This reflects a transient AWS Kinesis issue.
- **Elevate to `needs_fix`** when the daily transition count is high (e.g. ≥~15 transitions in one day) after a baseline of zero or near-zero for multiple days. In that state, the volume of silently dropped Kinesis records can exceed transient-noise thresholds, especially for the `TRIGGERING_EVENTS` or `MESSAGE_EVENTS` streams that feed campaign/user-journey delivery.
- **Long-term**: Kinesis `PutRecords` already uses `maxAttempts: 10` with `retryMode: 'standard'`, but that only retries the entire HTTP request, not individual failed records. For critical delivery paths, consider whether the caller should re-emit failed records or downgrade the log to `WARN` when the failure rate is low and transient. Do not downgrade if the Kinesis stream is a critical data path and silent loss is unacceptable.

## Silent-data-loss caveat

The `kinesis-record-dispatcher` consumer SQS queue uses `maxReceiveCount: 1` (`RedrivePolicy` on `kinesis-record-dispatcher-queue`). Because the Lambda invocation completes normally despite partial record failures, SQS deletes the message and no DLQ entry is created. The failed records are lost without downstream retry. If you need to estimate blast radius, count `FailedRecordCount` across the clustered alarm window rather than DLQ depth.

## Evidence to collect

1. Lambda runtime `Errors` / `Throttles` — must be `0`.
2. Lambda `Duration` around alarm window — confirm it is well under `Timeout`.
3. Bounded `filter-log-events` on `/aws/lambda/kinesis-record-dispatcher` for the alarm datapoint window with `filterPattern='ERROR'`.
4. Read alarm history to verify recurrence. Typically clustered within a single day with gaps of days to weeks between clusters.

## Related reference

- For the broader Kinesis dispatcher queue/DLQ pattern, see `references/kinesis-record-dispatcher-queue-spike.md`.
- For throughput bottleneck analysis on the SQS consumer side, see `references/kinesis-record-dispatcher-queue-throughput.md`.
- For the `kds-consumer` Kinesis consumer side, see `references/kds-consumer-event-timestamp-rangeerror.md`.
