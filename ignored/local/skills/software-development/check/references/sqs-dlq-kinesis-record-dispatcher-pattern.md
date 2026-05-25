# kinesis-record-dispatcher-queue-dlq triage

Alarm: `kinesis-record-dispatcher-queue-dlq has been created`  
Namespace: `AWS/SQS` · Metric: `ApproximateNumberOfMessagesVisible`  
Threshold: ≥ 1 · Period: 60s · Evaluation: 1 of 1

## Structural root cause

Main queue (`kinesis-record-dispatcher-queue`) uses `RedrivePolicy.maxReceiveCount: 1`. Any transient Lambda receive failure immediately DLQs the message with zero retries. Lambda (`kinesis-record-dispatcher`) itself is always healthy.

## Frequency

Rare and isolated — typically 1 single-message transition per incident, < 5 per 30 days.

## DLQ message shape

The body is a JSON envelope produced by `kds-consumer`:

```json
{
  "streamName": "notifly-triggering-events-stream",
  "records": [
    {
      "data": {
        "triggering_event_id": "<uuid>",
        "project_id": "<project_id>",
        "campaign_id": "<campaign_id>",
        "experiment_id": "<experiment_id>",
        "variant_id": "<variant_id>",
        "notifly_user_id": "<user_id>",
        "external_user_id": "<external_user_id>",
        "time": <epoch_usecs>,
        "triggering_source": "lambda__kds-consumer",
        "event_params": {}
      },
      "partitionKey": "<triggering_event_id>"
    }
  ]
}
```

## Scope extraction

- `project_id` → DynamoDB `project` table (e.g. `031b18009978590188e49e6777447fc2` = `munice`)
- `campaign_id` is present directly in the payload
- `experiment_id` and `variant_id` may also be present for A/B tests

## Consumer health check

```bash
aws lambda get-function-configuration --region ap-northeast-2 \
  --function-name kinesis-record-dispatcher \
  --query '{Timeout:Timeout,MemorySize:MemorySize,LastModified:LastModified}'

# Typical: Timeout 300, MemorySize 1024, Runtime nodejs22.x, Errors=0, Throttles=0
```

## Classification

Always `no_action` unless:
- Lambda Errors > 0 or Throttles > 0 during the window (then investigate as real consumer failure)
- DLQ depth > 1 and growing (then investigate main queue backlog)
- `ApproximateAgeOfOldestMessage` on the main queue is sustained high (throughput bottleneck)

## DLQ message inspection (read-only)

```bash
aws sqs receive-message --region ap-northeast-2 \
  --queue-url https://sqs.ap-northeast-2.amazonaws.com/702197142747/kinesis-record-dispatcher-queue-dlq \
  --max-number-of-messages 10 --visibility-timeout 10 \
  --attribute-names All --message-attribute-names All \
  --output json | jq -r '.Messages[] | (.Body | fromjson | {records_length: (.records | length), first_record: (.records[0] | {project_id:.data.project_id,campaign_id:.data.campaign_id})})'
```

The payload shape is:

```json
{
  "streamName": "notifly-triggering-events-stream",
  "records": [
    {
      "data": {
        "triggering_event_id": "<uuid>",
        "project_id": "<project_id>",
        "campaign_id": "<campaign_id>",
        "experiment_id": "<experiment_id>",
        "variant_id": "<variant_id>",
        ...
      },
      "partitionKey": "<triggering_event_id>"
    }
  ]
}
```

Map `project_id` via DynamoDB `project` and report `project_id/name/product_id` + `campaign_id`.

Note: `receive-message` changes message visibility. Use a short `--visibility-timeout` (e.g. 10s). Run only when scope is a mandatory field and the helper reports unknown.
