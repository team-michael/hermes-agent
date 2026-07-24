# Lambda ConsoleErrors False Positive: SQS Payload Base64 / URL Parameter ERROR Match

## Pattern

Alarm: `kakao-brand-message-delivery lambda error` (ConsoleErrors namespace)
Metric filter: `%ERROR|Status: timeout%`

The broad `%ERROR%` pattern matches the literal string `ERROR` embedded in:
1. **SQS `receiptHandle` base64 strings**: e.g., `...JdiNERROR...` — CloudWatch Logs metric
   filters evaluate the raw log line text, and Lambda logs `Received event:` which contains the
   full SQS record including `receiptHandle`. Base64 encoded strings occasionally contain the
   substring `ERROR` purely by chance.
2. **Message content URL parameters**: e.g., `imageLink` or `imageUrl` containing
   `referral_code=ERROR9T9U6` — query parameters in user-provided campaign content.

In both cases, Lambda `Errors=0`, `Throttles=0`, `BatchCompletion outcome=error=0`,
`KakaoApiSend success_count=10 / failure_count=0`. No delivery failure.

## Classification

`needs_fix` — structural false positive because the metric filter is too broad.
Lambda is healthy but the alarm fires when `ERROR` appears in the logged SQS payload body.

## Detection

1. Check `AWS/Lambda Errors` metric → Sum=0 confirms no runtime failure.
2. Run `filter_log_events` with `filterPattern='%ERROR%'` on the alarm window.
3. In returned events, locate `ERROR` position in the message: `msg.find('ERROR')`.
4. If found inside `receiptHandle` base64 or a URL query parameter value, it's this pattern.

```python
import re
pos = msg.find('ERROR')
context = msg[max(0,pos-50):pos+100]
# Look for: receiptHandle...ERROR or referral_code=ERROR or similar
```

## Fix

Terraform `infra/terraform/prod/ap-northeast-2/lambda/functions.tf` L3029:

```hcl
# Current (too broad):
"filter_pattern" = "%ERROR|Status: timeout%"

# Proposed (Lambda log level tab-delimiter aware):
"filter_pattern" = "%\tERROR\t%|Status: timeout%"
```

Lambda structured logs use tab-delimited format:
`<timestamp>\t<requestId>\tERROR\t<message>`

Matching on `\tERROR\t` (tab before and after) avoids false matches inside SQS payload content,
URL parameters, and other data fields that happen to contain the string `ERROR`.

## Duration P99 Spike Context

When `kakao-brand-message-delivery` processes many `scheduled_once` campaigns simultaneously
(e.g., moyo batch at ~08:30 KST), Duration p99 can spike from ~100ms to ~6,000ms+.
This is expected — each Lambda invocation processes BatchSize=10 SQS records serially
(per-record Kakao API call ~130-260ms each × 10 = ~1.5s per batch, ×5 batches ≈ 7-8s).
This is NOT a timeout or error; `BatchCompletion outcome=success` confirms normal completion.

## Related

- `references/lambda-consoleerrors-handled-business-rejection.md`
- `references/lambda-consoleerrors-metric-filter-false-positive.md`
