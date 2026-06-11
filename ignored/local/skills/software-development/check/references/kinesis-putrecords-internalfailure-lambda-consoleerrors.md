# Kinesis PutRecords InternalFailure Lambda ConsoleErrors False Positive

## Context

Lambda `kinesis-record-dispatcher` and `user-journey-kinesis-record-dispatcher` consume SQS messages and write aggregated records to Kinesis via `@notifly/kinesis` (`packages/kinesis/src/lib/kinesis.ts`).
The `putRecords` helper logs partial batch failures at `ERROR` level (`packages/kinesis/src/lib/kinesis.ts:162-165`) but does **not** retry them.

## Triggering Log Signature

```
<timestamp> <uuid> ERROR Failed to put <n> records out of <m>, failed records: [{"ErrorCode":"InternalFailure","ErrorMessage":"Internal service failure."}, ...]
```

## Why This Is a False Positive (Most Cases)

- Lambda runtime `Errors` = 0 and `Throttles` = 0 (`AWS/Lambda` metrics).
- Lambda `Duration` stays well below `Timeout` (typically < 1.5s for small batches).
- The failure is a **transient AWS Kinesis internal error**, not a code bug.
- The invocation completes normally; only a subset of the batch records fail.
- `@notifly/kinesis` retries at the SDK level (`maxAttempts: 10`) for transport errors, but partial batch failures (`PutRecordsResult` with `FailedRecordCount > 0`) are logged and returned without retry.

## Evidence Chain for Classification

1. `AWS/Lambda` `Errors` / `Throttles` / `Duration` for the function — confirm zero runtime failures.
2. `AWS/Kinesis` `PutRecords.FailedRecords` on the target stream — verify the transient spike and that it correlates with the alarm window.
3. `AWS/Kinesis` `PutRecords.TotalRecords` — compute failure ratio (typically < 0.1%).
4. Confirm the log signature matches `InternalFailure` / `Internal service failure` exactly, not a different error code.

**Pitfall — `PutRecords.FailedRecords` returns zero despite ERROR logs**: The Lambda dispatches to multiple Kinesis streams depending on the SQS payload (`streamName`), so a single-stream metric check may miss the failures. Also, partial-batch failures are often too sparse to register in 5-minute CloudWatch buckets. If the metric shows zero but Lambda logs clearly show `InternalFailure`, trust the logs. Do not block classification on the Kinesis metric.

## Scope Attribution

The SQS payload may contain `project_id`/`campaign_id`/`user_journey_id`, but the `console.error` line dumps only the Kinesis result array without record content. Therefore per-project/campaign scope is **not directly recoverable from the trigger log line**. Report as **infra-wide common pipeline** unless surrounding logs or SQS message inspection reveals scope.

## Classification

- **`no_action`**: Isolated transient burst, Lambda healthy, Kinesis metrics show brief spike. Also applies to a **single-day cluster** (many ALARM transitions within a few hours on one day, with near-zero recurrence on surrounding days) when Lambda metrics remain healthy throughout.
- **`needs_fix`**: Only if the failure becomes frequent (e.g., daily recurring at the same time, or failure rate spikes above ~1% sustained), indicating a structural retry gap rather than random AWS noise.

## Long-Term Fix Direction

1. **Retry partial failures**: After `putRecords`, identify `ErrorCode` in `Records` and retry only the failed subset with exponential backoff. AWS SDK `PutRecords` already retries transport errors, but partial-record failures require application-level retry.
2. **Log-level downgrade**: If retry is implemented, log the partial failure at `WARN`. Keep `ERROR` only when the entire batch fails or retry is exhausted.
3. **Add failed-record DLQ / SQS fallback**: For pipelines where every record matters, route persistently failed records to a dead-letter queue for manual inspection.

## Related Terraform

- `infra/terraform/prod/ap-northeast-2/lambda/functions.tf`: metric filter `%ERROR|Status: timeout%` on `/aws/lambda/kinesis-record-dispatcher`.
