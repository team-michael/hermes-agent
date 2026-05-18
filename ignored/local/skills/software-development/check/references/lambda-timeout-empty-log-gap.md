# Lambda timeout with empty log-gap triage

## When to use

- CloudWatch `ConsoleErrors` alarm on a Lambda log group where `current_trigger_contexts` shows only `REPORT ... Status: timeout`
- No ERROR-level application logs visible between `START` and `REPORT`
- Alarm is driven by metric filter `%ERROR|Status: timeout%` matching the timeout REPORT line
- `AWS/Lambda Errors` may be zero in the alarm window because the timeout is counted in a different minute bucket

## Evidence to collect

1. **Lambda Duration metric** (`AWS/Lambda`, `Maximum`) around the alarm window. A 900,000ms (15min) spike confirms the timeout.
2. **Lambda Errors metric** (`AWS/Lambda`, `Sum`) at 1-min granularity. The error may register in the *start* minute, not the *end* minute, because CloudWatch metric aggregation uses the invocation's reported `Duration` completion time.
3. **SQS queue attributes** for the Lambda's event source:
   - `RedrivePolicy.maxReceiveCount`: aggressive value of `1` means any timeout immediately routes to DLQ with zero retries
   - `VisibilityTimeout`: compared against Lambda `Timeout` to assess retry overlap risk
4. **DLQ depth**: if `ApproximateNumberOfMessagesVisible` is zero, the message was already retried or consumed
5. **Post-timeout retry Duration**: subsequent invocations after a timeout may show elevated Duration (~20–30s vs. normal ~500ms), indicating downstream dependency latency (e.g., SES, external provider)
6. **Log gap analysis**: check whether `SendResultsInsertQuery` or other "work complete" logs appear minutes or hours before `END`/`REPORT`. If work completed but the invocation remained alive, suspect:
   - an unawaited Promise or background task
   - a hanging network call (e.g., SES sendEmail without proper timeout)
   - Node.js event-loop blockage

## Scope attribution from Lambda logs

Lambda SQS event payloads typically contain `project_id` and `campaign_id` in the `Records[].body` JSON. Sanitize and extract these from the `Received event from SQS:` INFO log line. Map `project_id` via DynamoDB `project` table.

## Classification guidance

- **Transient isolated timeout**: If 30d/7d alarm count is single-digit, DLQ is empty, and retry succeeded (visible `send_success` DB inserts or subsequent normal Lambda invocations), classify as `no_action` with a note to monitor for recurrence.
- **Deployment-correlated timeout**: If `LastModified` is within minutes of the alarm onset and metric history shows zero errors before deployment, treat as deploy-related and consider rollback.
- **Recurring dependency latency**: If post-timeout retry invocations consistently show elevated Duration (e.g., 20s+) and this pattern repeats across multiple days, the root cause is likely an external provider SES/network latency issue, not the Lambda code. Use `needs_fix` to track downstream timeout tuning or provider escalation.
- **Batch-spike + SQS maxReceiveCount=1 timeout**: When a scheduled campaign produces a message spike that the Lambda cannot process within its timeout window (serial processing with Bottleneck `maxConcurrent: 1`, SQS `BatchSize: 10`), the entire batch is DLQed with zero retries. This is `needs_fix` because real emails are not delivered and the DLQ must be processed manually.

## Email-delivery specific findings

The `email-delivery` Lambda has unique characteristics that alter the timeout triage:

### Bottleneck serial scheduling
- `services/lambda/email-delivery/lib/limiter.js` uses `Bottleneck` with `maxConcurrent: 1` and dynamic `minTime` (2500ms when send count < 500, 1000ms when >= 500).
- `sendEmailAndLogResult` is wrapped in `Scheduler.schedule()`, so parallel `Promise.all(promises)` invocations are serialized at the limiter level.
- During batch spikes (e.g., 1,175 SQS messages = ~58,750 emails at once), each Lambda invocation with `BatchSize: 10` can process at most ~1 message per second. The 900s timeout is reached well before the batch finishes.

### Empty log gap mechanism
- The Lambda logs `SendResultsInsertQuery` (and `SendFailureLogInsertQuery: null`) before the actual `await db.queryWithoutTransaction(queryList)` executes.
- The 900s timeout occurs AFTER the last visible `SendResultsInsertQuery` log, leaving a ~14–15 minute silent gap.
- Last visible log before timeout is often `WARN Failed to increment campaign delivery counts` from `@notifly/delivery-policy` `insertUserExposureLogs`, suggesting the hang occurs during redis/DB connection cleanup after the SES send succeeds.
- Because `context.callbackWaitsForEmptyEventLoop = false` is set, the hang is likely an unawaited Promise or a persistent network/DB connection that the handler awaits on but never resolves.

### Batch + maxReceiveCount=1 impact
- SQS `BatchSize: 10` with `maxReceiveCount: 1` means ALL 10 messages in a timed-out batch go directly to DLQ with zero retries.
- The DLQ count can jump from near-zero to 10+ in a single timeout.
- Emails may have been sent via SES before timeout, but `delivery_result` DB records may be incomplete or missing. Re-processing DLQ risks duplicate sends.
- **Action**: inspect DLQ for `project_id`/`campaign_id`, then decide whether to re-drive (risk duplicate sends) or suppress and notify the customer.

### Post-timeout recovery pattern
- After the initial spike, Lambda Duration normalizes to ~23s per invocation (normal for `email-delivery`).
- Queue clears gradually (e.g., 540 → 260 messages over ~30 minutes).
- This confirms the timeout was caused by the batch spike overwhelming serial processing, not a persistent dependency outage.

## Example timeline from `email-delivery`

```
09:55 UTC  Lambda Errors=1 (60s bucket)
10:00 UTC  START RequestId: <uuid>
10:00 UTC  SendResultsInsertQuery: INSERT INTO delivery_result_... send_success
           <-- 15-minute empty gap, no ERROR logs -->
10:15 UTC  REPORT ... Duration: 900000ms Status: timeout
10:16 UTC  ConsoleErrors alarm fires
10:16 UTC  Next Lambda retry succeeds in ~24s
```

Key insight: the timeout is real, but the actual delivery work completed 15 minutes earlier. The hang is after the last visible log line.
