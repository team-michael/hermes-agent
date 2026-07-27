# SQS DLQ Creation Alarm — Healthy Lambda + maxReceiveCount=1

Trigger: CloudWatch alarm name matching `<queue-name>-dlq has been created`.

## Classification

Usually `no_action` when:
- DLQ message count is low (single-digit to low tens)
- Consumer Lambda `Errors=0`, `Throttles=0`, `Duration` normal
- Lambda logs show normal `START ... END/REPORT` with no ERROR lines
- Messages in DLQ are valid SQS payloads from known projects/campaigns

Root cause is structural: `maxReceiveCount=1` means any transient `DeleteMessage` failure (network hiccup, SQS service delay) immediately DLQs the message with zero retries. The Lambda itself is healthy and the work was likely completed.

## Triage workflow

1. **Queue attributes** (main queue → DLQ mapping)
   ```bash
   aws sqs get-queue-attributes --region ap-northeast-2 \
     --queue-url <main-queue-url> \
     --attribute-names All \
     --query 'Attributes.{RedrivePolicy:RedrivePolicy,ApproximateNumberOfMessages:ApproximateNumberOfMessages,ApproximateNumberOfMessagesNotVisible:ApproximateNumberOfMessagesNotVisible,CreatedTimestamp:CreatedTimestamp}'
   ```

2. **DLQ attributes**
   ```bash
   aws sqs get-queue-attributes --region ap-northeast-2 \
     --queue-url <dlq-url> \
     --attribute-names All \
     --query 'Attributes.{ApproximateNumberOfMessages:ApproximateNumberOfMessages,ApproximateNumberOfMessagesNotVisible:ApproximateNumberOfMessagesNotVisible,RedrivePolicy:RedrivePolicy}'
   ```

3. **Resolve Lambda consumer name**
   - From the alarm text `scheduled-batch-kakao-alimtalk-queue-dlq` → main queue `scheduled-batch-kakao-alimtalk-queue` → consumer is `scheduled-batch-kakao-alimtalk-delivery`
   - Or inspect the SQS `LambdaEventSourceMapping` / `EventSourceMappings` for the queue.

4. **Lambda health check**
   ```bash
   aws cloudwatch get-metric-statistics --region ap-northeast-2 \
     --namespace AWS/Lambda --metric-name Errors \
     --dimensions Name=FunctionName,Value=scheduled-batch-kakao-alimtalk-delivery \
     --start-time $(date -u -d '1 hour ago' '+%Y-%m-%dT%H:%M:%SZ') \
     --end-time $(date -u '+%Y-%m-%dT%H:%M:%SZ') \
     --period 300 --statistics Sum
   ```
   Also check `Throttles` and `Duration` (Maximum/Average) for the same window.

5. **Lambda logs (alarm window)** — look for ERROR or timeout
   ```bash
   aws logs filter-log-events --region ap-northeast-2 \
     --log-group-name /aws/lambda/scheduled-batch-kakao-alimtalk-delivery \
     --start-time <alarm_start_epoch_ms> --end-time <alarm_end_epoch_ms> \
     --filter-pattern 'ERROR'
   ```
   If empty and `REPORT` lines show normal Duration → healthy consumer.

6. **Scope attribution from DLQ payloads**
   - DLQ messages contain the original SQS `body` JSON with `project_id`, `campaign_id`, `template_code`, `recipient_list`
   - Map `project_id` via DynamoDB `project` table
   - Report `project/campaign` scope (campaign here is the API event type, e.g. `api_kakao_alimtalk`)

## Decision matrix

| Signal | Interpretation |
|---|---|
| `maxReceiveCount=1` | Structural zero-retry policy; any transient failure → DLQ |
| Lambda `Errors=0` + normal `Duration` | Consumer is healthy; not a code bug |
| DLQ count ≤ 5, infrequent | Benign transient glitch; `no_action` |
| DLQ count spikes daily or > 50 | Increase `maxReceiveCount` to 3–5 via SQS `set-queue-attributes` |
| Lambda logs show ERROR / timeout | Follow real-bug path; classify `needs_fix` or `urgent` |

## Known instance

- **Queue**: `scheduled-batch-kakao-alimtalk-queue`
- **DLQ**: `scheduled-batch-kakao-alimtalk-queue-dlq`
- **Consumer**: `scheduled-batch-kakao-alimtalk-delivery` Lambda
- **Pattern observed**: DLQ creation alarm fired twice in 30d (2026-05-18, 2026-05-21) with 2–4 messages each. Messages were `doctornow/api_kakao_alimtalk` campaigns (`NH8648231` ~714 recipients, `G7W913205` ~220 recipients). Lambda healthy throughout. Classified `no_action`.

## Remediation options

- **Immediate**: None; monitor DLQ depth.
- **Structural**: If recurrence increases, change main queue `RedrivePolicy` to `{"maxReceiveCount":3,"deadLetterTargetArn":"..."}`. Note this affects all messages on the queue.
- **Ops hygiene**: Ensure DLQ has its own consumer or alert so messages do not sit indefinitely.
