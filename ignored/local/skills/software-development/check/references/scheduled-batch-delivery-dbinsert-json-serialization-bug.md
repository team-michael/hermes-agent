# ScheduledBatchDelivery DbInsert `invalid input syntax for type json`

## Alarm pattern

- `ScheduledBatchDelivery-P2-DbError` (or any `Notifly/ScheduledBatchDelivery` alarm with `DbInsert` metric, `outcome=error`)
- Metric namespace: `Notifly/ScheduledBatchDelivery`
- Metric name: `DbInsert`
- Dimensions: `channel=push-notification`, `outcome=error`, `table=delivery_result`
- No CloudWatch metric filter exists because this is an EMF custom metric, not a log-derived metric filter alarm.

## Lambda log location

The actual Lambda function name is `scheduled-batch-delivery`.
Log group: `/aws/lambda/scheduled-batch-delivery`

Look for ERROR lines in the alarm-window stream around the metric datapoint timestamp:
```
invalid input syntax for type json
Query: INSERT INTO delivery_result_<project_id> (... extra_data) VALUES ...
```

## Root cause

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

The Lambda log EMF metrics include `project_id` and `campaign_id` fields in the same log line as the ERROR, e.g.:
```json
{"project_id":"02a3660e1b675689a0757409e5c1efaa","campaign_id":"58YS4P", ...}
```
Map `project_id` via DynamoDB `project` table for product name.

## Impact

- `delivery_result` row insert fails, so SMS/LMS delivery history is missing in the DB.
- `delivery_failure_log` also fails, so failure reason tracking is lost.
- The SMS/LMS API call to NHNCloud may still have succeeded; this is a data-loss/observability gap, not necessarily a delivery gap.

## Fix target

1. `services/lambda/scheduled-batch-text-message-delivery/lib/nhncloud/send_text_message.js`
   - `prepareSendResultsToInsertForNHNCloud`: wrap `extra_data` in `JSON.stringify()` before returning.
2. `services/lambda/scheduled-batch-text-message-delivery/lib/db.js`
   - `insertDeliveryMessageRows`: ensure `extra_data` is stringified before binding. Prefer fixing at the query-build layer so the DB function does not need to know column types.
   - `_getQueryForSendFailureLogs`: stop building raw string interpolations for `request_body`/`response_body`; move to parameterized queries and stringify objects before binding.

## Verification after fix

- Watch `Notifly/ScheduledBatchDelivery DbInsert {outcome=error}` metric for the next few scheduled batch runs.
- Confirm no `invalid input syntax for type json` in `/aws/lambda/scheduled-batch-delivery` logs.
- Regression test: assert that `prepareSendResultsToInsertForNHNCloud().extra_data` is a string, or that the DB insert succeeds when `extra_data` contains nested objects.
