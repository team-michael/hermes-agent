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

### Other patterns (see dedicated references)

- `message-event-consumer`: `delivery_policy_inspection_failed__global_frequency_limit` — handled frequency-limit rejection. See `references/message-event-consumer-delivery-policy-error.md`.
- `anomaly-delivery-monitoring`: routine inspection logs at ERROR level. See `references/anomaly-delivery-monitoring-lambda-consoleerrors.md`.
- External provider API 5xx with full error object dumped via `console.error(e)`. See `references/lambda-consoleerrors-external-api-5xx.md`.
- Node.js 22.x deprecation warnings containing literal `ERROR` substring. See `references/nodejs-deprecation-warning-lambda-consoleerrors-false-positive.md`.
- `user-journey-node-runner`: `notiflyUserId is required to match event condition` — handled user journey node validation. See below.

### user-journey-node-runner: notiflyUserId is required to match event condition

- Trigger string: `notiflyUserId is required to match event condition`
- Code path: **not found in raw source**; the string does not appear in the `notifly-event` TypeScript source tree. It likely originates from a compiled/bundled dependency or a shared package built into the Lambda artifact.
- Why it happens: during user journey node execution, a record arrives that lacks `notiflyUserId` — a required field for matching event conditions. The code detects the missing identifier, logs an ERROR, and skips processing that record. The Lambda batch continues with remaining records.
- Impact: no message is sent for the missing-user record, but the invocation completes normally.
- Scope extraction: the `user-journey-node-runner` Lambda processes Kinesis records from `notifly-user-journey-node-stream`. The record payload itself does not always contain `project_id`/`campaign_id` inline. Look for `event_intermediate_counts_<project_id>` table references in the same log stream to infer the project scope. DynamoDB `project` mapping confirms `getcha` (8172b3a8b8fe57ad9cc41a03646b0947) and `playio` (ffde3a7a000b5b2198961b3fff400acd) as active projects for this Lambda.
- Classification: `no_action` when isolated and Lambda `Errors == 0`. The log is a handled data-quality validation, not a service fault.
- Frequency observed: 30d 6 ALARM / 7d 5 / 1d 1 / 10m 1 — sporadic, not daily recurring. On 2026-05-15 a large Aurora reader-replica conflict spike (6316 ERROR logs) produced a distinct signature and should be triaged separately under the `canceling statement due to conflict with recovery` pattern.
- Action target: locate the exact source in `packages/` or a bundled dependency that emits this ERROR, then downgrade to `WARN` and log only `projectId` / count. Until the exact source file is found, the next lookup target is a full-text search across the Lambda artifact build output or a dependency audit for `notiflyUserId` validation.
