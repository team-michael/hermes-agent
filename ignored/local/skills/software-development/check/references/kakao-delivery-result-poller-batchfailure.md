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

## Classification quick guide

| Errors metric | ERROR logs present | Root cause | Status |
|---|---|---|---|
| 0 | Yes, `N_RESEND_ENQUEUE_FAILED` + missing env var | Deployment regression | `needs_fix` |
| 0 | Yes, `KakaoResultApiError` / provider error | Handled provider rejection | `no_action` |
| 0 | No, only `completed_failure` PollAttempts | Batch-level handled failure | `no_action` |
| 0 | Yes, `invalid input syntax for type json` on `delivery_failure_log_*` INSERT with `Params: undefined` | JSON double-escape bug in `delivery_result_repository.ts:132` + upstream Kakao API error | `needs_fix` |
| >0 | Unhandled exception / timeout | Runtime bug | `needs_fix` or `urgent` |
