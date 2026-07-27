# Kinesis Stream Iterator Age / Throughput Alarm Triage

Bounded manual trace for `AWS/Kinesis` `GetRecords.IteratorAgeMilliseconds` alarms when the helper has no Kinesis-specific collector.

## When to use

- Alarm name contains `notifly-event-stream` or another Kinesis stream name.
- Metric namespace is `AWS/Kinesis` and metric name is `GetRecords.IteratorAgeMilliseconds` or `IncomingRecords` / `ReadProvisionedThroughputExceeded`.
- The helper returns `metric_filters: []` and sparse `logs` because this is a native AWS metric alarm, not a log-derived alarm.

## Why this matters

Iterator age measures how far behind a consumer is from the tip of a Kinesis shard. A spike means the consumer is not keeping up with producer throughput. This is usually either:
1. A **transient producer traffic spike** that the consumer will catch up on naturally.
2. A **consumer throughput bottleneck** (Lambda concurrency too low, batch size too small, slow processing, errors causing retries).
3. A **consumer failure** (Lambda errors, timeouts, deployment issue).

The `check` helper has no Kinesis collector, so these steps must be run manually.

## Investigation flow

### 1. Stream status and consumer topology

```bash
aws kinesis describe-stream --stream-name <stream-name> --region ap-northeast-2 \
  --query 'StreamDescription.{StreamName:StreamName,StreamStatus:StreamStatus,ShardCount:length(Shards)}'
```

```bash
aws kinesis list-stream-consumers --stream-arn <stream-arn> --region ap-northeast-2 \
  --query 'Consumers[*].{ConsumerName:ConsumerName,ConsumerStatus:ConsumerStatus}'
```

- If `StreamStatus` is not `ACTIVE`, treat as an infrastructure incident.
- Record shard count. High shard count with a single-threaded consumer (ParallelizationFactor=1) is a known bottleneck pattern.

### 2. Find the actual Lambda consumer

Do not guess the Lambda function name from the stream name. Use event source mappings:

```bash
aws lambda list-event-source-mappings --region ap-northeast-2 \
  --query 'EventSourceMappings[?contains(EventSourceArn, `<stream-name>`) == `true`].{FunctionArn:FunctionArn,State:State,UUID:UUID}'
```

Then inspect the mapping:

```bash
aws lambda get-event-source-mapping --uuid <uuid> --region ap-northeast-2 \
  --query '{State:State,BatchSize:BatchSize,ParallelizationFactor:ParallelizationFactor,MaximumRetryAttempts:MaximumRetryAttempts,BisectBatchOnFunctionError:BisectBatchOnFunctionError,DestinationConfig:DestinationConfig}'
```

Then inspect the function:

```bash
aws lambda get-function --function-name <function-name> --region ap-northeast-2 \
  --query 'Configuration.{MemorySize:MemorySize,Timeout:Timeout,LastModified:LastModified,Runtime:Runtime}'
```

### 3. Producer traffic trend

```bash
aws cloudwatch get-metric-statistics --namespace AWS/Kinesis --metric-name IncomingRecords \
  --dimensions Name=StreamName,Value=<stream-name> \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) --period 300 --statistics Sum --region ap-northeast-2 \
  --query 'Datapoints[*].[Timestamp,Sum]' | sort
```

A rising trend confirms a traffic spike. Compare against baseline.

### 4. Consumer health metrics

```bash
# Lambda Errors
aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Errors \
  --dimensions Name=FunctionName,Value=<function-name> \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) --period 300 --statistics Sum --region ap-northeast-2 \
  --query 'Datapoints[*].[Timestamp,Sum]' | sort
```

```bash
# Lambda Duration
aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Duration \
  --dimensions Name=FunctionName,Value=<function-name> \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) --period 300 --statistics Average --region ap-northeast-2 \
  --query 'Datapoints[*].[Timestamp,Average]' | sort
```

```bash
# Lambda Invocations
aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Invocations \
  --dimensions Name=FunctionName,Value=<function-name> \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) --period 300 --statistics Sum --region ap-northeast-2 \
  --query 'Datapoints[*].[Timestamp,Sum]' | sort
```

### 5. Iterator age trend

```bash
aws cloudwatch get-metric-statistics --namespace AWS/Kinesis --metric-name GetRecords.IteratorAgeMilliseconds \
  --dimensions Name=StreamName,Value=<stream-name> \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) --period 300 --statistics Average --region ap-northeast-2 \
  --query 'Datapoints[*].[Timestamp,Average]' | sort
```

### 6. Lambda ERROR log check (bounded)

If Lambda Errors > 0 or if you want to confirm no hidden errors:

```bash
aws logs filter-log-events --log-group-name /aws/lambda/<function-name> \
  --start-time $(date -u -d '25 minutes ago' +%s)000 \
  --end-time $(date -u +%s)000 \
  --filter-pattern "ERROR" --region ap-northeast-2 --limit 10 \
  --query 'events[*].{timestamp:timestamp,message:message}'
```

Anchor the window to the actual alarm datapoint time (from `describe-alarms` `StateReasonData`), not Slack message time. Convert to epoch milliseconds (`+000`).

## Interpretation heuristics

| Signal | Interpretation |
|--------|----------------|
| Iterator age spikes once then drops to near-zero within 1-2 periods; Lambda Errors ≈ 0; Duration healthy; Invocations stable | **Transient producer spike.** Likely `no_action`. |
| Iterator age sustained high or rising; Lambda Errors ≈ 0; Duration healthy | **Consumer throughput bottleneck.** Check `ParallelizationFactor`, shard count, `BatchSize`. Consider `needs_fix` if recurring. |
| Iterator age rising; Lambda Errors > 0 or Duration near Timeout | **Consumer failure / code regression.** Inspect ERROR logs. Likely `needs_fix` or `urgent` depending on customer impact. |
| `IncomingRecords` flat but iterator age rising after `LastModified` deploy time | **Deployment regression.** Correlate to recent deploy. |
| Single ERROR log recurring with same payload (e.g. `[object Object]` → UTF8 `0x00`) | **Data-quality bug unrelated to throughput.** Log the finding but do not conflate with iterator age unless the error is causing batch bisection/retry storms. |

## Notifly-specific mapping

- Stream `notifly-event-stream` is consumed by Lambda `kds-consumer` (not `event-stream-consumer`).
- The `event-stream-consumer` named consumer exists as an EFO consumer but the actual processing is via `kds-consumer` Lambda event source mapping.
- If investigating `notifly-message-events-stream` or `notifly-triggering-events-stream`, use `list-event-source-mappings` to find the actual function.

## Pitfalls

- Do not guess the Lambda name from the stream name; always use `list-event-source-mappings`.
- `GetRecords.IteratorAgeMilliseconds` is an `Average` over all shards/consumers. A single hot shard can spike the average while others are healthy.
- `get-metric-statistics` does not support percentile statistics; for `p99`-type alarms on custom namespaces, use `get-metric-data` with `ExtendedStatistics`.
- Iterator age alarms may coincide with Lambda ERROR logs that are unrelated (e.g. a persistent DB insertion bug). Always verify whether the ERROR is causing retry/bisection that inflates iterator age, or is merely co-occurring.
