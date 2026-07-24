# cafe24-worker DLQ selective redrive

Session-derived note for `cafe24-worker-queue-dlq`.

## Use case

Use this when the DLQ contains a mix of Cafe24 mall retries and you want to redrive only the entries whose external backoff has already expired.

## Preferred redrive method: `start_message_move_task`

Use `sqs.start_message_move_task` (AWS SDK v3 / boto3) instead of manual `receive_message` + `send_message` loops. This is a server-side move that:

- Does not change message visibility or require receiving messages into a client.
- Handles the full DLQ batch in a single API call.
- Is the AWS-recommended DLQ redrive approach.
- Works when `RedriveAllowPolicy` on the DLQ permits the source queue (check with `get_queue_attributes` on the DLQ).

```python
import boto3
sqs = boto3.client("sqs", region_name="ap-northeast-2")
resp = sqs.start_message_move_task(
    SourceArn="arn:aws:sqs:ap-northeast-2:702197142747:cafe24-worker-queue-dlq",
    DestinationArn="arn:aws:sqs:ap-northeast-2:702197142747:cafe24-worker-queue"
)
# resp["TaskHandle"] is the task ID for cancellation/monitoring
```

The move is near-instant for small DLQs (hundreds of messages). For larger DLQs, poll both queue depths every 5-10 seconds until DLQ reaches 0.

**Pitfall**: `start_message_move_task` does NOT support filtering by `mall_id` or any message attribute. It moves ALL messages from the DLQ. If the DLQ contains mixed malls and one is still rate-limited, use the manual selective pattern below instead.

## Pre-redrive safety checks

Before redriving, verify ALL of the following:

1. **Rate-limited event volume is declining or stable**: Compare rate-limited count per 5-min window for the last 30 minutes. If the trend is flat or decreasing, redrive is safe. If still increasing, wait.
2. **Main queue depth = 0**: The consumer is keeping up with current traffic. If main queue has backlog, redriving more messages will worsen contention.
3. **DLQ depth is stable (not growing)**: Check DLQ `ApproximateNumberOfMessagesVisible` at 5-minute intervals. If flat for 15+ minutes, the burst has passed.
4. **Lambda `Errors=0` and `Throttles=0`**: Confirms no runtime failure, only rate-limit exhaustion.
5. **Last rate-limited event timestamp**: If the most recent `rate-limited` log is >15 minutes ago, the Cafe24 API quota window has likely reset.

If all checks pass, redrive is safe even when intermittent rate-limit events are still occurring — the Lambda retry mechanism (3x with 30s wait) will handle them successfully.

## Post-redrive verification

After `start_message_move_task`:

1. **DLQ depth → 0**: Should drain within seconds for small DLQs.
2. **Main queue depth → 0**: Lambda consumes redrived messages immediately. A brief spike is normal; sustained backlog indicates the rate-limit is still active.
3. **Main queue `NumberOfMessagesSent` spike**: A burst (e.g., 420 in one minute vs ~30 baseline) confirms the redrive reached the main queue.
4. **Main queue `NumberOfMessagesDeleted` ≈ `Sent`**: Parity means all redrived messages were processed successfully.
5. **DLQ stays at 0 for 10+ minutes**: Confirms the rate-limit window has passed and redrived messages are not cycling back.
6. **Lambda `Duration`**: May show ~35s spikes (30s retry wait + API call) if rate-limit retries occur, but messages still complete successfully.

## Manual selective redrive (when `start_message_move_task` is not safe)

Use this when the DLQ contains mixed malls and some are still rate-limited.

1. Sample DLQ message bodies with `receive_message` only to identify `mall_id` and `command`.
2. Group by `mall_id`.
3. Check the current `cafe24-worker` log stream for the latest `Backoff set for <mall_id>: 600s` / `rate limited` event.
4. Redrive only the `mall_id`s whose backoff window has already elapsed and whose current logs are no longer rate-limited.
5. After send/delete completion, verify:
   - DLQ visible count drops to zero for the selected cohort.
   - source queue in-flight count may spike temporarily because messages were re-enqueued for replay.

## Important caveats

- Do **not** purge the DLQ before attribution; the payload is the easiest way to recover `mall_id` scope.
- Do **not** redrive all DLQ messages blindly if the rate-limit window is still active; they will just cycle back toward DLQ.
- If multiple malls are present, keep them separated so one healthy mall does not inherit another mall’s retry flood.
- When a redrive is intentionally partial, document the skipped malls and the reason (`backoff still active`, `unknown mall`, `malformed body`).

## Recommended verification

- `aws sqs get-queue-attributes` on both DLQ and source queue after the operation.
- Lambda logs for `cafe24-worker` to confirm whether the selected mall resumed `Successfully added user ... with notifly` events.
- If the latest log still shows `rate limited` for a mall, leave that mall in DLQ until the backoff expires.
