# ScheduledBatchDelivery DbInsert `invalid input syntax for type json`

Three Lambda functions share this failure pattern. Determine which one is firing before choosing a fix target.

| Lambda | Channel | Primary source file | Known broken function |
|--------|---------|---------------------|----------------------|
| `scheduled-batch-delivery` | push-notification | `services/lambda/scheduled-batch-delivery/lib/push_utils.js` | `toSendFailureLog` (`sender_info`, `request_body`, `response_body`) |
| `scheduled-batch-text-message-delivery` | SMS/LMS | `services/lambda/scheduled-batch-text-message-delivery/lib/nhncloud/send_text_message.js` | `prepareSendResultsToInsertForNHNCloud` (`extra_data`) |
| `kakao-delivery-result-poller` | Kakao brand message | `services/lambda/kakao-delivery-result-poller/repository/delivery_result_repository.ts:132` | `buildDeliveryFailureLogInsertQuery` — `raw_request_body` SQL string interpolation with double-escaped URL encoding |

## Alarm patterns

A. **EMF metric alarm**
- `ScheduledBatchDelivery-P2-DbError` (or any `Notifly/ScheduledBatchDelivery` alarm with `DbInsert` metric, `outcome=error`)
- Metric namespace: `Notifly/ScheduledBatchDelivery`
- Metric name: `DbInsert`
- Dimensions: `channel=push-notification`, `outcome=error`, `table=delivery_result` or `delivery_failure_log`
- No CloudWatch metric filter exists because this is an EMF custom metric, not a log-derived metric filter alarm.

B. **ConsoleErrors metric-filter alarm**
- Alarm name: `scheduled-batch-delivery lambda error`
- Namespace: `ConsoleErrors`
- Metric filter: `%ERROR|Status: timeout%`
- Log group: `/aws/lambda/scheduled-batch-delivery`
- This catches the same `invalid input syntax for type json` ERROR logs, but the alarm is coarser and also matches unrelated timeout or generic ERROR lines.

## Lambda log location

- Push delivery: `/aws/lambda/scheduled-batch-delivery`
- Text delivery: `/aws/lambda/scheduled-batch-text-message-delivery`

Look for ERROR lines in the alarm-window stream around the metric datapoint timestamp:
```
invalid input syntax for type json
Query: INSERT INTO delivery_result_<project_id> (... extra_data) VALUES ...
```

For the push-notification path, the concrete log often shows `[object Object]` directly in the VALUES list:
```
Values: <uuid>,[object Object],<notifly_user_id>,58YS4P,[object Object],[object Object],push-notification
```

## Root cause — Kakao brand message path (`kakao-delivery-result-poller`)

`services/lambda/kakao-delivery-result-poller/repository/delivery_result_repository.ts:132`

`buildDeliveryFailureLogInsertQuery` builds the INSERT via SQL string interpolation:
```ts
`('${escapeForSql(row.id)}', '${escapeForSql(row.notifly_user_id ?? '')}', '${escapeForSql(row.campaign_id)}', '${escapeForSql(row.subtype ?? '')}', '${escapeForSql(row.extra_data?.raw_request_body ?? JSON.stringify({}))}', '${escapeForSql(JSON.stringify(row.extra_data))}', '${escapeForSql(row.channel)}', '${escapeForSql(JSON.stringify({ platform: row.sender_platform }))}')`
```

The `request_body` column receives `row.extra_data?.raw_request_body`, which is itself an already-stringified JSON with double-escaped URL encoding. When the string contains Korean characters in URL parameters (e.g., `utm_content=미국주식`) embedded in the double-escaped `button_variable.appUrl` / `button_variable.webUrl`, the result after `escapeForSql` produces a PostgreSQL JSON that is structurally invalid.

The `Params: undefined` / `Values: undefined` suffix in the error log confirms the pg driver's parameterized query also fails — the raw_request_body value cannot be bound to the `json` column.

**Log evidence (2026-06-19):**
```
ERROR  invalid input syntax for type json
Query: INSERT INTO delivery_failure_log_b2b4a8f879a75673b755bff42fc1deb6 (...) VALUES
  ('...', '...', 'Y1tuTv', 'IMAGE',
   '{"message_variable":{"article_summary":"...스페이스X..."},
     "button_variable":{"appUrl":"class101.net/...&utm_content=미국주식\\",...}}',
   ...);
Values: undefined
Params: undefined
```

**Primary trigger in this session:** Kakao BZM API error code `3018` (이미지 메시지 변수 오류) means the send already failed at the Kakao API level. The INSERT is for the failure log, not a delivery result — so delivery was already lost before the DB error.

**Classification:** `needs_fix` — double failure: (1) Kakao API rejection for the campaign `Y1tuTv` (campaign content/variable configuration issue), (2) failure log INSERT broken (no record of failure preserved).

**Fix target:** `repository/delivery_result_repository.ts:132` — use parameterized queries or sanitize `raw_request_body` with `JSON.parse` → `JSON.stringify` to normalize the double-escaping before insertion. Alternatively, truncate or strip the URL string to ASCII before binding.

---

## Root cause — push-notification path (`scheduled-batch-delivery`)

`services/lambda/scheduled-batch-delivery/lib/push_utils.js`

`toSendFailureLog` returns **three** object fields without `JSON.stringify`:
```js
function toSendFailureLog(error, errorCode, fcmServerKey, fcmServiceAccount, notiflyUserId, campaignId, requestPayload) {
    return {
        id: notiflyMessageId ?? v4().replace(/-/g, ''),
        sender_info: {
            fcm_server_key: fcmServerKey,
            fcm_service_account: fcmServiceAccount ?? undefined,
        },
        notifly_user_id: notiflyUserId,
        campaign_id: campaignId,
        request_body: requestPayload,
        response_body: { error, errorCode },
        channel: PUSH_NOTIFICATION_CHANNEL,
    };
}
```

- `toSendResult` **does** stringify `payload` (`JSON.stringify(payload, null, 2)`), but `toSendFailureLog` does not stringify any of its object fields.

`services/lambda/scheduled-batch-delivery/lib/db.js`
`insertFailureDetailLogs` flat-maps these raw objects directly into a parameterized query:
```js
const values = failureLogs
    .flatMap((log) => [
        log.id,
        log.sender_info,     // plain object → [object Object]
        log.notifly_user_id,
        extractCampaignId(log.campaign_id),
        log.request_body,    // plain object → [object Object]
        log.response_body,   // plain object → [object Object]
        log.channel,
    ])
    .map(toValue);
```

Columns `sender_info`, `request_body`, and `response_body` are typed `json`. PostgreSQL receives `[object Object]` and rejects it with `22P02`.

Concrete log evidence:
```
Values: e3289e81b5644ff5b7aa3e26b3cabe8e,[object Object],716589cdbad35bfeb3c5ff1f68666423,58YS4P,[object Object],[object Object],push-notification
```

A single alarm window can show **dozens** of these errors (e.g., 37 in 30 minutes).

The project (`02a3660e1b675689a0757409e5c1efaa` → product `cosmo`) and campaign (`58YS4P`) pair appears consistently in the Lambda EMF metric context and the raw VALUES line.

## Root cause — text-message path (`scheduled-batch-text-message-delivery`)

`services/lambda/scheduled-batch-text-message-delivery/lib/nhncloud/send_text_message.js`
function `prepareSendResultsToInsertForNHNCloud` returns `extra_data` as a plain JS object:

```js
extra_data: {
    requestId,
    recipientSeq: index,
    content: { templateId, templateParameter: ... },
    resultCode: sendResult?.resultCode,
    resultMessage: sendResult?.resultMessage,
    resultMessageKR: ...,
},
```

`services/lambda/scheduled-batch-text-message-delivery/lib/db.js`
function `insertDeliveryMessageRows` passes this object via `toValue(row.extra_data)` to a parameterized PostgreSQL query where the column type is `json`. PostgreSQL rejects the raw `[object Object]`.

Same bug affects `delivery_failure_log` INSERT in `_getQueryForSendFailureLogs`:
- `request_body` and `response_body` can contain `[object Object]` when the sender info / response is not stringified.
- `_getQueryForSendFailureLogs` builds raw SQL strings (not parameterized), so any unescaped special characters also risk SQL injection, but the immediate failure mode is `invalid input syntax for type json`.

## Surrogate pair failure mode

Even when `JSON.stringify` is present (e.g., `prepareSendFailureLogToInsert` stringifies `request_body`/`response_body`), PostgreSQL may still reject the JSON with:

```
code: '22P02',
detail: 'Unicode low surrogate must follow a high surrogate.',
where: 'JSON data, line 1: ... 우산 꼭 챙기구~ 잘자~ 사랑해\\ud83e....'
```

This happens when the source string contains emoji (U+1F600+) and the UTF-16 surrogate pair (`\ud83e\udd...`) is split or truncated during message personalization, substring operations, or transport. The `where` field in the pg error object reveals the exact broken character sequence and the table/column. In the example above, an emoji in a personalized LMS message caused the `delivery_failure_log` INSERT to fail.

The `delivery_result` INSERT can fail for the same reason when `extra_data.resultMessage` or `extra_data.content.templateParameter` contains emoji and `JSON.stringify` is missing (raw object → `[object Object]` is the first failure), or when `JSON.stringify` is applied to a string whose surrogate pair is already split.

When triaging, do not stop at "invalid input syntax for type json." Inspect the pg error object's `detail` and `where` fields in Lambda logs to distinguish:
1. `[object Object]` / missing `JSON.stringify`
2. Broken surrogate pair in an already-stringified JSON string

For (2), the fix may need to be upstream in message personalization or payload sanitization, not only in the DB insert layer.

### Campaign-level recurrence pattern

When `ScheduledBatchDelivery-P2-DbError` fires and the 30-day alarm history shows a prior occurrence, cross-check whether the `campaign_id` is identical.

Bounded command to extract the campaign ID from a prior alarm window:
```bash
aws logs filter-log-events \
  --region ap-northeast-2 \
  --log-group-name /aws/lambda/scheduled-batch-delivery \
  --start-time <prior_epoch_ms> --end-time <prior_epoch_ms + 3600000> \
  --filter-pattern 'invalid input syntax for type json' \
  --limit 1 --output text --query 'events[0].message' \
  | grep -oP '"campaign_id":\s*"\K[^"]+' | head -1
```

If the same `campaign_id` appears in both the current and prior alarm, the failure is likely a **persistently broken message template** for that campaign (e.g., a LiquidJS personalization expression that truncates a multi-byte emoji, producing a lone UTF-16 surrogate). In this case the fix should include inspecting the campaign message template in the Notifly console, not only the Lambda JSON-stringify layer.

Concrete example (2026-06-13, cosmo/58YS4P):
```
notification.body: "나는 간다아ㅏ 오늘도 수고했구 요즘에 조금 바빴어서ㅓ 연락을 많이 못했는데~ 또 올게ㅔ!!!! 사랑해 잘자\ud83e..."
```
The `\ud83e` is a lone high surrogate (the first half of a surrogate pair for an emoji such as 🫶 or 🫠). PostgreSQL rejects the JSON because the string is not valid UTF-8.

> **Pitfall — enormous `filter-log-events` output**: The Lambda ERROR log line for this alarm includes the full multi-row `VALUES` list for the parameterized INSERT query. A single event can be 100+ KB. Use `--limit 1` and pipe through `head`/`grep` to avoid flooding the terminal.

When this pattern is observed, also check `AWS/Lambda Errors == 0` to confirm the Lambda invocation itself is healthy and the failure is purely a DB serialization issue.

The Lambda log EMF metrics include `project_id` and `campaign_id` fields in the same log line as the ERROR, e.g.:
```json
{"project_id":"02a3660e1b675689a0757409e5c1efaa","campaign_id":"58YS4P", ...}
```
Map `project_id` via DynamoDB `project` table for product name.

## Send failure root-cause tracing via FCMSendBatch EMF metric

When `delivery_failure_log` INSERT fails with `[object Object]`, the original FCM send failure reason is lost from the DB. However, the Lambda EMF metric `FCMSendBatch` still records it.

**Key fields in the EMF line:**
- `outcome`: `"success"` or `"error"`
- `success_count`: number of `send_success` rows
- `error_count`: number of `send_failure` rows
- `error_codes`: JSON-stringified map of `{<statusCode>: <count>}`, e.g. `"{\"404\":1}"` or `"{\"403\":1}"`
- `campaign_id`, `project_id`, `fcm_project_id`

**Bounded CloudWatch Logs query:**
```bash
aws logs filter-log-events \
  --log-group-name /aws/lambda/scheduled-batch-delivery \
  --start-time <epoch_ms> --end-time <epoch_ms> \
  --filter-pattern '"FCMSendBatch" "<campaign_id>"' \
  --limit 50
```

Then parse the 4th tab-separated field (JSON payload) for `outcome`, `error_count`, and `error_codes`.

**Common FCM error codes seen in this alarm:**
- `404` — unregistered / invalid device token. Normal operational churn (app deleted, token refresh).
- `403` — authentication failure (`fcm_service_account` misconfiguration, sender ID mismatch).

> Pitfall: `FCMSendBatch outcome:success` with `error_count:0` does **not** mean no `toSendFailureLog` objects exist. If the metric line shows `error_count:0` but the alarm still fires on `delivery_failure_log`, inspect the exact batch timing — multiple campaigns run in the same time window and metrics may be interleaved.

## Invocation-level tracing via requestId

Lambda logs follow the format: `ISO_TIMESTAMP\tREQUEST_ID\tLEVEL\tMESSAGE`.

To trace a single invocation that produced the `invalid input syntax for type json` error:
1. Extract `REQUEST_ID` from the ERROR line.
2. Search the same log stream (or the whole log group, bounded to ±5 min) with `filterPattern='"<requestId>"'`.
3. Look for:
   - `START RequestId: ...`
   - `FCMSendBatch` EMF metric (success or error)
   - `DbInsert` / `DbRecordCount` EMF metric with `outcome=error`
   - `END RequestId: ...`

This reconstructs whether the invocation succeeded at FCM but failed at DB insert, or failed at both layers.

## Circular reference pitfall when fixing

Naively adding `JSON.stringify` to all three fields in `toSendFailureLog` introduces a new risk: `response_body.error` is often an **Error instance** (or Axios error with `.request`/`.response` circular refs), not a plain string.

```js
response_body: { error, errorCode }
```

If `error` is an Axios / HTTP client error, `JSON.stringify({ error, errorCode })` throws:
```
TypeError: Converting circular structure to JSON
```

Safe fix pattern — sanitize `error` to a serializable plain object before stringifying:
```js
function safeJsonStringify(obj) {
    try {
        return JSON.stringify(obj);
    } catch (e) {
        return JSON.stringify({ error: 'unserializable', message: e.message });
    }
}

function toSendFailureLog(...) {
    return {
        ...
        sender_info: safeJsonStringify({ fcm_server_key: fcmServerKey, fcm_service_account: fcmServiceAccount ?? undefined }),
        request_body: safeJsonStringify(requestPayload),
        response_body: safeJsonStringify({ error: error?.message ?? error, errorCode }),
        ...
    };
}
```

Or, fix at the DB insertion layer (`db.js`) by stringifying right before binding, so `push_utils.js` callers do not need to know column types:
```js
log.sender_info != null ? JSON.stringify(log.sender_info) : null,
log.request_body != null ? JSON.stringify(log.request_body) : null,
log.response_body != null ? JSON.stringify(log.response_body) : null,
```

Prefer the DB-layer fix when `push_utils.js` is also consumed by other paths that expect the original object shape.

If the fix still fails after adding `JSON.stringify`, inspect the pg error `detail`/`where` fields again — it may have shifted from `[object Object]` to a **broken surrogate pair** (see section below).

## Impact

- `delivery_result` row insert fails, so delivery history is missing in the DB for the affected channel (push-notification or SMS/LMS).
- `delivery_failure_log` also fails, so failure reason tracking is lost.
- For the **push-notification** path: the FCM API call may still have succeeded; this is a data-loss/observability gap, not necessarily a delivery gap.
- For the **text-message** path: the SMS/LMS API call to NHNCloud may still have succeeded; same data-loss/observability gap.
- If both `delivery_result` and `delivery_failure_log` fail for the same batch, there is **zero DB trace** of that delivery attempt, which breaks analytics, campaign statistics, and downstream retry logic.

## Fix target

### Push-notification path
1. `services/lambda/scheduled-batch-delivery/lib/push_utils.js`
   - `toSendFailureLog`: stringify `sender_info`, `request_body`, and `response_body` before returning. Prefer extracting `error.message` (not the full Error object) to avoid circular references.
2. `services/lambda/scheduled-batch-delivery/lib/db.js`
   - `insertFailureDetailLogs`: stringify object fields right before binding, or assert they are already strings. This is the safer layer because callers may not know column types.

### Text-message path
1. `services/lambda/scheduled-batch-text-message-delivery/lib/nhncloud/send_text_message.js`
   - `prepareSendResultsToInsertForNHNCloud`: wrap `extra_data` in `JSON.stringify()` before returning.
2. `services/lambda/scheduled-batch-text-message-delivery/lib/db.js`
   - `insertDeliveryMessageRows`: ensure `extra_data` is stringified before binding.
   - `_getQueryForSendFailureLogs`: stop building raw string interpolations for `request_body`/`response_body`; move to parameterized queries and stringify objects before binding.

## Verification after fix

- Watch `Notifly/ScheduledBatchDelivery DbInsert {outcome=error}` metric for the next few scheduled batch runs.
- Confirm no `invalid input syntax for type json` in `/aws/lambda/scheduled-batch-delivery` logs.
- Regression test: assert that `prepareSendResultsToInsertForNHNCloud().extra_data` is a string, or that the DB insert succeeds when `extra_data` contains nested objects.
