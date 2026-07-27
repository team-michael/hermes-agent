# SQS Lambda Throughput Bottleneck Analysis

When an SQS `ApproximateAgeOfOldestMessage` alarm fires and the consumer is a Lambda,
the root cause is often a throughput bottleneck rather than a code failure.
This reference describes how to distinguish bottleneck from bug and where to fix it.

## When to use

- Alarm metric is `AWS/SQS ApproximateAgeOfOldestMessage` (or `ApproximateNumberOfMessagesVisible`).
- Consumer is a Lambda function (detectable via `list_event_source_mappings`).
- Lambda `Errors` and `Throttles` are zero (or near-zero) during the alarm window.
- Lambda `Duration` is short (e.g., < 100 ms) and stable.
- `NumberOfMessagesDeleted` ≈ `NumberOfMessagesSent` over longer windows, but a transient spike caused the age to rise.

## Analysis flow

1. **Identify the consumer Lambda**
   ```bash
   aws lambda list-event-source-mappings --region ap-northeast-2 --query 'EventSourceMappings[?contains(EventSourceArn, `kinesis-record-dispatcher-queue`)]'
   ```
   Record `FunctionArn`, `BatchSize`, `MaximumConcurrency`, `State`.

2. **Inspect Lambda health**
   ```bash
   aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Errors --dimensions Name=FunctionName,Value=kinesis-record-dispatcher ...
   aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Throttles --dimensions Name=FunctionName,Value=kinesis-record-dispatcher ...
   aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Duration --dimensions Name=FunctionName,Value=kinesis-record-dispatcher ...
   ```
   If all three are healthy, suspect throughput bottleneck.

3. **Compare send vs delete**
   ```bash
   aws cloudwatch get-metric-statistics --namespace AWS/SQS --metric-name NumberOfMessagesSent --dimensions Name=QueueName,Value=kinesis-record-dispatcher-queue --start-time ... --end-time ... --period 60 --statistics Sum
   aws cloudwatch get-metric-statistics --namespace AWS/SQS --metric-name NumberOfMessagesDeleted --dimensions Name=QueueName,Value=kinesis-record-dispatcher-queue --start-time ... --end-time ... --period 60 --statistics Sum
   ```
   Near-parity over 5–10 minutes means the consumer is not stuck; it simply cannot absorb the peak.

4. **Inspect EventSourceMapping config**
   ```bash
   aws lambda get-event-source-mapping --uuid <uuid> --region ap-northeast-2
   ```
   Key fields:
   - `BatchSize`: how many messages per invocation
   - `MaximumConcurrency`: hard limit on concurrent invocations (absent = 1000, but many Notifly Lambdas are set to 2)
   - `VisibilityTimeout`: must be >= 6 × Lambda `Timeout`
   - `ScalingConfig.MaximumConcurrency`: same as above

5. **Calculate throughput ceiling**
   ```
   max_messages_per_second = MaximumConcurrency × BatchSize / (Duration_seconds + overhead)
   ```
   Example: `MaximumConcurrency=2`, `BatchSize=50`, `Duration=0.07s`
   → ceiling ≈ 1,400 messages/second. If the producer sends 2,000 msg/s for a minute, queue age will spike.

6. **Check DLQ**
   ```bash
   aws sqs get-queue-attributes --queue-url <dlq-url> --attribute-names ApproximateNumberOfMessages --region ap-northeast-2
   ```
   DLQ > 0 implies poison messages or retry exhaustion, not pure throughput.

7. **Map scope**
   - SQS messages in a shared pipeline (e.g., `kinesis-record-dispatcher-queue`) aggregate records from **all** projects.
   - Lambda logs (`/aws/lambda/kinesis-record-dispatcher`) usually contain only `START/END/REPORT` lines, not per-project IDs.
   - Do not force a project/campaign scope when the pipeline is intentionally project-agnostic.
   - State explicitly in Korean: "프로젝트/캠페인/유저여정 특정 불가 — 인프라 공통 파이프라인 지연".

## Representative case: `kinesis-record-dispatcher-queue`

- Producer: `event-proxy` ECS service writes to Kinesis (`notifly-event-stream`), then records are enqueued to SQS.
- Consumer: `kinesis-record-dispatcher` Lambda (node22.x, 1024 MB, 300 s timeout).
- EventSourceMapping: `BatchSize=50`, `MaximumConcurrency=2`.
- Timing pattern: scheduled batch campaigns send simultaneously at ~01:00 UTC (10:00 KST), creating a recurrent traffic spike.
- Symptoms: `ApproximateAgeOfOldestMessage` peaks at 78–98 s, `Errors=0`, `Throttles=0`, `Duration=100–570 ms` during the spike window.
- Spike magnitude observed: `NumberOfMessagesSent` ~38,900 in one minute; `NumberOfMessagesDeleted` tracks closely, confirming healthy consumption at average speed.
- Root cause: peak event volume temporarily exceeds `2 × 50 / 0.5 ≈ 200` msg/s short-term capacity.
- Impact: all Notifly projects using the shared event stream experience brief delivery delay. No data loss (DLQ stays at 0 throughout the spike).

## Fix targets

Terraform:
- `infra/terraform/prod/ap-northeast-2/sqs/queues.tf` — alarm threshold or evaluation period
- Lambda module / `aws_lambda_event_source_mapping` resource — `maximum_concurrency`, `batch_size`

Code:
- Lambda batch processing efficiency (reduce per-record latency)
- Producer batching (reduce message count)

## Pitfalls

- The `check` helper may not auto-detect the Lambda consumer for some SQS queues (`lambda_names: []`). If the queue is known but no Lambda appears, search `infra/terraform/prod/ap-northeast-2/lambda/functions.tf` for `event_source_arn` matches, or run `aws lambda list-event-source-mappings --query 'EventSourceMappings[?contains(EventSourceArn, `queue-name`)]'` directly.
- Do not assume `ApproximateAgeOfOldestMessage` = Lambda failure. Zero errors + short duration = bottleneck.
- Do not recommend code changes when the fix is simply raising `MaximumConcurrency`.
- Do not search project IDs in Lambda logs for shared-pipeline queues; the messages are intentionally aggregate.
- Do not omit the EventSourceMapping config from the final answer when it is the dominant root cause.

### Lambda healthy but DLQ still receives messages
When Lambda `Errors=0`, `Throttles=0`, and `Duration` is normal, yet the DLQ has messages, the failure is **not in the function code** but elsewhere in the Lambda-SQS integration chain. Common explanations:

1. **AWS service-level message-deletion failure** — Lambda finishes successfully but the internal SQS `DeleteMessage` call from the Lambda service to SQS fails transiently (network blip, SQS API error). The message becomes visible again and, with `maxReceiveCount=1`, is sent straight to DLQ on the next visibility cycle.
2. **`maxReceiveCount=1` with zero retries** — Any transient failure (including #1) immediately DLQs the message because there are no retry attempts. Terraform fix: raise `maxReceiveCount` to 3–5.
3. **Caught vs uncaught error distinction** — If the Lambda code itself wraps downstream calls (e.g., Kinesis `putRecords`) in `try/catch` and logs, the Lambda invocation succeeds, the SQS message is deleted, and the message **never reaches DLQ**. DLQ presence therefore proves an **uncaught** error or a service-level deletion failure, not a handled code error.
4. **DLQ message body inspection** — When Lambda logs are sparse (only `START/END/REPORT`), read the actual DLQ messages with `receive_message` to extract `project_id` and `campaign_id` from the JSON payload. Map them through DynamoDB `project` for scope attribution. See `references/sqs-dlq-message-inspection.md`.
