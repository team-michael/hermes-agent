# KakaoPoller-P1-BatchFailure — DynamoDB On-Demand Adaptive Capacity Throttle

Applies to alarms in namespace `Notifly/KakaoDeliveryResultPoller`:
- `KakaoPoller-P1-BatchFailure` (`BatchCompletion`, `outcome=failure`)

## Alarm shape

- **EMF metric** emitted from Lambda `kakao-delivery-result-poller` stdout.
- NOT a CloudWatch log metric filter; `metric_filters: []` in helper output.
- Metric: `BatchCompletion`, dimension: `outcome=failure`, statistic: `Sum`, threshold: `>= 1`, period: `300s`.
- Helper returns `lambda: null` because the alarm name `KakaoPoller-P1-BatchFailure` does not directly map to the Lambda function name `kakao-delivery-result-poller`.
- The alarm is defined in Terraform `infra/terraform/prod/ap-northeast-2/lambda/functions.tf` inside the Lambda's `metric_alarm_details` block (line ~3195). The function name can be inferred from the surrounding Terraform context.

## Alarm name to Lambda function name mapping

| Alarm name | Lambda function |
|------------|----------------|
| `KakaoPoller-P1-BatchFailure` | `kakao-delivery-result-poller` |
| `KakaoBrandMessage-P1-BatchFailure` | `kakao-brand-message-delivery` |

When the helper returns `lambda: null` for an EMF metric alarm, search Terraform `functions.tf` for the alarm name to find the enclosing Lambda function definition.

## Root cause: DynamoDB on-demand adaptive capacity throttling

### Mechanism

The Lambda processes SQS batches (BatchSize=10) of Kakao delivery result polling tasks. Each `processRecord` call reads and writes to DynamoDB table `kakao_delivery_result_polling_state` (PAY_PER_REQUEST / on-demand billing mode).

When a large batch of Kakao brand message deliveries completes simultaneously (e.g., class101 daily article campaigns `Y1tuTv`, `yVIBAj`), the poller receives a burst of SQS messages. The resulting DynamoDB write spike exceeds the table's adaptive capacity, causing `ThrottlingException: Throughput exceeds the current capacity of your table or index.`

### ThrottlingException propagation

```
processRecord (line 552)
  -> pollingStateRepository.save(stateAfterPoll)    // line ~630
    -> DynamoDB PutItem -> ThrottlingException
  -> throw error (not caught in processRecord)
-> Promise.allSettled sees rejected
-> console.error('Failed to process Kakao polling record', result.reason)
-> batchItemFailures = [{ itemIdentifier: ... }]
-> outcome = 'failure'
-> emitCount({ outcome }, 'BatchCompletion')
```

The ThrottlingException is NOT caught inside `processRecord`. It propagates to the `Promise.allSettled` handler in the SQS batch handler (line 637-648), which logs `Failed to process Kakao polling record ThrottlingException: ...` and returns the failed message IDs as `batchItemFailures` for SQS retry.

### WCU spike evidence

| Time window (UTC) | ConsumedWriteCapacityUnits | Baseline |
|--------------------|---------------------------|----------|
| 11:30 | 189 | normal |
| 11:35 | 161 | normal |
| **11:40** | **152,619** | **~800x spike** |
| **11:45** | **183,995** | **~970x spike** |
| 11:50 | 193 | recovered |
| 11:55 | 7,266 | tail |

### ThrottledRequests metric pitfall

`AWS/DynamoDB ThrottledRequests` with `TableName=kakao_delivery_result_polling_state` dimension may show **0** during the throttle window, even though `ThrottlingException` is clearly thrown in Lambda logs. This is known DynamoDB on-demand behavior: adaptive capacity can throttle individual requests at the partition level without surfacing in the account/table-level `ThrottledRequests` metric. The evidence is the WCU spike magnitude + the `ThrottlingException` in Lambda logs.

## Coexisting secondary error: `invalid input syntax for type json`

During the same alarm window, `delivery_failure_log_<project_id>` INSERT failures produce `invalid input syntax for type json` ERROR logs. This is the same pattern documented in `references/scheduled-batch-delivery-dbinsert-json-serialization-bug.md` section "Kakao brand message path".

**Critical distinction**: The JSON error is caught in a try/catch at `index.ts:167-171` and does NOT propagate. It does NOT cause the `BatchCompletion outcome=failure` metric. The batch failure is caused by the DynamoDB ThrottlingException, not the JSON error.

```typescript
// index.ts lines 165-171 -- JSON error is CAUGHT, does not propagate
await deliveryResultRepository.upsert(records.delivery_results);
try {
    await deliveryResultRepository.insertFailureLogs(records.delivery_results);
} catch (error) {
    console.error('Failed to insert delivery failure logs', error);
    // continues -- delivery_results_persisted_at is still set
}
```

When triaging, do not confuse the 100+ JSON ERROR log lines with the batch failure cause. The actual batch failure trigger is the single `Failed to process Kakao polling record ThrottlingException` log line.

## filter_log_events pagination for rare failure events

The `BatchCompletion` EMF metric is emitted at the end of every SQS batch processing invocation. During a high-volume window, there may be 150+ `outcome=success` events and only 1 `outcome=failure` event.

**Pitfall**: `filter_log_events` with `filterPattern='BatchCompletion'` and `limit=100` returns only the first 100 events. If the single failure event is event #157, it will be missed. Always paginate with `nextToken` or use `limit=10000` when searching for a rare event among many similar events.

```bash
# Reliable approach: paginate or use high limit
aws logs filter-log-events --region ap-northeast-2 \
  --log-group-name /aws/lambda/kakao-delivery-result-poller \
  --start-time "$start_ms" --end-time "$end_ms" \
  --filter-pattern 'BatchCompletion' \
  --limit 10000 \
  --output json | jq '[.events[] | select(.message | contains("\"outcome\":\"failure\""))]'
```

## Scope extraction

- `project_id` is present in `PollAttempt` EMF metric lines with dimension `[project_id, channel, outcome]`.
- The `delivery_failure_log_<project_id>` table suffix in ERROR logs also provides the project ID.
- Map via DynamoDB `project` table.
- Campaign IDs (`Y1tuTv`, `yVIBAj`) appear in the INSERT VALUES of the `delivery_failure_log` ERROR lines.

## Recurrence pattern

| Date | Root cause | Classification |
|------|-----------|----------------|
| 2026-06-04 | Missing env var `SQS_KAKAO_BRAND_MESSAGE_QUEUE_URL` (deployment issue) | Different root cause -- verify independently |
| 2026-06-19 | DynamoDB adaptive capacity throttle (WCU 302,629) | `no_action` -- transient |
| 2026-06-23 | DynamoDB adaptive capacity throttle (WCU 152,619) | `no_action` -- transient |

Each alarm occurrence should be verified independently -- the 6/4 alarm was a deployment config issue, not the same DynamoDB throttle pattern.

## Classification rule

Classify as `no_action` when:
- `AWS/Lambda Errors == 0` and `Throttles == 0` (Lambda runtime healthy)
- The batch failure is from DynamoDB `ThrottlingException` (infrastructure-level, not code bug)
- The alarm auto-recovers within 15 minutes (OK transition)
- The SQS `batchItemFailures` mechanism ensures message retry (no data loss)
- The JSON serialization errors are caught and do not affect the batch outcome

The Lambda's SQS EventSourceMapping has `BatchSize=10`. Failed messages are returned as `batchItemFailures` and retried by SQS after visibility timeout. No message loss occurs.

## Bounded manual trace commands

```bash
# 1. Find the failure BatchCompletion event (paginate if needed)
start_ms=$(date -d '2026-06-23 11:40:00 UTC' +%s)000
end_ms=$(date -d '2026-06-23 11:45:00 UTC' +%s)000
aws logs filter-log-events --region ap-northeast-2 \
  --log-group-name /aws/lambda/kakao-delivery-result-poller \
  --start-time "$start_ms" --end-time "$end_ms" \
  --filter-pattern 'BatchCompletion' \
  --limit 10000 \
  --output json | jq '[.events[] | select(.message | contains("\"outcome\":\"failure\""))]'

# 2. Find the ThrottlingException that caused the batch failure
aws logs filter-log-events --region ap-northeast-2 \
  --log-group-name /aws/lambda/kakao-delivery-result-poller \
  --start-time "$start_ms" --end-time "$end_ms" \
  --filter-pattern 'ThrottlingException' \
  --limit 5 --output json | jq '.events[0].message'

# 3. Check DynamoDB WCU spike
aws cloudwatch get-metric-statistics --region ap-northeast-2 \
  --namespace AWS/DynamoDB --metric-name ConsumedWriteCapacityUnits \
  --dimensions Name=TableName,Value=kakao_delivery_result_polling_state \
  --start-time '2026-06-23T11:30:00Z' --end-time '2026-06-23T12:00:00Z' \
  --period 300 --statistics Sum \
  --output json | jq '.Datapoints | sort_by(.Timestamp)'

# 4. Lambda Errors/Throttles (confirm runtime health)
aws cloudwatch get-metric-statistics --region ap-northeast-2 \
  --namespace AWS/Lambda --metric-name Errors \
  --dimensions Name=FunctionName,Value=kakao-delivery-result-poller \
  --start-time '2026-06-23T11:30:00Z' --end-time '2026-06-23T12:00:00Z' \
  --period 300 --statistics Sum
```

## Terraform context

- Lambda function: `infra/terraform/prod/ap-northeast-2/lambda/functions.tf` (function name `kakao-delivery-result-poller`, memory 4096 MB)
- Alarm definition: same file, `metric_alarm_details` block at line ~3195
- DynamoDB table: `infra/terraform/prod/ap-northeast-2/dynamodb/tables.tf` line 382 (`kakao_delivery_result_polling_state`, `billing_mode = "PAY_PER_REQUEST"`)
- SQS EventSourceMapping: `BatchSize=10`, no `MaximumConcurrency` set
