# Scheduled Batch Delivery Push-Notification FCM Send Failure

Sessions: 2026-05-15 (delivery count deployment, BatchCompletion send failures)

## Alarm patterns

- `ScheduledBatchDelivery-P1-BatchFailure` or any `Notifly/ScheduledBatchDelivery` `BatchCompletion` alarm with `outcome=error`, `channel=push-notification`
- Metric namespace: `Notifly/ScheduledBatchDelivery`
- Metric name: `BatchCompletion` (or `FCMSendBatch` with `outcome=error`)
- Dimensions: `outcome=error`, `channel=push-notification`
- `AWS/Lambda Errors` is typically **zero** because failures are handled inside the catch block of `sendFCMMessage`; the Lambda invocation itself succeeds.

## Root cause family

`services/lambda/scheduled-batch-delivery/lib/send_push_v1_api.js` → `sendFCMMessage` catches an Axios/network error before an HTTP response is received. The error has no `response.status`, so `errorCode` becomes `undefined`, which the caller aggregates as `error_codes: "{\"unknown\":1}"`.

### What `"unknown":1` means

In `sendFCMMessage`:

```js
catch (error) {
    // ...
    return {
        error: error?.response?.data?.error ? error?.response?.data?.error : 'Unknown error',
        errorCode: error?.response?.status?.toString(), // undefined when no response received
    };
}
```

When `error.response` is absent (network error, DNS failure, connection reset, timeout before response headers), `errorCode` is `undefined`. The caller aggregates it as:

```js
const code = log.response_body?.errorCode || 'unknown';
```

Result: `error_codes: "{\"unknown\":1}"` (or higher count if multiple recipients fail).

### Why ERROR-level logs are absent

`sendFCMMessage` treats network/timeout errors as **suppressible**:

```js
const SUPPRESSIBLE_RESPONSE_MESSAGES = ['ETIMEDOUT', 'ECONNRESET', 'timeout', 'socket hang up'];
const isSuppressible = SUPPRESSIBLE_RESPONSE_CODES.includes(error.response?.status) ||
    SUPPRESSIBLE_RESPONSE_MESSAGES.some((suppressible) => `${message}`.includes(suppressible));
if (!isAxiosError || !isSuppressible) {
    console.error('Error sending FCM message:', message);
}
```

Network errors are `isAxiosError=true` and match `SUPPRESSIBLE_RESPONSE_MESSAGES`, so `console.error` is **not** called. The only trace is the INFO-level EMF metric line.

## Bounded trace (Logs Insights on `/aws/lambda/scheduled-batch-delivery`)

Because EMF metrics are tab-delimited `INFO` lines with JSON payloads, CloudWatch `filter-log-events` cannot reliably match JSON fields. Use Logs Insights with `parse`.

### 1. Find `FCMSendBatch` error details

```sql
fields @timestamp, @message
| parse @message /^[^\t]*\t[^\t]*\t[^\t]*\t(?<payload>.*)$/
| filter strcontains(payload, '"FCMSendBatch"')
  and strcontains(payload, '"outcome":"error"')
| limit 50
```

Fields to extract from `payload` JSON:
- `fcm_project_id` — the Firebase project slug (e.g., `cosmo-6edb5`, `teuida-beta`)
- `error_codes` — JSON string like `"{\"unknown\":1}"`
- `error_message` — present only for auth failures, absent for network errors
- `project_id`, `campaign_id`, `success_count`, `error_count`

### 2. Find `BatchCompletion` error overview

```sql
fields @timestamp, @message
| parse @message /^[^\t]*\t[^\t]*\t[^\t]*\t(?<payload>.*)$/
| filter strcontains(payload, '"BatchCompletion"')
  and strcontains(payload, '"outcome":"error"')
| limit 50
```

Fields to extract:
- `project_id`, `campaign_id`
- `processing_time_ms`
- `recipient_input_count`, `recipient_passed_count`, `recipient_filtered_count`
- `skip_reason` if present ( distinguishes policy-filtered from send-failed )

### 3. Check for auth failures (different root cause)

```sql
fields @timestamp, @message
| filter @message like 'Failed to get access token'
   or @message like 'Missing FCM project ID'
| limit 20
```

If results appear, the issue is Google API auth (likely service account decoding or token renewal), not network-level FCM.

## Deployment correlation as a primary signal

When helper logs are empty for an EMF metric alarm, check the consumer Lambda's `LastModified` timestamp **first**:

```bash
aws lambda get-function-configuration \
  --function-name scheduled-batch-delivery \
  --region ap-northeast-2 \
  --query '{lastModified:LastModified, handler:Handler}'
```

If `LastModified` falls within minutes of the alarm onset and metric history shows zero errors before that time, treat the deployment as the primary suspect. Before deep log analysis:
1. Confirm with the deploying engineer what branch/commit was deployed.
2. Check if the deployed code changed the return contract of functions called by the handler (e.g., `sendPushV1ApiAndLogResult` returning an object instead of a boolean).
3. If a rollback is available, strongly consider it while root-causing.

## Fast-path classification

- **`no_action`**: Single transient burst that recovers within 1–2 metric periods, `AWS/Lambda Errors=0`, no DLQ growth, and the same projects show `success` in subsequent windows.
- **`needs_fix`**: Persistent or increasing error counts across multiple 5-minute windows, `error_codes: {"unknown":N}` sustained, or clear deployment correlation with ongoing failures across many projects/campaigns.
- **`urgent`**: Lambda `Errors>0`, DLQ growing rapidly, or total delivery failure (success_count=0 for sustained periods).

## Common project/product mappings (ap-northeast-2)

| project_id | product | slug hint |
|---|---|---|
| `02a3660e1b675689a0757409e5c1efaa` | cosmo | `cosmo-6edb5` |
| `7cb3fac7c49e5b84913f89bf8bd54d2d` | teuida-v2 | `teuida-beta` |
| `68cb6fa961d3531699620f505c466b0b` | datepop | `seouldatepop` |
| `e7239ea653e251ed8b0ae4aff9d9d859` | fint | `fint-dev-78763` |
| `91a042a79e4c5c4fa3af7c3d3b5aaf53` | doctornow | `baedalyakgook` |

## Verification after fix

1. `Notifly/ScheduledBatchDelivery BatchCompletion {channel=push-notification, outcome=error}` should drop to zero across consecutive 5-minute periods.
2. `FCMSendBatch {channel=push-notification, outcome=error}` should drop to zero.
3. Lambda `Errors` should remain zero.
4. SQS push queue `ApproximateNumberOfMessagesVisible` and DLQ should not grow.
