# Lambda ConsoleErrors: Handled Business / Configuration Rejection False Positives

Class-level reference for Lambda alarms in the `ConsoleErrors` namespace where the trigger is a handled business rejection, missing configuration, or expected no-op outcome that was logged at `ERROR` level and caught by the coarse `%ERROR|Status: timeout%` metric filter. Lambda `Errors` and `Throttles` are zero; the invocation completes normally.

## Quick classification

- `AWS/Lambda Errors == 0` and `Throttles == 0`
- Log line contains phrases like `skipping`, `missing`, `already exists`, `not found`, `invalid`, `failed to` but processing continues or exits normally
- Alarm is typically `no_action` for the current occurrence; use `needs_fix` only when recurrence is daily/many and producing alert noise
- Long-term fix: downgrade `console.error` to `console.warn` or `console.info`, or log only compact context (projectId, campaignId, count)

## Known patterns

### kakao-brand-message-delivery: 080 unsubscribe number missing

- Trigger string: `080 unsubscribe number missing, skipping batch: <projectId>/<campaignId>`
- **Log-volume pitfall**: Because this Lambda logs full Kakao Bizmessage request/response bodies at INFO level for every batch, the INFO log volume far exceeds ERROR volume. When only 1-2 `080 unsubscribe number missing` ERROR lines exist in the alarm window, helper `current_top_signatures` and `current_trigger_contexts` may show only INFO request-body patterns and report `current_error_detail` as missing. Run a bounded `filter_log_events` with `filterPattern='ERROR'` on the exact alarm window to locate the trigger line when the helper's ERROR detail is empty.
- Code path: `services/lambda/kakao-brand-message-delivery/index.ts` around line 163
- Scope-attribution pitfall: The `/aws/lambda/kakao-brand-message-delivery` log stream often carries both `campaign` and `user_journey` payloads in the same alarm window. The helper's `scope_attribution.scope_kind` may aggregate to `user_journey` even when the actual `080 unsubscribe number missing` ERROR trigger is a `campaign` line with `resource_type: campaign`. Always verify the `resource_type` field on the specific triggering log line before accepting `scope_kind` as definitive.
- Why it happens: Kakao Bizmessage **marketing** (`/marketing/send/basic/batch`) messages require an 080 toll-free unsubscribe number in the sender profile. If the project's `kakaoSenderInfo.unsubscribe_phone_number` is unset, the batch is intentionally skipped.
- Impact: no messages are sent for that batch, but the Lambda returns normally and continues processing remaining batches.
- Scope extraction: log includes `projectId`/`campaignId` directly — map via DynamoDB `project` table.
- Frequency observed: variable; observed ranges include 30d 11 transitions, 7d 11 transitions, 1d 6 transitions. A bursty profile is common: e.g. 30d 67 / 7d 43 / 1d 33 (May 18 alone), or 30d 18 / 7d 18 / 1d 13 where nearly all transitions occurred within the last 7 days. A sudden burst localized to a single campaign indicates a newly active campaign with missing `unsubscribe_phone_number` configuration, not chronic baseline noise.
- Timing: fires throughout the day, not at a fixed clock time. Each spike maps to an individual campaign or user-journey execution rather than a scheduled batch job.
- Exact log line format: `080 unsubscribe number missing, skipping batch: <projectId>/<campaignId> { notiflyUserIdList: [ '...' ] }`
- Rapid recurrence note: when `history.rapid_recurrence.status` is `rapid` or multiple ALARM transitions occur within 10 minutes, verify the current trigger context before classifying. If all transitions show the same `080 unsubscribe number missing` signature for the same campaign, the rapid recurrence is benign batch processing, not a worsening failure.
- Action: classify each occurrence as `no_action` because the Lambda invocation completes normally and no customer-facing delivery occurs. The rejection is handled behavior. However, when this pattern exceeds ~1/day sustained (e.g., 30d > 20), the cumulative noise warrants a `needs_fix` tracking item to downgrade `console.error` to `console.warn` in `services/lambda/kakao-brand-message-delivery/index.ts:163`.

**Fix implementation** (when user asks for a targeted PR or the pattern has crossed the noise threshold):
- File: `services/lambda/kakao-brand-message-delivery/index.ts`
- Change: In the `if (!unsubscribeNumber)` block (around line 163), replace `console.error` with `console.warn` on the skip log line.
- Keep `incrementCampaignDeliveryCounts` at the end of the block so delivery stats remain accurate.
- **Leave the `catch` block around `filterUnsubscribedRecipients` at `console.error`**: an exception there is an actual failure, not a handled rejection.
- No Terraform changes are required; the metric filter continues to work for real failures while the handled path stops tripping it.
- Prior implementation: PR #3673 (`hashimoto/fix-kakao-brand-080-noise`) demonstrates the one-line change.

**Bounded log check** (when helper returns empty `current_trigger_contexts`):
```bash
python3 -c "
import boto3, datetime
session = boto3.Session(region_name='ap-northeast-2')
logs = session.client('logs')
start = int(datetime.datetime(YYYY, MM, DD, HH, MM, tzinfo=datetime.timezone.utc).timestamp() * 1000)
end   = int(datetime.datetime(YYYY, MM, DD, HH, MM, tzinfo=datetime.timezone.utc).timestamp() * 1000)
resp = logs.filter_log_events(
    logGroupName='/aws/lambda/kakao-brand-message-delivery',
    startTime=start, endTime=end,
    filterPattern='ERROR',
    limit=50
)
for e in resp.get('events', []):
    print(e['message'].strip()[:300])
"
```

### cafe24-token-refresher: deleted/completed mall token refresh failure

- Trigger string: `Failed to get fresh token <mall_id> invalid_client Uninstalled app. Please re-acquire admin consent.`
- Log line: `ERROR	Failed to get fresh token drlabnosh invalid_client Uninstalled app. Please re-acquire admin consent.`
- Data source: `cafe24_integration` DynamoDB table — scanned by `getCandidatesToRefreshAccessToken` without a `status` filter.
- Root cause: `services/lambda/cafe24-token-refresher/lib/ddb.js` `getCandidatesToRefreshAccessToken` only filters on `token.expires_at <= now + 10min`. It does **not** check the `status` field. Malls with `status: deleted` or `status: completed` remain in the table and are repeatedly scanned for refresh. When the Cafe24 app is uninstalled, the OAuth refresh request returns `invalid_client`, which is logged at `ERROR` level in `lib/cafe24.js` or its caller.
- Impact: Lambda continues after logging the ERROR; 56 of 57 candidates in the observed run succeeded. The invocation completes normally with `Errors=0`.
- Scope: extract `project_id` from the candidate object in the log (e.g. `c91f318c73235d7c8e72266f2cf28452` / `doctor-labnosh`) and map via DynamoDB `project`. When `project_id` is not present, use the `mall_id` to look up the `cafe24_integration` item.
- Classification: `no_action` for isolated occurrences because the Lambda completes normally and the mall is no longer active. If the same deleted mall fires repeatedly over days, classify as `needs_fix` because the noise is structural.
- Immediate fix: Delete the `mall_id` row from the `cafe24_integration` DynamoDB table. This is safe when the project is `deleted` or `completed` and the app is uninstalled.
- Structural fix: Add a `FilterExpression` on `status` in `getCandidatesToRefreshAccessToken` so that only `token_issued` (or equivalent active status) records are candidates. For example: add `AND (#st = :active)` with `ExpressionAttributeNames {'#st': 'status'}` and `ExpressionAttributeValues {':active': 'token_issued'}`.
- Frequency observed: 30d 1 / 7d 1 / 1d 1 / 10m 1 — single occurrence in current window, but will recur every time the expired token is re-scanned.
- Bounded log check (when helper returns empty `current_trigger_contexts`):
```bash
python3 -c "
import boto3, datetime
session = boto3.Session(region_name='ap-northeast-2')
logs = session.client('logs')
start = int(datetime.datetime(2026, 5, 21, 2, 0, tzinfo=datetime.timezone.utc).timestamp() * 1000)
end   = int(datetime.datetime(2026, 5, 21, 2, 20, tzinfo=datetime.timezone.utc).timestamp() * 1000)
resp = logs.filter_log_events(
    logGroupName='/aws/lambda/cafe24-token-refresher',
    startTime=start, endTime=end,
    filterPattern='ERROR',
    limit=10
)
for e in resp.get('events', []):
    print(e['message'].strip()[:300])
"
```

### cafe24-worker: handled SQS record rejection / invalid command / malformed payload

- Trigger strings: `Record <messageId> failed, will retry via SQS:`, `Unsupported command:`, `The body from sqs record is not in JSON format.`, `Invalid record format`, `Project id or token not found for mallId`, `Failed to add user of <mallId>`, `Failed to update user properties of <mallId>`, `API request failed with`
- Code path: `services/lambda/cafe24-worker/index.js` and `lib/jobs/*.js`
- Why it happens: `cafe24-worker` is an SQS consumer Lambda that processes Cafe24 webhook events (`add_user`, `order_completed`, `add_to_cart`, etc.). It uses `Promise.allSettled()` and returns `batchItemFailures` for any rejected task. Rejected — including those logged with `console.error` — are **handled by the Lambda runtime**: SQS will retry per the queue's `RedrivePolicy` (`maxReceiveCount: 6` for `cafe24-worker-queue`). The Lambda itself returns normally with `return { batchItemFailures }`.
- Invocation health: `AWS/Lambda Errors == 0`, `Throttles == 0`, `Duration` well under `Timeout` (typically < 2 s, p99 < 1.2 s). `REPORT` lines show normal completion.
- Impact: individual SQS records retry through standard SQS redrive. No data loss because `maxReceiveCount: 6` provides ample retry budget before DLQ. DLQ depth is typically zero.
- Scope extraction: the ERROR log often carries `mallId` (e.g. `chosunhnb`, `vorio01`). Map `mallId` → `project_id` via DynamoDB `cafe24_integration` table or use the `mall_id` field in the SQS body. When the log line is a generic `index.js` handler error (`Unsupported command`, `Invalid record format`), `mallId` may still be present. No `campaign_id` or `user_journey_id` is involved in this Lambda.
- Metric-filter note: the `%ERROR|Status: timeout%` filter catches all of the above because they contain the literal substring `ERROR`. There is no separate `timeout` signal here; the `|Status: timeout` clause is the metric-filter's catch-all for other Lambda failure modes.
- **Log-ingestion pitfall**: `cafe24-worker` has low traffic and short-lived log streams. When an alarm fires, `filter-log-events` may return zero results even though the metric filter demonstrably breached, because the matching log line has not yet been indexed or the stream already rotated. In this state, do not conclude the alarm is unclassifiable. Cross-check `AWS/Lambda Errors`, queue depth, and DLQ depth instead.
- Classification: `no_action` when `Lambda Errors=0`, queue metrics are healthy, and recurrence is sparse (observed ~1/week, e.g. 30d 4 / 7d 1 / 1d 1). Each alarm is a transient handled rejection, not a service fault.
- Action target (if noise threshold is crossed, e.g. > 1/day sustained):
  - In `services/lambda/cafe24-worker/index.js`, change the non-rate-limit rejection log from `console.error` to `console.warn`:
    ```js
    // Line ~93
    console.warn(`Record ${tasks[i].messageId} failed, will retry via SQS:`, reason);
    ```
  - Keep `batchItemFailures.push(...)` unchanged so SQS retry still works.
  - For job-level errors (`lib/jobs/*.js`), prefer `console.warn` for expected failures (missing project/token, invalid params) and keep `console.error` only for unexpected exceptions (network failure, DB write failure).
  - No Terraform or alarm changes needed; the metric filter still catches real Lambda invocation failures (`Errors > 0`).
- Bounded log check (when helper returns empty `current_trigger_contexts`):
```bash
python3 -c "
import boto3, datetime
session = boto3.Session(region_name='ap-northeast-2')
logs = session.client('logs')
start = int(datetime.datetime(YYYY, MM, DD, HH, MM, tzinfo=datetime.timezone.utc).timestamp() * 1000)
end   = int(datetime.datetime(YYYY, MM, DD, HH, MM, tzinfo=datetime.timezone.utc).timestamp() * 1000)
resp = logs.filter_log_events(
    logGroupName='/aws/lambda/cafe24-worker',
    startTime=start, endTime=end,
    filterPattern='ERROR',
    limit=50
)
for e in resp.get('events', []):
    print(e['message'].strip()[:300])
"
```

### cafe24-worker: missing user table on shop-delete DELETE (42P01)

- Trigger string: `Failed to delete <mallName> from notifly, error: error: relation "user_<hash>" does not exist`
- **Exact log line**:
  ```
  ERROR	<request_id>	Failed to delete heodakmkt from notifly, error: error: relation "user_f3d350d0d5bb50ccaf875b6bafd1442c" does not exist
  Query: DELETE FROM device_f3d350d0d5bb50ccaf875b6bafd1442c WHERE notifly_user_id IN ( SELECT notifly_user_id FROM user_f3d350d0d5bb50ccaf875b6bafd1442c WHERE source = 'cafe24' )
  ```
- Code path: `services/lambda/cafe24-worker/lib/jobs/shopDelete.js` (or equivalent shop-deletion job) constructs a cross-table DELETE that joins `device_<hash>` with `user_<hash>` filtered by `source = 'cafe24'`.
- Why it happens: When a Cafe24 shop deletion webhook arrives, the Lambda tries to delete Cafe24-sourced users and their devices. If the project's `user_<hash>` table does not exist (e.g., project migrated to a different shard scheme, or users were never created via Cafe24), PostgreSQL returns `42P01` (`relation does not exist`). The error is caught and logged at `ERROR` level, tripping the `%ERROR%` metric filter.
- Invocation health: `AWS/Lambda Errors == 0`, `Throttles == 0`, `Duration` normal (< 2 s). Lambda completes normally.
- Impact: no data is deleted because the source table doesn't exist. No customer-visible failure occurs; the webhook response to Cafe24 is not affected.
- Scope extraction: Extract the 32-char hex hash from the table name in the ERROR log (e.g. `user_f3d350d0d5bb50ccaf875b6bafd1442c` → `f3d350d0d5bb50ccaf875b6bafd1442c`). Map via DynamoDB `project` table. In the observed case this resolves to `fresheasy` (`product_id: fresheasy`). The shop name (e.g. `heodakmkt`) is present in the log line. No `campaign_id` or `user_journey_id` is involved.
- Frequency observed: 30d 4 / 7d 2 / 1d 1 / 10m 1. The 7d window shows two OK→ALARM transitions (2026-05-28, 2026-06-02), suggesting a low-rate recurring pattern tied to shop-deletion events for this or other projects.
- Queue / DLQ state: `cafe24-worker-queue` has `maxReceiveCount: 6`, DLQ depth 0, queue depth 0. Even when the SQS record carries the deletion event, redrive handles transient failures; this specific pattern is not an SQS retry issue.
- Classification: `no_action`. Lambda `Errors=0`, queue healthy, and the root cause is a missing target table for a handled deletion request.
- Action target (if recurrence becomes noisy, e.g. > 1/week for multiple projects):
  - In the shop-deletion job, verify `user_<hash>` table existence before issuing the DELETE (e.g. via `pg_class` or a try/catch with `42P01` downgrade), or simply downgrade the caught `42P01` log to `WARN` when the table is known not to exist.
  - Alternative: log only `mallName`, `projectId`, and a compact code (`USER_TABLE_MISSING`) rather than the full SQL statement.

**Bounded log check** (when helper returns empty `current_trigger_contexts`):
```bash
python3 -c "
import boto3, datetime
session = boto3.Session(region_name='ap-northeast-2')
logs = session.client('logs')
start = int(datetime.datetime(YYYY, MM, DD, HH, MM, tzinfo=datetime.timezone.utc).timestamp() * 1000)
end   = int(datetime.datetime(YYYY, MM, DD, HH, MM, tzinfo=datetime.timezone.utc).timestamp() * 1000)
resp = logs.filter_log_events(
    logGroupName='/aws/lambda/cafe24-worker',
    startTime=start, endTime=end,
    filterPattern='does not exist',
    limit=20
)
for e in resp.get('events', []):
    print(e['message'].strip()[:400])
"
```
**7-day recurrence check**:
```bash
aws logs start-query --region ap-northeast-2 \
  --log-group-name '/aws/lambda/cafe24-worker' \
  --start-time $(python3 -c "import datetime; print(int((datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=7)).timestamp()))") \
  --end-time $(python3 -c "import datetime; print(int(datetime.datetime.now(datetime.timezone.utc).timestamp()))") \
  --query-string 'fields @timestamp, @message | filter @message like "does not exist" | stats count() by bin(1d)'
# Then poll with get-query-results
```

- Trigger strings: `Record <messageId> failed, will retry via SQS:`, `Unsupported command:`, `The body from sqs record is not in JSON format.`, `Invalid record format`, `Project id or token not found for mallId`, `Failed to add user of <mallId>`, `Failed to update user properties of <mallId>`, `API request failed with`
- Code path: `services/lambda/cafe24-worker/index.js` and `lib/jobs/*.js`
- Why it happens: `cafe24-worker` is an SQS consumer Lambda that processes Cafe24 webhook events (`add_user`, `order_completed`, `add_to_cart`, etc.). It uses `Promise.allSettled()` and returns `batchItemFailures` for any rejected task. Rejected — including those logged with `console.error` — are **handled by the Lambda runtime**: SQS will retry per the queue's `RedrivePolicy` (`maxReceiveCount: 6` for `cafe24-worker-queue`). The Lambda itself returns normally with `return { batchItemFailures }`.
- Invocation health: `AWS/Lambda Errors == 0`, `Throttles == 0`, `Duration` well under `Timeout` (typically < 2 s, p99 < 1.2 s). `REPORT` lines show normal completion.
- Impact: individual SQS records retry through standard SQS redrive. No data loss because `maxReceiveCount: 6` provides ample retry budget before DLQ. DLQ depth is typically zero.
- Scope extraction: the ERROR log often carries `mallId` (e.g. `chosunhnb`, `vorio01`). Map `mallId` → `project_id` via DynamoDB `cafe24_integration` table or use the `mall_id` field in the SQS body. When the log line is a generic `index.js` handler error (`Unsupported command`, `Invalid record format`), `mallId` may still be present. No `campaign_id` or `user_journey_id` is involved in this Lambda.
- Metric-filter note: the `%ERROR|Status: timeout%` filter catches all of the above because they contain the literal substring `ERROR`. There is no separate `timeout` signal here; the `|Status: timeout` clause is the metric-filter's catch-all for other Lambda failure modes.
- **Log-ingestion pitfall**: `cafe24-worker` has low traffic and short-lived log streams. When an alarm fires, `filter-log-events` may return zero results even though the metric filter demonstrably breached, because the matching log line has not yet been indexed or the stream already rotated. In this state, do not conclude the alarm is unclassifiable. Cross-check `AWS/Lambda Errors`, queue depth, and DLQ depth instead.
- Classification: `no_action` when `Lambda Errors=0`, queue metrics are healthy, and recurrence is sparse (observed ~1/week, e.g. 30d 4 / 7d 1 / 1d 1). Each alarm is a transient handled rejection, not a service fault.
- Action target (if noise threshold is crossed, e.g. > 1/day sustained):
  - In `services/lambda/cafe24-worker/index.js`, change the non-rate-limit rejection log from `console.error` to `console.warn`:
    ```js
    // Line ~93
    console.warn(`Record ${tasks[i].messageId} failed, will retry via SQS:`, reason);
    ```
  - Keep `batchItemFailures.push(...)` unchanged so SQS retry still works.
  - For job-level errors (`lib/jobs/*.js`), prefer `console.warn` for expected failures (missing project/token, invalid params) and keep `console.error` only for unexpected exceptions (network failure, DB write failure).
  - No Terraform or alarm changes needed; the metric filter still catches real Lambda invocation failures (`Errors > 0`).
- Bounded log check (when helper returns empty `current_trigger_contexts`):
```bash
python3 -c "
import boto3, datetime
session = boto3.Session(region_name='ap-northeast-2')
logs = session.client('logs')
start = int(datetime.datetime(YYYY, MM, DD, HH, MM, tzinfo=datetime.timezone.utc).timestamp() * 1000)
end   = int(datetime.datetime(YYYY, MM, DD, HH, MM, tzinfo=datetime.timezone.utc).timestamp() * 1000)
resp = logs.filter_log_events(
    logGroupName='/aws/lambda/cafe24-worker',
    startTime=start, endTime=end,
    filterPattern='ERROR',
    limit=50
)
for e in resp.get('events', []):
    print(e['message'].strip()[:300])
"
```

### Other patterns (see dedicated references)

- `message-event-consumer`: `delivery_policy_inspection_failed__global_frequency_limit` — handled frequency-limit rejection. See `references/message-event-consumer-delivery-policy-error.md`.
- `anomaly-delivery-monitoring`: routine inspection logs at ERROR level. See `references/anomaly-delivery-monitoring-lambda-consoleerrors.md`.
- External provider API 5xx with full error object dumped via `console.error(e)`. See `references/lambda-consoleerrors-external-api-5xx.md`.
- Node.js 22.x deprecation warnings containing literal `ERROR` substring. See `references/nodejs-deprecation-warning-lambda-consoleerrors-false-positive.md`.
- `user-journey-node-runner`: `notiflyUserId is required to match event condition` — handled user journey node validation. See below.

### user-journey-node-runner: LiquidJS TokenizationError on malformed template

- Trigger string: `Failed to build message for context: <notifly_user_id>, projectId: <project_id>` followed by `TokenizationError: output "..." not closed`
- Code path: `services/lambda/user-journey-node-runner/lib/services/executors/MessageNodeBatchExecutor.ts:443`
- Why it happens: During user-journey message-node batch processing, `buildMessages()` renders a LiquidJS template per recipient. If the campaign/user-journey template contains HTML attributes (e.g. `alt="..."`) that break Liquid tokenization, `liquidjs` throws `TokenizerError` / `TokenizationError`. The error is caught, logged with `console.error`, and `pushFailedContext()` records a failure for that recipient. The remaining recipients in the batch continue processing and the Lambda returns normally.
- Impact: One recipient (or a subset matching the bad template) does not receive the message. The batch is not aborted. No Lambda invocation failure occurs.
- Invocation health: `AWS/Lambda Errors == 0`, `Throttles == 0`, `Duration` stays well under `Timeout`. The `REPORT` line shows normal completion.
- Scope extraction: The ERROR log carries `projectId` directly (e.g. `13645f66a993575995631aad71b37ca3`). Map via DynamoDB `project` table. The `notifly_user_id` context value is also present. `campaign_id` or `user_journey_id` may not appear in the same log line; look for `campaign_id`/`user_journey_id` in adjacent Kinesis record `Processing` lines.
- 30-day frequency pitfall: ConsoleErrors log count for this Lambda can be dominated by a single bad day (e.g. 6,316 on 2026-05-15) of WARN `Unexpected error on idle client` pg-pool ETIMEDOUT lines that contain the literal word `Error` and therefore trip the metric filter. Always inspect `logs.daily_counts_30d` before judging severity. The actual alarm transition count (OK→ALARM) is the better severity signal.
- Classification: `no_action` when isolated and Lambda `Errors == 0`. The root cause is a client-authored template with invalid Liquid syntax, not a service bug.
- Action target: In `MessageNodeBatchExecutor.ts`, change the handled template-failure log from `console.error` to `console.warn` and log only `projectId`, `notifly_user_id`, and a compact error code instead of the full LiquidJS stack trace.
- Bounded log check (when helper returns empty `current_error_details`):
```bash
python3 -c "
import boto3, datetime
session = boto3.Session(region_name='ap-northeast-2')
logs = session.client('logs')
start = int(datetime.datetime(YYYY, MM, DD, HH, MM, tzinfo=datetime.timezone.utc).timestamp() * 1000)
end   = int(datetime.datetime(YYYY, MM, DD, HH, MM, tzinfo=datetime.timezone.utc).timestamp() * 1000)
resp = logs.filter_log_events(
    logGroupName='/aws/lambda/user-journey-node-runner',
    startTime=start, endTime=end,
    filterPattern='TokenizationError',
    limit=20
)
for e in resp.get('events', []):
    print(e['message'].strip()[:400])
"
```

### user-journey-node-runner: notiflyUserId is required to match event condition

- Trigger string: `notiflyUserId is required to match event condition`
- Code path: **not found in raw source**; the string does not appear in the `notifly-event` TypeScript source tree. It likely originates from a compiled/bundled dependency or a shared package built into the Lambda artifact.
- Why it happens: during user journey node execution, a record arrives that lacks `notiflyUserId` — a required field for matching event conditions. The code detects the missing identifier, logs an ERROR, and skips processing that record. The Lambda batch continues with remaining records.
- Impact: no message is sent for the missing-user record, but the invocation completes normally.
- Scope extraction: the `user-journey-node-runner` Lambda processes Kinesis records from `notifly-user-journey-node-stream`. The record payload itself does not always contain `project_id`/`campaign_id` inline. Look for `event_intermediate_counts_<project_id>` table references in the same log stream to infer the project scope. DynamoDB `project` mapping confirms `getcha` (8172b3a8b8fe57ad9cc41a03646b0947) and `playio` (ffde3a7a000b5b2198961b3fff400acd) as active projects for this Lambda.
- Classification: `no_action` when isolated and Lambda `Errors == 0`. The log is a handled data-quality validation, not a service fault.
- Frequency observed: 30d 6 ALARM / 7d 5 / 1d 1 / 10m 1 — sporadic, not daily recurring. On 2026-05-15 a large Aurora reader-replica conflict spike (6316 ERROR logs) produced a distinct signature and should be triaged separately under the `canceling statement due to conflict with recovery` pattern.
- Action target: locate the exact source in `packages/` or a bundled dependency that emits this ERROR, then downgrade to `WARN` and log only `projectId` / count. Until the exact source file is found, the next lookup target is a full-text search across the Lambda artifact build output or a dependency audit for `notiflyUserId` validation.
