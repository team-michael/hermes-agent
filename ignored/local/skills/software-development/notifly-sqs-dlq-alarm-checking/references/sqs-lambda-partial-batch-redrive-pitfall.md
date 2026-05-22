# SQS/Lambda DLQ pitfall: `batchItemFailures` can be ignored

Use this reference when investigating Notifly SQS DLQ alarms where Lambda `Errors=0` but messages still move to DLQ.

## Key lesson

Do not assume a Lambda return value like `{ batchItemFailures }` is honored by SQS. For SQS event source mappings, partial batch response semantics require the event source mapping to include `FunctionResponseTypes: ["ReportBatchItemFailures"]`.

If `FunctionResponseTypes` is empty, Lambda can return `{ batchItemFailures }` and still be treated as a normal successful invocation by the Lambda runtime/poller. The field is effectively ignored for SQS deletion/redrive reasoning.

## Investigation pattern

1. Inspect the source queue redrive policy and visibility timeout.
   - `RedrivePolicy.maxReceiveCount`
   - `VisibilityTimeout`
2. Inspect Lambda event source mapping for the queue.
   - `BatchSize`
   - `FunctionResponseTypes`
   - `ScalingConfig.MaximumConcurrency`
3. Check Lambda metrics separately from SQS state.
   - Lambda `Errors=0` means the invocation completed successfully.
   - It does not prove every received SQS message was deleted.
4. Compare source queue SQS metrics over the incident window.
   - `NumberOfMessagesReceived`
   - `NumberOfMessagesDeleted`
   - `ApproximateNumberOfMessagesNotVisible`
   - `ApproximateAgeOfOldestMessage`
   - DLQ `ApproximateNumberOfMessagesVisible`
5. A durable clue is:
   - `sum(NumberOfMessagesReceived) - sum(NumberOfMessagesDeleted) == DLQ increment`
   - source `ApproximateAgeOfOldestMessage` approaches the queue `VisibilityTimeout`
   - DLQ count rises shortly after

This points to messages being received but not deleted before visibility timeout, not necessarily to a Lambda application exception.

## Pitfall from a Notifly scheduled-batch push investigation

A prior thread initially attributed DLQ accumulation to:

- per-message exception inside `scheduled-batch-delivery`
- `batchItemFailures.push(...)`
- `maxReceiveCount=1` moving the failed item immediately to DLQ

Verification showed this was incomplete/wrong because the production event source mapping had `FunctionResponseTypes: []`, so partial batch response was not enabled. The observed evidence instead matched:

```text
SQS message received
  -> remains in-flight for the source queue visibility timeout
  -> not deleted by the poller/consumer path
  -> maxReceiveCount=1 makes the next receive/redrive attempt send it to DLQ
```

A separate Liquid `TokenizationError` was real, but it was caught/logged inside the push send path and the invocation ended normally. Treat such business/template errors as message-send failures only after correlating them with delete/redrive evidence; do not use them as the DLQ root cause by default.

## Reporting guidance

When reporting back, distinguish:

- **application/business failure**: template render error, FCM credential/token failure, policy filtering, etc.
- **Lambda invocation failure**: runtime error, timeout, throttle, unhandled exception
- **SQS deletion/redrive failure**: received messages were not deleted, visibility timeout elapsed, redrive policy moved them

For `maxReceiveCount=1`, emphasize that a single non-delete path is enough to DLQ the message after visibility timeout. Avoid saying "first attempt failed and Lambda returned `batchItemFailures`" unless `ReportBatchItemFailures` is confirmed enabled and the logs actually show the failing record.