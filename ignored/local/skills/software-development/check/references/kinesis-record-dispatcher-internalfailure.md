# Kinesis Record Dispatcher InternalFailure Triage

## Pattern

`kinesis-record-dispatcher lambda error` alarm (namespace `ConsoleErrors`, metric filter `%ERROR|Status: timeout%`) fires with log signature:

```
ERROR Failed to put <n> records out of <n>, failed records: [{"ErrorCode":"InternalFailure","ErrorMessage":"Internal service failure."}, ...]
```

## Key characteristics

- **Lambda runtime `Errors = 0`, `Throttles = 0`**. The invocation completes normally.
- **SQS message is deleted** after the Lambda returns, because the code catches the partial failure and logs it rather than throwing.
- **Partial failure**: `PutRecords` returns HTTP 200 with some records carrying `ErrorCode: InternalFailure` inside the response array.
- **Root cause is AWS Kinesis internal transient failure**, not Notifly code.

## Code path

- `services/lambda/kinesis-record-dispatcher/index.ts` → `executeCommands()` → `putRecords()` in `lib/kinesis.ts`
- `putRecords` batches records into 300-record chunks (`DEFAULT_BATCH_SIZE = 300`), calls `_putChunk()` which uses `@aws-sdk/client-kinesis` `PutRecordsCommand`.
- On partial failure (`aggregated.FailedRecordCount > 0`), the code logs the failed records at `ERROR` level (`lib/kinesis.ts:80-83`) but **does not throw**.
- The caller (`executeCommands`) catches only exceptions from `putRecords`, not partial failures inside a successful response. So partial failures are logged and swallowed.

## Verification steps

1. **Confirm Lambda health**: `AWS/Lambda` `Errors` and `Throttles` metrics are zero around the alarm window.
2. **Identify target stream**: The log line does not include `streamName`. Cross-check upstream SQS message volume vs downstream Kinesis `PutRecords.Records` metrics to guess the affected stream. Or inspect the Lambda log stream for adjacent `INFO` lines if any.
3. **Check Kinesis stream metrics** for the suspected stream(s):
   - `PutRecords.Latency` — look for spikes (>40ms when baseline is ~10ms)
   - `WriteProvisionedThroughputExceeded` — should be zero; if non-zero, the failure is throttling-based, not pure `InternalFailure`
   - `PutRecords.Records` — check for traffic burst correlating with the failure minute
4. **Check all Kinesis streams** when the target stream is unclear:
   ```bash
   aws kinesis list-streams --region ap-northeast-2
   for stream in <streams>; do
     aws cloudwatch get-metric-statistics --namespace AWS/Kinesis \
       --metric-name PutRecords.Latency --dimensions Name=StreamName,Value=$stream \
       --start-time <window> --end-time <window> --period 60 --statistics Average
   done
   ```
5. **Scope**: `kinesis-record-dispatcher` processes messages from multiple upstream services. The log line does not carry `project_id` or `campaign_id`. Scope is infra-wide unless upstream context is recoverable from surrounding SQS/Lambda logs.

## Classification

- **`no_action`** when:
  - Lambda `Errors = 0`, `Throttles = 0`
  - Kinesis `WriteProvisionedThroughputExceeded = 0`
  - Failure count is small (tens of records) and isolated
  - Stream latency returns to baseline afterward
- **`needs_fix`** only when:
  - The same stream shows repeated `InternalFailure` with increasing frequency
  - Or `WriteProvisionedThroughputExceeded` is non-zero (shard scaling needed)
  - Or partial-failure records are silently lost without any retry or DLQ path

## Long-term improvement options

1. **Retry partial failures**: In `lib/kinesis.ts`, add a bounded retry loop for records that return `InternalFailure` or `ProvisionedThroughputExceededException`.
2. **Log-level downgrade**: If the team decides partial Kinesis failures are acceptable at WARN/INFO (because they are transient and retries will be added), change the log level in `lib/kinesis.ts:80`.
3. **Emit retryable failures to DLQ**: Instead of swallowing partial failures, return a batch item failure or send failed records to a dead-letter path.
4. **Stream-level alerting**: Split `ConsoleErrors` metric filter into per-stream filters if one noisy stream drowns out others.

## Terraform location

- Alarm: `infra/terraform/prod/ap-northeast-2/lambda/functions.tf` line ~3759 (`kinesis-record-dispatcher lambda error`)
- Metric filter: same file line ~3776 (`%ERROR|Status: timeout%`)
- Lambda config: same file under `kinesis-record-dispatcher` entry
