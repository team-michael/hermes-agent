# Notifly SQS DLQ vs Redis warning triage

Use when a Notifly delivery queue DLQ alarm appears near Redis timeout warnings and the task is to determine whether a Redis/client change caused message loss.

## Core separation

Do not infer causality from temporal proximity alone. Split the investigation into three planes:

1. **DLQ plane** — SQS alarm, main queue/DLQ metrics, sampled DLQ metadata, Lambda event-source mapping.
2. **Lambda execution plane** — `Errors`, `Throttles`, `Duration`, `ConcurrentExecutions`, REPORT logs, timeout/runtime-error logs.
3. **Redis warning plane** — exact warning strings, callsite/profile if available, and whether warning is in a fatal path or a best-effort cache/counter path.

## Practical probes

### Queue and event-source mapping

- Read event-source mapping for the consumer Lambda:
  - `BatchSize`
  - `ScalingConfig.MaximumConcurrency`
  - `FunctionResponseTypes`
- Read main queue attributes:
  - `VisibilityTimeout`
  - `RedrivePolicy.maxReceiveCount`
  - current visible/not-visible/delayed counts
- Read DLQ current visible count and alarm history.

Important interpretation:

- `maxReceiveCount=1` is very sensitive. One receive that is not successfully deleted can push a message to DLQ on the next receive cycle.
- If Lambda code returns `{ batchItemFailures }` but the event-source mapping lacks `FunctionResponseTypes=['ReportBatchItemFailures']`, partial batch retry is not actually enabled.

### DLQ sampling

Sample only a few DLQ messages, with tiny visibility timeout, and summarize safe fields:

- `MessageId`
- `SentTimestamp`
- `ApproximateFirstReceiveTimestamp`
- `ApproximateReceiveCount`
- `project_id`
- `campaign_id`
- `delivery_type`
- `platform`
- recipient count
- body key shape, not full payload

Avoid dumping tokens, service accounts, recipient payloads, or full message bodies.

### Metric correlation

Pull minute-level SQS metrics around the alarm:

- main queue: `NumberOfMessagesSent`, `NumberOfMessagesReceived`, `NumberOfMessagesDeleted`, `ApproximateNumberOfMessagesNotVisible`, `ApproximateAgeOfOldestMessage`
- DLQ: `ApproximateNumberOfMessagesVisible`, `ApproximateAgeOfOldestMessage`

Look for:

- top-of-hour or campaign fan-out burst
- consumer concurrency saturation
- main queue age growth followed by DLQ visibility after approximately the queue `VisibilityTimeout`

Pull Lambda metrics for the same window:

- `Invocations`
- `Errors`
- `Throttles`
- `Duration` Average/Maximum
- `ConcurrentExecutions`

If `Errors=0`, `Throttles=0`, no `Task timed out`, and durations are far below Lambda timeout, treat DLQ as likely delete/retry/processing-shape issue, not a Lambda crash.

### Redis correlation

Query exact Redis warning strings separately:

- `Can't get value from redis`
- `Can't set value to redis`
- `Redis connection timed out`
- `Command timed out`
- `Failed to increment campaign delivery counts`
- `Failed to set campaign delivery published`
- `Failed to set campaign delivery status`
- `[redis] client event`

Then classify:

- Generic `Can't get/set value from redis` in delivery-policy cache paths usually means bounded cache read/write fallback, not necessarily message loss.
- `Failed to increment campaign delivery counts` / `Failed to set campaign delivery ...` is the delivery-monitor counter path and should be treated differently.
- In Lambda prod, verify whether `REDIS_PROXY_HOST` is set. Cloudflare preview Redis-proxy findings do not automatically apply to Lambda if only `REDIS_HOST` is configured.

Check historical daily counts for the same Redis warnings over 14–30 days. If similar or larger counts existed before the candidate deploy, report it as residual/known warning rather than a new regression.

## Result phrasing

A good conclusion separates:

- **DLQ is a real problem?** yes/no/current count.
- **Redis warnings are real?** yes/no/count/callsite class.
- **Did Redis cause DLQ?** supported/unsupported, with timing and fatal-path evidence.

Example phrasing:

> DLQ messages are real and need follow-up, but current evidence does not support Redis timeout as the direct cause. The DLQ messages are event-based push records, the Redis warnings are bounded cache get/set timeouts, no Lambda errors/timeouts were observed, and the DLQ timing matches queue burst + visibility timeout rather than Redis warning timestamps.

## Remediation suggestions

- Do not redrive blindly; first check delivery result/message event tables for duplicate-send risk.
- Consider increasing `maxReceiveCount` from `1` to a safer value such as `3–5`, depending on idempotency and duplicate-delivery tolerance.
- If code returns `batchItemFailures`, enable `ReportBatchItemFailures` on the event-source mapping or remove the misleading return path.
- Improve Redis warning logs with profile/key-class/callsite so cache read, forbidden-timing lookup, and delivery-monitor counter writes are separable in CloudWatch.
