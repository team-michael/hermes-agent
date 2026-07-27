# kinesis-record-dispatcher-queue-dlq triage

Alarm: `kinesis-record-dispatcher-queue-dlq has been created`  
Namespace: `AWS/SQS` · Metric: `ApproximateNumberOfMessagesVisible`  
Threshold: ≥ 1 · Period: 60s · Evaluation: 1 of 1

## Structural root cause

Main queue (`kinesis-record-dispatcher-queue`) uses `RedrivePolicy.maxReceiveCount: 1`. Any transient Lambda receive failure immediately DLQs the message with zero retries. Lambda (`kinesis-record-dispatcher`) itself is always healthy.

## Frequency

Rare and isolated — typically 1 single-message transition per incident, < 5 per 30 days.

## DLQ message shape

The DLQ receives records from more than one upstream stream/producer — the shape varies. Two confirmed variants so far:

**Variant A — triggering events (produced by `kds-consumer`):**

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
        # kinesis-record-dispatcher-queue-dlq triage

        Alarm: `kinesis-record-dispatcher-queue-dlq has been created`  
        Namespace: `AWS/SQS` · Metric: `ApproximateNumberOfMessagesVisible`  
        Threshold: ≥ 1 · Period: 60s · Evaluation: 1 of 1

        ## Structural root cause

        Main queue (`kinesis-record-dispatcher-queue`) uses `RedrivePolicy.maxReceiveCount: 1`. Any transient Lambda receive failure immediately DLQs the message with zero retries. Lambda (`kinesis-record-dispatcher`) itself is always healthy.

        ## Frequency

        Rare and isolated — typically 1 single-message transition per incident, < 5 per 30 days. During a throughput-bottleneck burst (see `references/kinesis-record-dispatcher-queue-throughput.md`), tens of messages can land at once as a byproduct of the age-of-oldest-message alarm firing, not as a separate incident.

        ## DLQ message shape — two known payload variants

        The same queue carries at least two distinct stream envelopes; check `streamName` first to pick the right field-extraction path.

        ### Variant A — `notifly-triggering-events-stream` (kds-consumer origin)

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

        ### Variant B — `notifly-message-events-stream` (delivery/analytics event origin)

        Observed during a throughput-bottleneck burst (2026-07-09, `weatherstone` project, campaign `XoA7dH`). These are delivery/analytics tracking events (e.g. push `send_success`), not the triggering-event pipeline. Losing these means campaign delivery *statistics* may under-count — the actual send (push/SMS/etc.) already happened and is unaffected.

        ```json
        {
          "streamName": "notifly-message-events-stream",
          "records": [
            {
              "data": {
                "id": "<uuid>",
                "type": "MessageEvent",
                "project_id": "<project_id>",
                "resource_type": "campaign",
                "campaign_id": "<campaign_id>",
                "name": "send_success",
                "time": <epoch_ms>,
                "notifly_user_id": "<user_id>",
                "notifly_device_id": "<device_id>",
                "event_params": {
                  "message_id": "<uuid>",
                  "channel": "push-notification",
                  "subtype": "text",
                  "extra_data": "{...device token / provider payload...}"
                }
              }
            }
          ]
        }
        ```

        `resource_type` may also be `user_journey` for user-journey-triggered sends — same extraction path, just report user journey instead of campaign per the mutual-exclusivity rule.

        ## Scope extraction

        - `project_id` → DynamoDB `project` table (e.g. `031b18009978590188e49e6777447fc2` = `munice`; `9156042e17c3560ab9c5717c75b1f5d6` = `weatherstone`)
        - `campaign_id` is present directly in the payload in both variants
        - `experiment_id` and `variant_id` may also be present for A/B tests (Variant A only)
        - Variant B's `extra_data` may embed device push tokens / provider payload fields — do not print these verbatim in the final answer; extract only `project_id`/`campaign_id`/`resource_type`/`name`.

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

        When the DLQ receipt is a byproduct of a throughput-bottleneck burst (queue age alarm also firing, Lambda healthy), still classify `no_action` for the alarm — but explicitly state the DLQ message count and affected project/campaign in `고객 영향도` rather than omitting it just because the root alarm resolves on its own.

        ## DLQ message inspection (read-only)

        ```bash
        aws sqs receive-message --region ap-northeast-2 \
          --queue-url https://sqs.ap-northeast-2.amazonaws.com/702197142747/kinesis-record-dispatcher-queue-dlq \
          --max-number-of-messages 10 --visibility-timeout 10 \
          --attribute-names All --message-attribute-names All \
          --output json | jq -r '.Messages[] | (.Body | fromjson | {stream: .streamName, records_length: (.records | length), first_record: (.records[0].data | {project_id, campaign_id, resource_type, name})})'
        ```

        The `jq` filter above works for both variants since both nest `project_id`/`campaign_id` under `records[0].data`; `resource_type`/`name` will be `null` for Variant A (kds-consumer payloads don't set them) and populated for Variant B.

        Map `project_id` via DynamoDB `project` and report `project_id/name/product_id` + `campaign_id`.

        Note: `receive-message` changes message visibility. Use a short `--visibility-timeout` (e.g. 10s). Run only when scope is a mandatory field and the helper reports unknown.
