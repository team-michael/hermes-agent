# SQS receiptHandle Token Containing "ERROR" — Lambda ConsoleErrors False Positive

## Pattern

Lambda functions that log the full raw SQS event payload at `INFO` level
(`Received event: { "Records": [{ "receiptHandle": "AQEBI2ERROR...", ... }] }`)
will trigger coarse `%ERROR|Status: timeout%` metric filters because the base64
`receiptHandle` token incidentally contains the substring `ERROR`.

This is not an application error. The log level is `INFO`, and Lambda runtime
`Errors` and `Throttles` remain 0.

## Observed Instance

- **Alarm:** `scheduled-batch-kakao-alimtalk-delivery lambda error`
- **Date:** 2026-06-19 19:59 KST (10:59 UTC)
- **Project:** doctornow (project_id: `91a042a79e4c5c4fa3af7c3d3b5aaf53`)
- **Campaign:** `api_kakao_alimtalk` (API 알림톡 발송 채널)
- **Trigger log stream:** `2026/06/19/[$LATEST]7af56b8233ae425db1b5a8893f631714`
- **Matching line:** `INFO Received event: { "Records": [{ "receiptHandle": "AQEBI2ERRORCx9fCl0j7...", ... }] }`
- **Lambda Duration:** ~50ms, Memory: 183/512 MB — normal completion
- **Lambda Errors (AWS/Lambda namespace):** 0 across entire alarm window

## Confirmation Steps

```python
# 1. filter_log_events on alarm window with '"ERROR"' pattern
resp = logs.filter_log_events(
    logGroupName='/aws/lambda/scheduled-batch-kakao-alimtalk-delivery',
    startTime=start_ms,
    endTime=end_ms,
    filterPattern='"ERROR"',
    limit=50
)
# If only match is INFO Received event with receiptHandle containing ERROR → false positive

# 2. Cross-check AWS/Lambda Errors
resp = cw.get_metric_statistics(
    Namespace='AWS/Lambda',
    MetricName='Errors',
    Dimensions=[{'Name': 'FunctionName', 'Value': 'scheduled-batch-kakao-alimtalk-delivery'}],
    ...
    Statistics=['Sum']
)
# If Sum=0 across window → confirmed false positive
```

## Scope

`alarm_count_30d: 5` (2026-05-26, 2026-05-28, 2026-06-11, 2026-06-15, 2026-06-19)
— all of these are candidates for the same false-positive pattern, not code regressions.

## Classification

`no_action` — Lambda is healthy. receiptHandle tokens are random base64 strings
that may contain `ERROR` by chance.

## Long-Term Fix Options

1. **Remove `receiptHandle` from the logged event** — log only `messageId`,
   `body`, `eventSource`, and `awsRegion` from each SQS record at INFO level.
   Avoids false positives entirely.

2. **Structured JSON metric filter** — replace `%ERROR|Status: timeout%` with
   `{ $.level = "ERROR" }` (requires the Lambda to emit structured JSON logs
   with a `level` field). This is the durable solution for all Lambda
   ConsoleErrors alarms.

3. **Accept as known noise** — if the alarm fires rarely (≤1/week), document
   and suppress in runbooks.

## Affected Lambdas

Any Lambda that:
- uses SQS as event source
- logs the raw SQS event (including `receiptHandle`) at INFO level on invocation start
- has a `%ERROR|Status: timeout%` or `%ERROR%` metric filter

Confirmed: `scheduled-batch-kakao-alimtalk-delivery`
Likely candidates: other `scheduled-batch-*` Lambdas with the same log-entry pattern
