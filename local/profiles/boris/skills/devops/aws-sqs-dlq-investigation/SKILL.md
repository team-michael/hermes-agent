---
name: aws-sqs-dlq-investigation
description: Investigate SQS Dead Letter Queue alarms — systematic root cause analysis for why messages ended up in a DLQ. Covers Lambda-triggered SQS, event source mappings, and the common traps.
tags: [aws, sqs, dlq, lambda, cloudwatch, debugging, incident-response]
trigger: User reports a DLQ alarm, asks why messages are in a DLQ, or asks about SQS message failures.
---

# SQS DLQ Root Cause Investigation

## Critical Rule: Verify Before Concluding

**Do NOT conclude "timeout exceeded" or "Lambda failed" without checking actual numbers.** A common trap is seeing high message age in the queue and assuming it exceeded a timeout — message age (time waiting in queue) is NOT the same as Lambda execution duration or visibility timeout being exceeded.

Always compare:
- Actual Lambda max Duration vs Lambda Timeout setting
- Actual Lambda Errors count (should be non-zero for Lambda failures)
- Actual ApproximateReceiveCount on DLQ messages vs maxReceiveCount setting

## Investigation Order

### Phase 1: Queue Configuration (do this FIRST)
```python
# Get source queue attributes
sqs.get_queue_attributes(QueueUrl=src_url, AttributeNames=['All'])
```
Key values to extract:
- **VisibilityTimeout** — how long a message is invisible after being received
- **RedrivePolicy** → **maxReceiveCount** — how many receive attempts before DLQ
- **MessageRetentionPeriod** — max lifetime of a message

### Phase 2: Lambda Configuration
```python
lam.get_function_configuration(FunctionName=fn_name)
lam.get_function_concurrency(FunctionName=fn_name)  # reserved concurrency
lam.list_event_source_mappings(FunctionName=fn_name)  # SQS trigger config
```
Key values:
- **Lambda Timeout** vs **VisibilityTimeout** (timeout should be < visibility timeout)
- **MaximumConcurrency** on event source mapping — hard cap on parallel Lambda invocations
- **BatchSize** and **MaximumBatchingWindowInSeconds**
- **FunctionResponseTypes** — if `ReportBatchItemFailures` is set, partial batch failures are possible

### Phase 3: CloudWatch Metrics (1-minute granularity around incident time)
Check these Lambda metrics:
- **Errors** — non-zero means Lambda threw an unhandled exception
- **Duration** (Maximum) — compare against Lambda Timeout
- **Throttles** — Lambda concurrency limit hit
- **ConcurrentExecutions** (Maximum) — actual parallel execution count
- **Invocations** — traffic volume, look for spikes

Check these SQS metrics:
- **ApproximateAgeOfOldestMessage** — shows queue backlog buildup
- **NumberOfMessagesSent** on the DLQ — when and how many messages moved to DLQ
- **NumberOfMessagesReceived/Deleted** on source queue — processing throughput

### Phase 4: Logs
```
fields @timestamp, @message
| filter @message like /(?i)(timed out|timeout|error|exception|Task timed|REPORT.*Timeout)/
| filter @message not like /^(START|END|REPORT|INIT_START)/
| sort @timestamp asc
| limit 50
```
Look for:
- "Task timed out after X seconds" — actual Lambda timeout
- Unhandled exceptions
- Note: if the Lambda code has try/catch that swallows errors, Lambda Errors metric will be 0 even when processing fails

### Phase 5: DLQ Message Content
```python
# Peek without consuming (short visibility timeout)
sqs.receive_message(QueueUrl=dlq_url, MaxNumberOfMessages=10,
    AttributeNames=['All'], VisibilityTimeout=5)
```
Key attributes on each message:
- **ApproximateReceiveCount** — how many times it was received before DLQ
- **SenderId** — which service/Lambda sent it to the source queue
- **SentTimestamp** — when it was originally sent
- **Body** — the actual payload (may reveal which project/campaign/event caused the issue)

## Common Root Causes

### 1. MaximumConcurrency cap + maxReceiveCount=1
**Pattern:** Lambda max duration is fine, Lambda errors = 0, but messages pile up.
**Mechanism:** Event source mapping has a low MaximumConcurrency (e.g., 2). During traffic spikes, SQS poller receives messages but can't dispatch them fast enough. With maxReceiveCount=1, any message that gets received but not successfully processed on the first attempt goes straight to DLQ.
**Fix:** Increase maxReceiveCount to 2-3, or increase MaximumConcurrency.

### 2. Lambda timeout exceeded
**Pattern:** Lambda Duration max ≈ Lambda Timeout, "Task timed out" in logs.
**Mechanism:** Downstream service (Kinesis, DB, API) is slow or down.
**Fix:** Increase Lambda timeout, fix downstream, add circuit breaker.

### 3. Lambda unhandled exception
**Pattern:** Lambda Errors > 0, exception in logs.
**Mechanism:** Code bug, permission error, resource not found.
**Fix:** Fix the code/permissions.

### 4. Visibility timeout too short
**Pattern:** ApproximateReceiveCount > 1 on DLQ messages, Lambda duration close to VisibilityTimeout.
**Mechanism:** Lambda takes longer than VisibilityTimeout, message becomes visible again, gets re-received, hits maxReceiveCount.
**Fix:** Set VisibilityTimeout to 6x Lambda timeout (AWS recommendation).

### 5. Throttling
**Pattern:** Lambda Throttles > 0, possibly account-level concurrent execution limit.
**Fix:** Request limit increase, add reserved concurrency.

## Pitfalls

- **Message age ≠ processing time.** ApproximateAgeOfOldestMessage shows how long a message has been in the queue, not how long Lambda took to process it.
- **Lambda Errors=0 doesn't mean no failures.** If Lambda code catches all exceptions and returns success, the SQS message is deleted successfully — but the intended work (e.g., Kinesis putRecords) may have silently failed. Check application-level logs.
- **maxReceiveCount=1 means zero retries.** The first receive IS the only attempt. This is aggressive — even transient SQS/Lambda integration hiccups will send messages to DLQ.
- **DLQ NumberOfMessagesSent metric may have no data** if the DLQ receives messages via SQS redrive (it's the source queue's internal mechanism, not an explicit SendMessage call). Check ApproximateNumberOfMessagesVisible on the DLQ instead.

## Environment Note (notifly-event specific)

AWS credentials are in `/home/ubuntu/.hermes/.env` — parse the file and create a boto3 Session explicitly. Shell env vars may not persist across terminal sessions.
