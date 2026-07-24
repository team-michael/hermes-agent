# Dimensionless AWS/Lambda Duration Sum Alarm Triage

## Alarm Shape

- Name: typically `notifly-lambda-high-duration`
- Namespace: `AWS/Lambda`
- MetricName: `Duration`
- Statistic: `Sum`
- Period: `60`
- Threshold: ~10,000,000 ms (10,000 s)
- Dimensions: `[]` (empty — account-wide aggregate)

## Why the helper cannot resolve it

The helper's Lambda collector uses `FunctionName` dimension or alarm-name heuristics to resolve the target function. When dimensions are empty, `detected.lambda_names` is empty and the collector returns `lambda: null`.

## Manual Trace

Query all Lambda functions' `Duration Sum` around the alarm window:

```python
import boto3
session = boto3.Session(region_name='ap-northeast-2')
cw = session.client('cloudwatch')
lambda_client = session.client('lambda')

functions = []
paginator = lambda_client.get_paginator('list_functions')
for page in paginator.paginate():
    for f in page['Functions']:
        functions.append(f['FunctionName'])

high = []
for fn in functions:
    resp = cw.get_metric_statistics(
        Namespace='AWS/Lambda', MetricName='Duration',
        Dimensions=[{'Name':'FunctionName','Value':fn}],
        StartTime=start, EndTime=end, Period=60, Statistics=['Sum']
    )
    for dp in resp['Datapoints']:
        if dp['Sum'] > 5000000:
            high.append({'function': fn, 'timestamp': dp['Timestamp'].isoformat(), 'sum': dp['Sum']})
```

Then cross-check `Errors`, `Throttles`, `ConcurrentExecutions`, `Invocations` for the top contributor(s).

## Expected Contributors

In Notifly prod, the dominant contributors during the daily batch window (~01:00 UTC / ~10:00 KST) are:

- `scheduled-batch-delivery`: scheduled campaign push-notification batch send
- `kds-consumer`: Kinesis event ingestion consumer

Both typically show:
- Errors: 0
- Throttles: 0
- Concurrency: 100 (`scheduled-batch-delivery`), ~130 (`kds-consumer`)
- Invocations: 400–900/min

## Classification

- **no_action**: When Errors=0, Throttles=0, the alarm is from normal daily batch workload, and the alarm self-recovers to OK within minutes. This is a known periodic pattern caused by the aggregate Sum of multiple healthy high-concurrency functions.
- **needs_fix**: If a *new* function suddenly dominates, or Errors/Throttles are non-zero, or the alarm persists well past the batch window.
- **urgent**: Only if actual invocation failures or customer-visible delivery failures are present.

## Distinguish from per-function Duration alarms

Per-function Lambda duration alarms use `FunctionName` dimension and typically threshold on p99/Average per invocation. This alarm uses no dimensions and thresholds on aggregate `Sum` across the entire account, so brief high-concurrency bursts from healthy functions can breach it.

## Resilience / Notifly-specific

The `notifly-lambda-high-duration` alarm was created as a catch-all safety net. It is inherently noisy during batch windows because it lacks per-function dimension filtering. The long-term fix options are:
1. Add `FunctionName` dimension filters to the alarm (one per known high-duration function).
2. Raise the threshold specifically for the 01:00 UTC batch window.
3. Replace with per-function p99 duration alarms that are more signal-dense.
