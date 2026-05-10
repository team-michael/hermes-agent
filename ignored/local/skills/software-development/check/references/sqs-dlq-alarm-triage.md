# SQS DLQ Alarm Triage

When a CloudWatch alarm fires on a dead-letter queue (`ApproximateNumberOfMessagesVisible >= 1` or queue-name suffix `-dlq`), use this reference to distinguish transient redrive from real poison-message incidents, and to locate the structural fix.

## When to use

- Alarm name contains `-dlq` or `dlq has been created`.
- Metric is `AWS/SQS ApproximateNumberOfMessagesVisible` on a DLQ.
- The DLQ alarm has little or no history because DLQ messages are usually short-lived.

## Analysis flow

1. **Check the companion main-queue alarm**
   DLQ alarms are secondary. The primary signal is usually on the main queue.
   ```bash
   aws cloudwatch describe-alarms --alarm-name-prefix '<main-queue-base-name>' --region ap-northeast-2 --query 'MetricAlarms[].{Name:AlarmName,State:StateValue,Reason:StateReason}'
   ```
   Look for:
   - `ApproximateAgeOfOldestMessage` ALARM→OK transitions around the same window.
   - Any `ConsoleErrors` or Lambda error alarms for the consumer.
   If the main queue had an age spike that recovered just before the DLQ alarm, the DLQ messages are likely from that transient backlog.

2. **Get the current DLQ state and redrive chain**
   ```bash
   aws sqs get-queue-attributes --queue-url <dlq-url> --attribute-names All --region ap-northeast-2
   ```
   Also read the main queue attributes to see `RedrivePolicy`:
   ```bash
   aws sqs get-queue-attributes --queue-url <main-queue-url> --attribute-names All --region ap-northeast-2
   ```
   Key fields:
   - `RedrivePolicy.maxReceiveCount` — **1 is aggressive**. Any transient failure (cold-start timeout, network blip, SQS visibility timeout edge) immediately DLQs the message.
   - `RedrivePolicy.deadLetterTargetArn` — confirms the DLQ pairing.
   - `VisibilityTimeout` on the main queue — must be >= 6 × Lambda timeout.

3. **Inspect the consumer Lambda health**
   Even when the DLQ has messages, the Lambda may be perfectly healthy.
   ```bash
   aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Errors --dimensions Name=FunctionName,Value=<consumer> ...
   aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Throttles --dimensions Name=FunctionName,Value=<consumer> ...
   aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Duration --dimensions Name=FunctionName,Value=<consumer> ...
   ```
   - `Errors == 0` and `Throttles == 0` → **not a code crash**. Suspect retries exhausted by policy, not by bugs.
   - If `Errors > 0`, inspect `/aws/lambda/<consumer>` logs for the actual exception.

4. **Peek DLQ messages (read-only, do not delete)**
   ```bash
   aws sqs receive-message --queue-url <dlq-url> --max-number-of-messages 10 --visibility-timeout 5 --attribute-names All --message-attribute-names All --region ap-northeast-2
   ```
   - `ApproximateReceiveCount` tells how many times the message was attempted.
   - If the DLQ returns **zero messages** during investigation, first check `ApproximateNumberOfMessagesNotVisible`. **If `NotVisible > 0` and `Visible == 0`, the messages are in-flight** (another consumer holds the visibility timeout). Poll again after the queue's `VisibilityTimeout` expires, or use a longer `--visibility-timeout` to claim them briefly for inspection.
   - If still empty, they may have already been re-driven, purged, or consumed by an operator. This is common and does not invalidate the alarm.
   - Do not rely on `receive_message` as a durability check; it changes visibility.

5. **Compare main queue sent vs deleted**
   Near-parity over the alarm window means the consumer is keeping up on average; the DLQ entries are from isolated failures, not sustained overload.
   (See `references/sqs-lambda-throughput-bottleneck.md` for the exact CLI pattern.)

6. **Scope attribution**
   - Shared pipeline queues (e.g., `kinesis-record-dispatcher-queue`) carry aggregate records from all projects.
   - Lambda logs typically contain only `START/END/REPORT`.
   - Do not force a project/campaign scope. State explicitly in Korean: "프로젝트/캠페인/유저여정 특정 불가 — 인프라 공통 파이프라인".

## Deep analysis: Lambda healthy but DLQ still receives messages

When `Lambda Errors == 0`, `Throttles == 0`, and `Duration` is well below timeout, but DLQ has messages, the failure is **not in the function code**. The possible causes, in order of likelihood:

1. **Aggressive `maxReceiveCount=1`** — Any transient receive failure (cold-start network blip, brief SQS API latency) causes immediate DLQ routing with zero retries. This is by far the most common structural cause.
2. **AWS service-level message-deletion failure** — Lambda handler completes successfully, but the internal SQS `DeleteMessageBatch` call between the Lambda service and SQS fails transiently. The messages become visible again and, because `maxReceiveCount=1`, are sent to DLQ.
3. **Brief Lambda initialization failure not captured in metrics** — An extremely short-lived failure during module import or SDK initialization that resolves before CloudWatch metric aggregation. Very rare.

**Evidence-gathering limits:**
- **CloudTrail** logs only **Management** events by default. SQS `DeleteMessage`/`DeleteMessageBatch` are **Data** events and are **not** recorded unless the trail is explicitly configured with data event selectors.
- **Lambda platform logs** (`/aws/lambda/<function>`) only emit `START`, `END`, and `REPORT`. SQS trigger deletion failures are **not** written to function logs.
- **Lambda Insights / X-Ray** — if not enabled (`TracingConfig: PassThrough`), there is no additional tracing.
- **VPC Flow Logs** — even if present, they log REJECT traffic only and cannot capture HTTPS API call failures between AWS services.
- **Conclusion:** There is **no customer-visible log source** for Lambda-SQS message deletion failures. The only evidence is the outcome (DLQ messages despite Lambda success metrics).

## Known structural issue: `maxReceiveCount=1`

If the main queue redrive policy has `maxReceiveCount=1`, every single receive-failure sends the message straight to the DLQ with **no retry**. This creates DLQ noise for:
- Lambda cold-start latency breaching SQS visibility timeout
- Transient network errors during Lambda initialization
- Brief downstream dependency unavailability
- AWS service-level SQS deletion failures (see above)

**Fix target:** `infra/terraform/prod/ap-northeast-2/sqs/queues.tf` (or wherever the queue resource is defined). Raise `maxReceiveCount` from 1 to 3–5 unless the messages are truly non-idempotent and dangerous to retry.

## Representative case: `kinesis-record-dispatcher-queue-dlq`

- **Main queue:** `kinesis-record-dispatcher-queue`
- **Consumer:** `kinesis-record-dispatcher` Lambda (node22.x, 1024 MB, 300 s timeout)
- **EventSourceMapping:** `BatchSize=50`, `MaximumConcurrency` not set (defaults)
- **RedrivePolicy:** `maxReceiveCount=1`
- **Timeline:**
  - 23:15 UTC — main queue `ApproximateAgeOfOldestMessage` ALARM (peak 592 s).
  - 23:20 UTC — main queue recovers to OK.
  - 23:22 UTC — DLQ alarm fires (`ApproximateNumberOfMessagesVisible=2`).
  - Lambda `Errors=0`, `Throttles=0`, `Duration` stable (~60 ms).
- **Root cause:** transient main-queue backlog + aggressive `maxReceiveCount=1` caused 2 messages to DLQ on what was likely a single receive attempt failure.
- **Impact:** no sustained customer impact; messages were either processed from DLQ or expired; queue empty by investigation time.
- **Long-term fix:** raise `maxReceiveCount` to 3–5 in Terraform.

## Pitfalls

- Do not treat DLQ presence as proof of a Lambda bug. Always check Lambda `Errors` first.
- Do not treat empty DLQ at investigation time as a false alarm. DLQ messages are often short-lived (auto-redrive, manual purge, or consumer retry after delay).
- Do not search Lambda logs for project IDs when the queue is a shared pipeline.
- Never omit the `maxReceiveCount` value from the final answer when it is 1; it is the dominant structural cause.
