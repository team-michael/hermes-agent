# SQS DLQ: New Consumer Deployment Failure

Pattern: DLQ alarm fires for a queue whose consumer (Lambda or ECS) was
deployed very recently, and every invocation times out or fails with the same
error.

## When to suspect this pattern

- DLQ alarm fires with no prior 7d/30d history.
- `CreatedTimestamp` on the main queue is within hours of the alarm.
- Lambda `LastModified` or EventSourceMapping `LastModified` is within minutes
  of the alarm.
- All Lambda invocations in the log stream end with `REPORT ... Status: timeout`
  (or the same unhandled exception).
- DLQ payload contains obviously synthetic/test data (e.g. `createdDateTime:
  2025-01-01T00:00:00+09:00`).

## Root cause

The queue, DLQ, alarm, and consumer were all created/deployed together.
The consumer cannot reach its dependency (DB, VPC endpoint, external API,
secrets manager, etc.) so it hangs until timeout or crashes immediately.
Test/initialization messages then exhaust `maxReceiveCount` and land in the DLQ.

## Bounded trace commands

### 1. Queue creation time and main-queue health

```bash
export AWS_DEFAULT_REGION=ap-northeast-2
aws sqs get-queue-attributes \
  --queue-url "$(aws sqs get-queue-url --queue-name <main-queue-name> --query QueueUrl --output text)" \
  --attribute-names All \
  --query 'Attributes.{Created:CreatedTimestamp,Messages:ApproximateNumberOfMessages,NotVisible:ApproximateNumberOfMessagesNotVisible,Delayed:ApproximateNumberOfMessagesDelayed,Redrive:RedrivePolicy,Visibility:VisibilityTimeout}'
```

### 2. Lambda config and last modified

```bash
aws lambda get-function-configuration \
  --function-name <lambda-name> \
  --query '{Name:FunctionName,Runtime:Runtime,MemorySize:MemorySize,Timeout:Timeout,LastModified:LastModified,State:State,Handler:Handler}'
```

### 3. EventSourceMapping last modified

```bash
aws lambda list-event-source-mappings \
  --event-source-arn "$(aws sqs get-queue-url --queue-name <main-queue-name> --query QueueUrl --output text | xargs -I{} aws sqs get-queue-attributes --queue-url {} --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)" \
  --query 'EventSourceMappings[0].{UUID:UUID,BatchSize:BatchSize,MaxConcurrency:ScalingConfig.MaximumConcurrency,State:State,LastModified:LastModified}'
```

### 4. Recent Lambda logs (stream-first, no broad filter)

```bash
export AWS_DEFAULT_REGION=ap-northeast-2
python3 -c "
import boto3, datetime
logs = boto3.client('logs')
streams = logs.describe_log_streams(
    logGroupName='/aws/lambda/<lambda-name>',
    orderBy='LastEventTime', descending=True, limit=5)['logStreams']
for s in streams:
    events = logs.filter_log_events(
        logGroupName='/aws/lambda/<lambda-name>',
        logStreamNames=[s['logStreamName']],
        limit=10)['events']
    for e in events:
        ts = datetime.datetime.fromtimestamp(e['timestamp']/1000, tz=datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        print(f'[{ts}] {e[\"message\"][:500]}')
"
```

### 5. Lambda metrics (Errors, Duration, Throttles)

```bash
aws cloudwatch get-metric-statistics \
  --namespace 'AWS/Lambda' \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=<lambda-name> \
  --start-time "$(date -u -d '7 hours ago' +%Y-%m-%dT%H:%M:%SZ)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --period 3600 --statistics Sum
```

Repeat for `Duration` and `Throttles`.

## Interpretation

| Signal | Meaning |
|---|---|
| Queue `CreatedTimestamp` within hours of alarm | Queue is brand new. |
| Lambda `LastModified` within minutes of alarm | Fresh deploy. |
| Every `REPORT` line shows `Status: timeout` | Consumer hangs on external dependency. |
| `Duration` ≈ `Timeout` on every invocation | Consistent timeout, not intermittent. |
| `Errors` > 0 but no ERROR log lines | Timeout is registered as Lambda error metric but does not emit `console.error`. |
| DLQ payload looks synthetic/test | Test messages triggered during queue creation/validation. |

## Pitfall: `filter-log-events` colon in `filterPattern`

CloudWatch Logs `filter-log-events` rejects `?Status: timeout` (colon is an
invalid character in filter-pattern terms). Use stream-first enumeration
(`describe_log_streams` + `filter_log_events` with no filter, or with `ERROR`
only) instead, or escape/omit the colon.

## Pitfall: timeout does not emit ERROR log lines

Lambda timeout produces `REPORT ... Status: timeout`, not a `console.error` or
`ERROR` log line. Searching `filter-log-events` with `ERROR` will return zero
results even when every invocation times out. Always check the raw log stream
for `REPORT` lines.

## Customer impact

Usually **low or none** if the messages are synthetic test data and the queue
has no production traffic yet. Confirm by checking `NumberOfMessagesSent` on
the main queue: near-zero means no real production messages have arrived.

## Immediate action

- Fix the consumer's dependency connectivity (VPC, security group, IAM,
  environment variables, secret rotation).
- Purge or redrive the DLQ test messages.
- Re-test with a fresh synthetic message.
