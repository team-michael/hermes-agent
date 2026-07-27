# cafe24-worker rate-limit auto delay requeue

Use this reference when `cafe24-worker-queue-dlq` fills because one Cafe24 mall repeatedly returns HTTP 429 / `Too Many Requests`.

## Problem shape

- `cafe24-worker` consumes `cafe24-worker-queue` with `ReportBatchItemFailures`.
- Cafe24 429 raises `Cafe24RateLimitError`.
- The handler currently treats rate-limit records as SQS failures, so SQS receive count advances.
- With concurrent Lambda workers, many messages for the same `mall_id` can re-hit Cafe24 during or immediately after the Redis backoff window, extending the block and eventually pushing messages into DLQ.
- `AWS/Lambda Errors=0` is expected and does **not** mean the queue is healthy.

## Desired behavior

Model Cafe24 429 as **delayed work**, not as a failed message.

On `Cafe24RateLimitError`:
1. Compute a safe delay from the maximum of:
   - `reason.retryAfterMs`
   - Redis `getBackoffRemainingMs(mallId)`
   - Cafe24 minimum block window, normally `600_000ms`
2. Clamp to SQS `DelaySeconds <= 900` and add small jitter.
3. Send the original message body back to `cafe24-worker-queue` with `DelaySeconds`.
4. Add/advance retry metadata in the body or message attributes:
   - `rate_limit_retry_count`
   - `first_rate_limited_at`
   - `last_rate_limited_at`
5. If send succeeds, do **not** include the original message in `batchItemFailures`; let Lambda delete it.
6. If send fails, include it in `batchItemFailures` so the existing SQS retry path remains the safety net.
7. If retry metadata exceeds the guardrail, e.g. `rate_limit_retry_count >= 24` or age > 6h, stop self-requeueing and let it DLQ for operator review.

## Implementation targets

- `services/lambda/cafe24-worker/index.js`
  - carry parsed body alongside each task
  - on `Cafe24RateLimitError`, delayed self-requeue instead of immediate `batchItemFailures`
- `services/lambda/cafe24-worker/lib/api/index.js`
  - ensure `Cafe24RateLimitError.retryAfterMs` reflects the effective Redis/Cafe24 backoff, not only a short fallback header value
- `services/lambda/cafe24-worker/lib/redis-rate-limiter.js`
  - reuse `getBackoffRemainingMs(mallId)` for delay calculation
- `services/lambda/cafe24-worker/package.json`
  - add `@aws-sdk/client-sqs` if direct SQS send is implemented in this lambda
- `infra/terraform/prod/ap-northeast-2/lambda/functions.tf`
  - add `CAFE24_WORKER_QUEUE_URL` env var if the queue URL is not already available
  - IAM already has broad `sqs:SendMessage` in `cafe24-worker-inline` in the observed prod inventory, but verify before PR

## Minimal implementation pattern proven in repo

A minimal change does not need queue/FIFO/EventBridge/Terraform restructuring:

- In `index.js`, store `{ messageId, record, body, promise }` for each parsed SQS record.
- Derive the source `QueueUrl` from `record.eventSourceARN` (`arn:aws:sqs:<region>:<account>:<queue>` → `https://sqs.<region>.amazonaws.com/<account>/<queue>`) and optionally let `CAFE24_WORKER_QUEUE_URL` override it.
- On `Cafe24RateLimitError`, call `getBackoffRemainingMs(reason.mallId || body.mall_id)`, compute `DelaySeconds = min(900, max(reason.retryAfterMs, redisBackoffMs, 600_000) / 1000 + jitter)`, then `SendMessageCommand` the original body plus retry metadata.
- If `SendMessageCommand` succeeds, `continue` without adding the original message to `batchItemFailures`.
- If SQS send fails, or `rate_limit_retry_count >= 24`, fall back to `batchItemFailures` so the existing DLQ path remains the safety valve.
- Add `@aws-sdk/client-sqs` to `services/lambda/cafe24-worker/package.json`; the workspace lock entry should be under the `services/lambda/cafe24-worker` importer dependencies, not devDependencies.

## Sketch

```js
if (reason?.name === 'Cafe24RateLimitError') {
  const redisBackoffMs = await getBackoffRemainingMs(reason.mallId);
  const delaySeconds = Math.min(
    900,
    Math.max(
      1,
      Math.ceil(Math.max(reason.retryAfterMs || 0, redisBackoffMs, 600_000) / 1000) + jitterSeconds()
    )
  );

  const nextBody = {
    ...originalBody,
    rate_limit_retry_count: (originalBody.rate_limit_retry_count || 0) + 1,
    first_rate_limited_at: originalBody.first_rate_limited_at || new Date().toISOString(),
    last_rate_limited_at: new Date().toISOString(),
  };

  await sqs.send(new SendMessageCommand({
    QueueUrl: process.env.CAFE24_WORKER_QUEUE_URL,
    MessageBody: JSON.stringify(nextBody),
    DelaySeconds: delaySeconds,
  }));

  // Requeue succeeded: omit original message from batchItemFailures.
  continue;
}
```

## Why this is better than automatic DLQ redrive

Automatic DLQ redrive is late: the message has already exhausted its retry budget and paged operators. Delayed self-requeue keeps rate-limit work in the normal queue path and reserves DLQ for long-lived external outages, malformed data, or code bugs.

## Verification

- Unit test `index.js`: `Cafe24RateLimitError` triggers `SendMessageCommand` with `DelaySeconds`, and the original message is omitted from `batchItemFailures` when send succeeds.
- Unit test failure path: if SQS send fails, the message remains in `batchItemFailures`.
- Unit test guardrail: excessive `rate_limit_retry_count` does not self-requeue.
- Unit test metadata path: existing `first_rate_limited_at` is preserved while `rate_limit_retry_count` and `last_rate_limited_at` advance.
- Run `pnpm exec prettier --check services/lambda/cafe24-worker/index.js services/lambda/cafe24-worker/test/index.spec.js services/lambda/cafe24-worker/package.json`.
- Run `pnpm --filter cafe24-worker lint`; known pre-existing warnings may exist in unrelated cafe24-worker files, but new files should not add errors.
- For full `services/lambda/cafe24-worker` Jest from the lambda directory, build workspace package dependencies first if their `dist/` outputs are absent: `@notifly/types`, `@notifly/util`, `@notifly/liquidjs`, `@notifly/common`, `@notifly/cipher`, `@notifly/userdb`.
- Live check after deploy: `Backoff set for <mallId>` may occur, but `cafe24-worker-queue-dlq ApproximateNumberOfMessagesVisible` should stay 0 while source queue drains after delay.
