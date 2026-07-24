# KakaoDeliveryResultPoller `BatchCompletion` `outcome=failure` Triage

Alarm family: `KakaoPoller-P1-BatchFailure` and similar `Notifly/KakaoDeliveryResultPoller` `BatchCompletion` alarms with `outcome=failure` dimension.

## Alarm shape

- Namespace: `Notifly/KakaoDeliveryResultPoller`
- Metric: `BatchCompletion`
- Dimension: `outcome` = `failure`
- Statistic: `Sum`, Period: `300`
- Threshold: `>= 1.0`
- EvaluationPeriods: `1`

This is an EMF metric emitted from `services/lambda/kakao-delivery-result-poller/index.ts` line ~643. The metric is written via `emitCount({ outcome }, 'BatchCompletion')` where `outcome` is derived from `batchItemFailures` (non-empty `batchItemFailures` → `failure`).

## Helper behavior

The `check` helper will return empty `metric_filters` and empty `logs` because EMF metrics are not CloudWatch log metric filters. `can_answer_root_cause` may be `true` but `current_error_details` will be empty. Do not treat this as unclassifiable — the Lambda log group exists and carries the error.

## Bounded manual trace

1. **Resolve Lambda function name**: the alarm prefix `KakaoPoller` maps to the actual function `kakao-delivery-result-poller`.
2. **Describe Lambda config** to check `LastModified` against alarm window — if `LastModified` is within hours or days of the alarm onset, suspect a deployment regression. Also inspect `Environment.Variables.SQS_KAKAO_BRAND_MESSAGE_QUEUE_URL`; if absent, Signature A below is the likely root cause.
3. **Filter Lambda logs** with `filterPattern='failure'` or `filterPattern='ERROR'` on `/aws/lambda/kakao-delivery-result-poller` around `StateReasonData.startDate`.
4. **Cross-check `AWS/Lambda` `Errors` metric**: if `Errors == 0`, the failure is a handled code path, not a runtime crash.

## Known failure signatures

### A. Missing `SQS_KAKAO_BRAND_MESSAGE_QUEUE_URL` env var (deployment regression)

Log excerpt:
```
ERROR {"alert":"N_RESEND_ENQUEUE_FAILED","message":"N resend enqueue failed: SQS_KAKAO_BRAND_MESSAGE_QUEUE_URL environment variable is not set",...}
ERROR Failed to process Kakao polling record Error: SQS_KAKAO_BRAND_MESSAGE_QUEUE_URL environment variable is not set
    at enqueueNResendMessages (/var/task/service/n_resend_service.js:170:15)
```

- `AWS/Lambda` `Errors = 0`, `Duration` normal (~170 ms).
- The invocation returns `{ batchItemFailures: [...] }`, which the Lambda runtime handles as a partial batch failure; the SQS message is retried according to `maxReceiveCount`.
- **Classification**: `needs_fix` — the env var must be restored in `infra/terraform/prod/ap-northeast-2/lambda/functions.tf` (the metric alarm is defined at line ~3195 in the `kakao-delivery-result-poller` block).
- The queue URL is `https://sqs.ap-northeast-2.amazonaws.com/702197142747/kakao-brand-message-queue`.
- **Live confirmation (June 2026)**: This exact pattern fired with `LastModified: 2026-06-02T08:14:14+00:00` and the alarm at `2026-06-04T08:18+00:00` (2 days later). The env var was confirmed absent via `get-function-configuration`. Scope was project `michael` (internal test), so customer impact was zero despite the real config gap. Deployment correlation (`get-function-configuration.LastModified` within days of alarm onset) is a strong signal for this signature.

### B. Normal Kakao API business rejection (`completed_failure` PollAttempt, no ERROR)

Log excerpt:
```
INFO ... "project_id":"...","channel":"kakao-brand-message","outcome":"completed_failure","PollAttempt":1
INFO ... "outcome":"success","BatchCompletion":1
```

- The `BatchCompletion` dimension for the whole batch is still `success` because `batchItemFailures` is empty; the sub-task `PollAttempt` records `completed_failure`. In most windows this does **not** breach the `BatchCompletion` alarm.
- If the alarm fires with no ERROR log lines and `Errors == 0`, inspect whether the `completed_failure` count within a single batch triggered the metric. This can happen when a batch of SQS messages contains multiple `completed_failure` polling states. Still classify as `no_action` if the root cause is a handled provider-side result (e.g., message blocked by Kakao).

## Scope extraction

EMF log lines contain plain JSON and carry `project_id`, `campaign_id`, `request_id` directly. Extract `project_id` from the `PollAttempt` or `FailoverSkipped` line and map via DynamoDB `project`.

## Pitfall — Node.js 22 deprecation warnings trip unrelated invocations

`kakao-delivery-result-poller` also runs on Node.js 22.x and may emit `[DEP0040] DeprecationWarning: The punycode module is deprecated...` with `ERROR` severity on cold starts. These are benign but produce `ERROR`-level log lines. When combined with the broad `%ERROR%` metric filter on the Lambda log group, these warnings can appear alongside the real `N_RESEND_ENQUEUE_FAILED` log line. Cross-check `AWS/Lambda Errors`; if `Errors == 0`, the deprecation lines are noise. See `references/nodejs-deprecation-warning-lambda-consoleerrors-false-positive.md` for remediation.

## Pitfall — `filter_log_events` with UUID returns empty

When trying to isolate a specific invocation by `RequestId`, `filter_log_events` with the full UUID may return zero events even when the log stream exists. Use a time-bounded `filter-log-events` with no `filterPattern` (or a simpler term like `failure` / `ERROR`) and grep client-side.

### C. `delivery_failure_log` INSERT `invalid input syntax for type json` (JSON double-escape bug)

Log excerpt:
```
ERROR  invalid input syntax for type json
Query: INSERT INTO delivery_failure_log_<project_id> (id, notifly_user_id, campaign_id, subtype, request_body, response_body, channel, sender_info) VALUES ('...', '...', '<campaign_id>', 'IMAGE', '{"message_variable":{"article_summary":"..."}, "button_variable":{"appUrl":"...&utm_content=한글\\",...}}', ...);
Values: undefined
Params: undefined
```

- `AWS/Lambda` `Errors = 0`, `Duration` normal.
- The Lambda returns `{ batchItemFailures: [...] }` for every message where the DB insert failed — Kakao polling record is retried.
- **Root cause:** `repository/delivery_result_repository.ts:132` — `raw_request_body` is an already-stringified JSON with double-escaped URL encoding containing Korean characters (e.g., `utm_content=미국주식`). After `escapeForSql`, the result is not valid PostgreSQL JSON. The `Params: undefined` / `Values: undefined` line confirms the pg parameterized query binding also fails.
- **Upstream cause:** The send failure itself is usually triggered by a Kakao BZM API error (e.g., `3018` — 이미지 메시지 변수 오류). The INSERT failure is secondary — failure log record is lost, not the delivery attempt per se.
- **Classification:** `needs_fix` — two independent issues: (1) Kakao API rejection (campaign variable/image issue, class101 project), (2) failure log INSERT broken.
- **Scope extraction:** `delivery_failure_log_<project_id>` table suffix gives `project_id`; `campaign_id` appears in the VALUES clause directly.
- **Fix target:** `repository/delivery_result_repository.ts:132` — normalize `raw_request_body` via `JSON.parse` → `JSON.stringify` before SQL interpolation, or switch to parameterized binding. See `references/scheduled-batch-delivery-dbinsert-json-serialization-bug.md` for the full pattern and fix options shared with `scheduled-batch-delivery` and `scheduled-batch-text-message-delivery`.

### D. DynamoDB on-demand adaptive capacity throttling (`ThrottlingException`)

Log excerpt:
```
ERROR Failed to process Kakao polling record ThrottlingException: Throughput exceeds the current capacity of your table or index. DynamoDB is automatically scaling your table or index so please try again shortly.
    at AwsJson1_0Protocol.handleError (.../@aws-sdk/client-dynamodb/...)
    at async repository/polling_state_repository.js:77
    at async withExternalMetrics (/var/task/emf.js:37)
    at async processIplusNFailover (/var/task/...)
```

- `AWS/Lambda` `Errors = 0`, `Throttles = 0` — the error is caught and returned as `batchItemFailures`.
- **Root cause:** DynamoDB table `kakao_delivery_result_polling_state` (on-demand / `PAY_PER_REQUEST`) hits adaptive capacity limits during a burst of polling state writes. Despite being on-demand, DynamoDB can throttle when a single partition key receives a sudden high write rate that exceeds the per-partition burst bucket.
- **Evidence pattern:**
  - `WriteThrottleEvents` on the table (e.g., 40 at 11:44, 25 at 11:45, 12 at 11:46)
  - `ConsumedWriteCapacityUnits` spike (e.g., 141,144 in 1 minute)
  - Lambda `ConcurrentExecutions` spike (e.g., 1 → 5) and `Invocations` surge (e.g., 4 → 136/min) — a scheduled campaign batch floods the queue
  - Table `ItemCount` is small (e.g., 53) — the throttle is from burst write rate, not table size
- **Scope:** The burst is typically driven by one project's Kakao brand message campaign batch. Extract `project_id` from the concurrent `PollAttempt` EMF logs in the same window. Common: `b2b4a8f879a75673b755bff42fc1deb6` (class101).
- **DLQ context:** `maxReceiveCount=3` on `kakao-delivery-result-poller-queue`. Messages that fail 3 times are DLQ'd. DLQ may accumulate (e.g., 237 messages from a prior day's campaign `DR4eXt`). These are polling tasks that exhausted retries — the actual Kakao messages were already sent; only the delivery result polling state is lost.
- **Classification:** `no_action` when isolated (1-2 times/month, Lambda self-recovers, SQS retries handle the failed batch). The polling state loss means the system may not record the final delivery status for some messages, but the messages themselves were delivered.
- **Recurrence:** 3 OK→ALARM transitions in 30 days (2026-06-23, 2026-06-19, 2026-06-04). The 6/19 event was the same DynamoDB throttle pattern; the 6/4 event was Signature A (missing env var).

### E. Batch-level `poll_alimtalk_response_all` provider API error (no `project_id` in the failing invocation)

Log excerpt:
```
INFO {"resource":"kakao_api","operation":"poll_alimtalk_response_all","ExternalCallError":1}
ERROR Failed to process Kakao polling record KakaoResultApiError: Kakao Alimtalk result API request failed
    at assertAlimtalkSuccess (/var/task/client/kakao_client.js:32:15)
    at /var/task/client/kakao_client.js:85:20
    ...
    at async processAlimtalkResultTask (/var/task/processor/alimtalk_processor.js:307:22)
{
  response_code: undefined,
  http_status: 404
}
```

- `AWS/Lambda` `Errors = 0` (confirmed 0 for 30 consecutive days in the live June–July 2026 session), `Duration` normal (~11 ms) — the exception is caught inside the invocation and surfaces only as a `BatchCompletion{outcome:"failure"}` EMF count.
- **Key trace pitfall**: this failure happens inside the batch-level `poll_alimtalk_response_all` call (`kakao_client.js:85` → `assertAlimtalkSuccess`), which runs *before* any per-record `PollAttempt`/`project_id` EMF line is emitted for that invocation. Do not expect a `project_id` in the failing invocation's own log lines — scope is genuinely unrecoverable from this signature alone. Report scope as service-wide/unknown rather than borrowing a `project_id` from a neighboring invocation in the same log stream.
- **Root cause**: the Kakao Alimtalk result-polling API itself returned HTTP 404 for that poll cycle (`response_code: undefined`, `http_status: 404`) — an external provider-side rejection, not a service bug.
- **Classification**: `no_action` when isolated (1 failure in the 5-minute window, `Errors=0`, rest of the batch `outcome:"success"`). This is a variant of Signature B (handled provider error) but at the batch-call layer instead of the per-record `KakaoResultApiError` seen in prior sessions — same classification logic applies.
- **Verification pattern**: `aws logs filter-log-events --filter-pattern "BatchCompletion"` across the alarm's `[startDate, startDate+period)` window quickly shows the ratio of `outcome:"success"` vs `outcome:"failure"` lines — a single `failure` amid dozens of `success` lines confirms an isolated provider blip rather than a systemic issue.

### F. `Kakao Alimtalk result recipient mapping is missing` (unmatched serial numbers, silent drop)

Log excerpt:
```
WARN  Unmatched serial numbers while materializing Kakao Alimtalk results {
  response_id: 127129390,
  channel_key: 'notifly',
  unmatched_count: 3,
  unmatched_serial_numbers: [ '20260701-131708492', '20260701-809962156', '20260702-442167114' ]
}
ERROR Failed to process Kakao polling record Error: Kakao Alimtalk result recipient mapping is missing
    at processAlimtalkResultTask (/var/task/processor/alimtalk_processor.js:362:15)
    at process.processTicksAndRejections (node:internal/process/task_queues:103:5)
    at async processRecord (/var/task/index.js:39:9)
    at async Promise.allSettled (index 1)
    at async Runtime.handler (/var/task/index.js:46:21)
```

- `AWS/Lambda Errors = 0`, `Duration` normal (~160 ms). The error is caught per-record inside `Promise.allSettled` and does not fail the Lambda invocation.
- **No `project_id` in the failing record's own log lines** — `alimtalk_processor.js:362` throws before any project-scoped EMF metric is emitted for that specific serial number. Scope is genuinely unrecoverable from this signature alone (same limitation as Signature E). Do not borrow `project_id` from concurrent unrelated records in the same batch invocation (e.g., `FailoverSkipped project_id=... reason=no_config` lines belong to a *different* record processed in the same 10-message batch).
- **Root cause**: `alimtalk_processor.js` looks up the DynamoDB Alimtalk recipient mapping (`ddb get_alimtalk_recipient_mapping`) by serial number to resolve which `notifly_user_id`/`campaign_id` a Kakao result response corresponds to. When the mapping is missing (e.g., mapping TTL-expired before the async result arrived, or the mapping was never written due to a race in `save_alimtalk_recipient_mapping`), `processAlimtalkResultTask` throws instead of skipping gracefully.
- **Retry/loss behavior — important**: the Lambda's SQS EventSourceMapping has `FunctionResponseTypes: []` (no `ReportBatchItemFailures` configured). A per-record error caught in `Promise.allSettled` does NOT get returned as a `batchItemFailure`, so the entire batch is still ACKed to SQS as successful. This means the failed serial number's result is **not retried** — it is silently dropped, not just delayed. This differs from Signatures A/C/D where the failure does surface as a retryable `batchItemFailure`.
- **Deployment correlation**: first (and as of this writing, only) occurrence came 1h22m after a `kakao-delivery-result-poller` deploy (`LastModified` within the same day as the alarm). Always check `get-function-configuration.LastModified` for this alarm family — a brand-new signature appearing shortly after a deploy is a strong regression signal.
- **Classification**: `needs_fix` when this is a newly observed signature (0 occurrences in the preceding 30 days) — the silent-drop behavior (no `ReportBatchItemFailures`) means the fix should either (a) make `processAlimtalkResultTask` skip missing mappings gracefully with a WARN instead of throwing, or (b) enable `ReportBatchItemFailures` on the EventSourceMapping so per-record failures are retried instead of dropped. Downgrade to `no_action`/monitor only after confirming the signature is a rare, non-recurring race condition with no growing trend.
- **Fix target**: `processor/alimtalk_processor.js:362` (`processAlimtalkResultTask`) and Lambda EventSourceMapping config (`FunctionResponseTypes`) in `infra/terraform/prod/ap-northeast-2/lambda/functions.tf`.

### G. Finalize lock contention (`response batch is locked by another worker`)

Log excerpt:
```
ERROR	Failed to process Kakao polling record Error: Kakao Alimtalk response batch is locked by another worker
    at processAlimtalkResultTask (/var/task/processor/alimtalk_processor.js:332:15)
    at process.processTicksAndRejections (node:internal/process/task_queues:103:5)
    at async processRecord (/var/task/index.js:39:9)
    at async Promise.allSettled (index N)
    at async Runtime.handler (/var/task/index.js:46:21)
```

- `AWS/Lambda Errors = 0`, `Throttles = 0` — caught per-record inside `Promise.allSettled`, not a runtime crash.
- **Mechanism**: `index.ts` (`finalizeTerminalState`, ~line 485) calls `pollingStateRepository.tryAcquireFinalizeLock()` (`repository/polling_state_repository.ts:143`), a DynamoDB conditional `UpdateItem` (`attribute_not_exists(finalize_owner) OR finalize_owner = :owner OR finalize_lock_until < :now`) that guards against two concurrent Lambda invocations finalizing the same `project_id#request_id#sender_key` polling record at once. **When `finalizeTerminalState` itself loses the race it does NOT throw** — it emits `PollAttempt{outcome:'finalize_lock_miss'}` and returns cleanly (index.ts:501-506).
- **Throw site resolved (2026-07-03, follow-up session)**: the literal "response batch is locked by another worker" throw IS in `services/lambda/kakao-delivery-result-poller/processor/alimtalk_processor.ts` (line ~566, confirmed via GitHub Contents API against `main` — this file is TypeScript source; the compiled deploy artifact is `alimtalk_processor.js` with different line numbers, which is why grepping the local checkout for the exact string failed previously and why stack-trace line numbers don't match the `.ts` source directly). This is a **second, distinct lock** from `tryAcquireFinalizeLock`: `alimtalkResultRepository.tryAcquireResponseBatchLock(responseId, lockOwner, now, ALIMTALK_RESPONSE_BATCH_LOCK_TTL_MS)` guards the per-`responseId` result-processing checkpoint (`emitAlimtalkPollAttempt(task, 'locked', ...)` then `throw new Error('Kakao Alimtalk response batch is locked by another worker')`). Do not conflate the two locks — `tryAcquireFinalizeLock` (finalize-stage, silent `finalize_lock_miss` outcome, no throw) is upstream of `tryAcquireResponseBatchLock` (response-processing stage, throws, caught per-record in `Promise.allSettled`). **Lesson**: when a stack trace names a `.js` file but the repo only has `.ts` sources (or a local workspace checkout is missing the service entirely), fetch the tree via `gh api repos/<org>/<repo>/git/trees/main?recursive=1 --paginate` and grep for the service/filename fragment rather than guessing paths — see `references/execute-code-env-credential-loading.md` for the exact command.
- **No `project_id` in the failing record's own log line** — same limitation as Signatures E/F. Scope must come from neighboring `PollAttempt` EMF lines in the same log stream, and even then multiple projects are typically interleaved in one invocation's stream (BatchSize=10 mixes projects). Do not force single-project attribution; report scope as service-wide unless a `finalize_lock_miss` EMF line in the exact same 1-2 second window carries a `project_id`.
- **No data loss in the sense of dropped Kakao messages**, but see the retry caveat below — the Lambda's SQS EventSourceMapping for `kakao-delivery-result-poller-queue` has `FunctionResponseTypes: []` (confirmed live 2026-07-03), i.e. **`ReportBatchItemFailures` is NOT enabled**. A per-record error caught inside `Promise.allSettled` therefore does **not** become a retryable `batchItemFailure` — the whole 10-message batch is still ACKed to SQS as successful, and the failed polling-result record is silently dropped (not retried). Do not assume "SQS retries it" for this alarm family without first confirming `FunctionResponseTypes` on the live EventSourceMapping.
- **Pitfall — do NOT assume this requires ≥2 concurrent invocations**: the mechanism description above (two invocations racing) is the *design intent* of the lock, but live data on 2026-07-03 falsified the assumption that concurrency must be >1 for the lock-contention error to fire. `AWS/Lambda ConcurrentExecutions` stayed at a flat `Maximum: 1` for the entire 20-minute window surrounding a cluster of 9 "locked by another worker" errors (04:03:47–04:05:08 UTC, single Lambda, no overlap). This means the error can also fire when a **single serialized invocation** hits a lock record whose `finalize_lock_until` TTL from a *prior*, already-completed invocation has not yet expired — i.e. a lock-release/TTL timing bug, not (or not only) a true concurrency race. When triaging this signature, check `ConcurrentExecutions` before concluding "concurrent invocation pressure"; if it's flat at 1, redirect the root-cause hypothesis toward `tryAcquireFinalizeLock`'s TTL window (`finalize_lock_until`) being too long relative to the poller's invocation cadence, rather than blaming SQS visibility timeout or `MaximumConcurrency`.
- **Recurrence pattern (updated)**: First observed 2026-07-03 as a single invocation's worth of errors; same-day follow-up investigation (also 2026-07-03, later in the day) found a second, larger cluster — 9 occurrences of "locked by another worker" + 1 occurrence of Signature F ("recipient mapping is missing") **all within an 85-second window** (04:03:47–04:05:08 UTC), against a background of `Errors=0`/`Throttles=0`/`ConcurrentExecutions=1`. Both clusters were dominated by project `b2b4a8f879a75673b755bff42fc1deb6` (class101) — consistent with the DynamoDB-throttle signature's known high-volume batch project. 7-day Logs Insights count for the exact phrase `locked by another worker` was 9 — i.e. this alarm's "new signature" can arrive as one dense burst rather than spread evenly; do not require multi-day spread before treating a same-day cluster as the dominant cause.
- **Mixed-signature windows are expected**: in the 2026-07-03 04:03–04:06 UTC window, `BatchCompletion` showed 10 `outcome:"failure"` vs 19 `outcome:"success"` — i.e. roughly a third of batches failed, and the failures split across two distinct signatures (G dominant, F once). Always tally signature counts per ERROR line rather than assuming one alarm window = one root cause.
- **Classification**: `no_action` on first/isolated occurrence given `Errors=0`, self-recovering alarm. Escalate to `needs_fix` once the signature recurs in a same-day dense cluster (as opposed to a single stray event) — the action target is the lock/TTL timing bug in `tryAcquireFinalizeLock`/`finalize_lock_until` (not just "raise `MaximumConcurrency`", since concurrency was not actually elevated), plus enabling `ReportBatchItemFailures` on the EventSourceMapping in `infra/terraform/prod/ap-northeast-2/lambda/functions.tf` so these caught failures are retried instead of silently dropped.

**Technique — counting a rare log signature over a 7-day window without timing out**: manual bash loops that page through `aws logs filter-log-events --next-token` for a wide time range (e.g., 7 days) on a busy log group can exceed the 60s foreground terminal timeout before finishing, especially on high-volume Lambdas. For a pure count (not needing sample lines), use CloudWatch Logs Insights instead — it aggregates server-side and returns in a few seconds regardless of window width:
```bash
qid=$(aws logs start-query --region ap-northeast-2 \
  --log-group-name /aws/lambda/kakao-delivery-result-poller \
  --start-time $(date -d '7 days ago' +%s) --end-time $(date +%s) \
  --query-string 'fields @message | filter @message like /locked by another worker/ | stats count() as cnt' \
  --output json | jq -r '.queryId')
sleep 5
aws logs get-query-results --region ap-northeast-2 --query-id "$qid" --output json
```
To see the exact timestamps of a rare signature (to check whether it's spread out or clustered), swap the `stats count()` line for `sort @timestamp asc` and read `@timestamp` from each result row.

### Datapoint timestamp interpretation

CloudWatch alarm `StateReasonData` shows a datapoint at timestamp T with Period P. The datapoint covers the window **[T, T+P)** — T is the period **START**, not the end. The actual triggering event is typically near T+P (the end of the window), not near T.

Example: datapoint at `11:40:00` with `Period=300` covers `[11:40:00, 11:45:00)`. The ThrottlingException occurred at `11:44:47` — 4 minutes and 47 seconds into the window. Searching logs in `[11:35:00, 11:40:00)` (the previous period) will miss the actual trigger entirely.

When the helper or `describe-alarms` returns `StateReasonData.recentDatapoints[].timestamp`, always compute the search window as `[timestamp, timestamp + period)` and search towards the end of that window first.

## Classification quick guide

| Errors metric | ERROR logs present | Root cause | Status |
|---|---|---|---|
| 0 | Yes, `N_RESEND_ENQUEUE_FAILED` + missing env var | Deployment regression | `needs_fix` |
| 0 | Yes, `KakaoResultApiError` / provider error | Handled provider rejection | `no_action` |
| 0 | No, only `completed_failure` PollAttempts | Batch-level handled failure | `no_action` |
| 0 | Yes, `invalid input syntax for type json` on `delivery_failure_log_*` INSERT with `Params: undefined` | JSON double-escape bug in `delivery_result_repository.ts:132` + upstream Kakao API error | `needs_fix` |
| 0 | Yes, `ThrottlingException` on `kakao_delivery_result_polling_state` DynamoDB table | On-demand adaptive capacity burst throttle during campaign batch | `no_action` |
| 0 | Yes, `response batch is locked by another worker` (finalize lock contention, exact throw site not in local checkout) | Lock/TTL timing bug — can fire even with `ConcurrentExecutions=1`; not retried (`FunctionResponseTypes=[]`) | `no_action` isolated single event; `needs_fix` once a same-day dense cluster (e.g. 9+ in <2 min) recurs |
| >0 | Unhandled exception / timeout | Runtime bug | `needs_fix` or `urgent` |
