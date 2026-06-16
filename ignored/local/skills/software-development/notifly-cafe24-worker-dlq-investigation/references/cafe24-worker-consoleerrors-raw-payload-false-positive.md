# cafe24-worker ConsoleErrors false positive from raw SQS payload

## Signature

CloudWatch alarm: `cafe24-worker lambda error`

Metric filter on `/aws/lambda/cafe24-worker`:

```text
%ERROR|Status: timeout%
```

Known false-positive payload:

```json
{
  "mallid": "chosunhnb",
  "command": "shippingstatuschanged",
  "params": {
    "eventcode": "shippingstart",
    "memberid": "",
    "extrainfo": [
      { "trackingno": "ERROR:N/A" }
    ]
  }
}
```

The worker logs the entire SQS record before parsing/processing:

```js
console.log(`Received event from SQS: ${JSON.stringify(sqsRecord, null, 2)}`);
```

So the metric filter can match the literal provider payload string `ERROR:N/A` inside an `INFO Received event from SQS` line. This is not necessarily a Lambda runtime error or an application `console.error`.

## Verification checklist

1. Query the alarm and metric filter:
   - namespace `ConsoleErrors`
   - metric name `cafe24-worker lambda error`
   - filter pattern `%ERROR|Status: timeout%`
2. Query `/aws/lambda/cafe24-worker` around the alarm window for:
   - `ERROR:N/A`
   - `Member ID is required to handle order shipping status changed`
   - `will retry via SQS`
   - real `ERROR` prefix / `Status: timeout`
3. Check AWS/Lambda metrics for the same window:
   - `Errors=0`
   - `Throttles=0`
   - short/normal `Duration`
4. Map `mall_id` via DynamoDB `cafe24_integration` → `project`/`products`, but keep interpretation separate from active business usage.

## Interpretation

If matches are only raw `Received event from SQS` payloads containing `trackingno: "ERROR:N/A"`, and Lambda `Errors=0` with no retry logs, classify as **log-derived alarm false positive**.

For `shippingstatuschanged` with empty `memberid`, `handleShippingStatusChanged()` skips because it cannot identify a Notifly user. This can be normal for guest/phone orders and does not imply message delivery/data loss.

## Important nuance: active business project vs live integration

Do not infer "inactive project" from product/business intuition alone. The worker's gate is `cafe24_integration.status === completed`, not whether the product looks active in the console or currently runs campaigns.

Even if a mall is business-inactive, Cafe24 can keep sending webhooks while the Cafe24 app/webhook remains installed. Also, the raw SQS payload is logged before integration status checks, so broad metric filters can still fire from inactive or soon-to-be-skipped events.

## Fix framing

Short-term: no operational action if metrics confirm false positive.

Monitoring/code cleanup options:
- stop logging the full raw SQS record at INFO for cafe24-worker, or redact/summarize provider payload fields;
- narrow the ConsoleErrors metric filter so arbitrary provider payload strings do not page;
- if the mall is truly retired, remove/disable the Cafe24 app/webhook and clean up `cafe24_integration` state through the intended product/offboarding flow.
