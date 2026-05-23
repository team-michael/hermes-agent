# kinesis-record-dispatcher-queue Transient Spike Pattern

**Alarm**: `kinesis-record-dispatcher-queue too high approximate age`  
**Namespace**: `AWS/SQS`, Metric: `ApproximateAgeOfOldestMessage`, Statistic: `Maximum`

## Architecture

- **Producer**: `segment-publisher` ECS Fargate service. Task-def sets `KINESIS_RECORD_DISPATCHER_SQS_QUEUE_URL` to this queue.
- **Consumer**: `kinesis-record-dispatcher` Lambda (SQS trigger, `BatchSize: 50`, `MaximumBatchingWindowInSeconds: 1`, no `MaximumConcurrency` set → default 5 concurrent).
- **Purpose**: Lambda reads SQS messages and forwards to Kinesis Data Streams via `PutRecords` in 300-record chunks.

## Triage

1. Alarm metadata: threshold 20s, period 60s, `datapoints_to_alarm=5`.
2. Queue attributes: `ApproximateNumberOfMessagesVisible`, `NumberOfMessagesSent`, `NumberOfMessagesDeleted`.
   - Near-parity on Sent vs Deleted → normal throughput.
   - Spike values: `NumberOfMessagesVisible` has hit 9,865+ (7d max). `Age` has hit 562s.
3. Lambda metrics:
   - `AWS/Lambda Duration`: should stay low (<500ms avg even during spike)
   - `AWS/Lambda Errors`: must be 0
   - `AWS/Lambda Throttles`: must be 0
4. EventSourceMapping: `BatchSize: 50`, `MaximumConcurrency` is `null`.
5. Upstream ECS batch activity: check `/aws/ecs/notifly-services-prod/segment-publisher` for `recipients published` or `Start extracting project segment` around the spike window to confirm scheduled batch burst.

## Classification

**`no_action`** when ALL of:
- Lambda Errors=0, Throttles=0
- Lambda Duration stays low (<500ms avg)
- Queue recovers to age ≈ 0 within 5-10 minutes
- Segment-publisher batch activity visible upstream

This is a transient upstream burst. The Lambda consumer is healthy; the queue acts as a buffer during batch surges.

## Structural notes

- `RedrivePolicy.maxReceiveCount` = 1. Any Lambda timeout immediately DLQs the entire batch (50 messages) with zero retries.
- The queue has no per-project dimensions. Scope is infra-wide common pipeline delay.
- DLQ `kinesis-record-dispatcher-queue-dlq` typically shows 0-1 messages at steady state.

## Historical recurrence

Observed twice-daily recurrence at approximately:
- ~01:00 UTC (~10:00 KST)
- ~23:00 UTC (~08:00 KST next day)

When alarm history shows this pattern and current metrics match, classify as known periodic batch workload.

## Terraform source

- Alarm definition: `infra/terraform/prod/ap-northeast-2/sqs/queues.tf` line 53
- DLQ alarm definition: line 78
- Queue definition: line 549
- Lambda event source: `infra/terraform/prod/ap-northeast-2/lambda/functions.tf` line 3586
