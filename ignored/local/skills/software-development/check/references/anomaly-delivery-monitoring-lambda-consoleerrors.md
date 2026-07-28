# anomaly-delivery-monitoring Lambda ConsoleErrors

Use this reference only after the `check` helper identifies
`anomaly-delivery-monitoring`. The helper output is the investigation plan:
do not start an independent code, Git, CloudWatch, SQS, or database survey.

## Bounded workflow

1. Run the helper once.
2. If `can_answer_root_cause` is `true`, stop investigating and answer from the
   helper evidence.
3. If it is `false`, run only the listed `required_followups`, with at most two
   tool calls total.
4. After two follow-ups, classify from the confirmed evidence and explicitly
   mark unavailable fields. Do not open another investigation branch.

The helper must not return `can_answer_root_cause: true` while a
severity-required field is missing. Treat that combination as invalid output
and rerun the helper once, not as permission for an unbounded manual survey.

Keep every log query inside the alarm window unless a listed follow-up
explicitly asks for a frequency aggregate. Never use recursive filesystem
searches or unbounded `filter-log-events`.

## Quick classifier

Always classify from the confirmed `reason:` value in the current alarm
window:

| Confirmed reason | Default judgment |
|---|---|
| `DLQ_BACKLOG_DETECTED` | `needs_fix`, disposition `hold_for_evidence` |
| `DLQ_BACKLOG_INSPECTION_FAILED` | `needs_fix`, disposition `hold_for_evidence` |
| `not aggregated nhn pending messages exist` | `no_action` when isolated and not escalating |
| `There exist messages that were scheduled but not delivered` | `no_action` when isolated and recovered |
| `high failure rate detected` | `needs_fix` |

Do not assume every `ConsoleErrors` alarm is a Lambda failure. The alarm uses
the broad metric filter `%ERROR|Status: timeout%` on
`/aws/lambda/anomaly-delivery-monitoring`; the Lambda can complete successfully
while reporting a delivery anomaly.

## Pattern 0: Structured DLQ backlog marker

```json
{
  "eventType": "DLQ_BACKLOG_DETECTED",
  "messageCount": 476,
  "queues": [
    {
      "queueName": "example-queue-dlq",
      "visibleMessageCount": 476,
      "notVisibleMessageCount": 0,
      "delayedMessageCount": 0,
      "messageCount": 476
    }
  ]
}
```

The helper parses this payload from the raw current-window row before log
sanitization and exposes:

- `dlq_backlog`: exact marker totals, every queue/depth, and bounded recurrence
  evidence.
- `dlq_disposition`: live queue depth, confirmed or inferred source queue,
  Lambda event-source consumer evidence, missing safety evidence, and the
  allowed action.
- `dlq_disposition.response_facts`: precomputed KST timestamps and the only
  facts allowed in the Slack response. Do not manually convert timestamps or
  add conclusions outside this object.
- Each queue's `redrive_capability` says only whether SQS wiring permits a move
  back to the source queue. `consumer_contract` says whether the event-source
  mapping reports partial batch failures. Neither field proves replay safety.
- Each queue's `recovery_decision` is evidence-gated: `redrive_candidate`
  requires a transient failure, idempotent replay, non-obsolescence, and
  preserved evidence; `purge_candidate` requires a terminal/permanent failure,
  confirmed obsolescence, and preserved evidence. The decision never grants
  mutation permission.
- Prefer `response_facts.queues[].depth`, sourced from current SQS attributes,
  over `marker_depth`. A prior marker can outlive a purge, expiry, or drain.
- If the 10 KB emergency fallback emits `queue_fields` plus array rows, zip
  those fields with every row and decode `queue_value_codes` before rendering;
  this preserves all queue names while removing repeated JSON keys.
- `live_sqs_observed_empty: true` means every marker queue reported zero in the
  current read-only SQS approximate snapshot. It supports `no_action` for the
  current backlog, but does not prove historical message outcomes. An alarm
  `OK` transition alone never provides even this evidence.
- `live_sqs_snapshot_complete: false` means at least one queue uses
  `marker_snapshot_fallback`; report that queue as current-state unavailable
  rather than treating the marker total as a fresh SQS observation.

Required classification:

- A currently non-empty live SQS snapshot is `needs_fix`. If a prior marker is
  non-empty but every affected queue is currently observed empty, use the
  helper's current-snapshot `no_action` without claiming historical outcomes.
- The action disposition is `hold_for_evidence` until the message outcome,
  consumer behavior, idempotency, and replay side effects are confirmed.
- A current CloudWatch state of `OK` is not resolution evidence. This
  log-derived alarm can return to `OK` between scheduled scans because missing
  data is non-breaching.
- Lambda `Errors=0` and `Throttles=0` mean the inspection Lambda ran
  successfully. They do not prove that DLQ messages are harmless.
- Do not receive, redrive, delete, purge, or replay messages automatically.
- Message age and an `Enabled` mapping never satisfy recovery safety gates.
- Do not call `receive_message` or payload inspection read-only; receiving a
  message changes visibility and requires explicit approval.
- Do not speculate that messages are stale, historical residue, safe, or tied
  to a product subtype. Use the exact queue and consumer identifiers.
- Do not call Lambda duration normal without a documented threshold or
  baseline. Runtime metrics describe the inspection Lambda, not message
  outcome.
- An `Enabled` Lambda event-source mapping proves configuration wiring, not
  consumer runtime health.
- Recurrence values are a bounded recent sample. Do not call them complete
  7-day history, all-consecutive events, or a persistence duration; report
  `event_count`, `same_as_latest_snapshot_count`, and
  `distinct_snapshot_count` separately and state continuity is unconfirmed.
- `DLQ_BACKLOG_INSPECTION_FAILED`, malformed markers, and oversized markers
  remain `needs_fix / hold_for_evidence`; report the parser/inspection failure
  without exposing raw payloads.

For the final response, list every queue's current approximate depth and marker
depth, the bounded recurrence sample, source/consumer evidence, unavailable
outcome evidence, and the read-only next action. Customer impact remains
`미확인` until delivery outcome evidence establishes otherwise.

## Pattern 1: NHN pending aggregation

```text
ERROR Anomaly delivery detected for project_id: <id>, reason: not aggregated nhn pending messages exist.
```

This reports outstanding NHN delivery-result rows awaiting aggregation. It is
a backlog signal, not by itself a Lambda crash.

- Isolated, recovered occurrence: `no_action`.
- Repeated or growing backlog across alarm windows: `needs_fix`.
- Check Lambda `Errors` and `Throttles` only when the helper lists them as
  missing required evidence.

## Pattern 2: Scheduled but not delivered

```text
ERROR Anomaly delivery detected for campaign_id: <id>, project_id: <id>, reason: There exist messages that were scheduled but not delivered, scheduledMessageCounts: <n>, messageCountsDeliveryTried: <m> <console_url>
```

The scheduler aggregate is larger than the observed delivery-attempt count.
The gap may be transient while delivery catches up.

- One window, small gap, recovered: `no_action`.
- Repeated windows, widening gap, or related downstream errors: `needs_fix`.
- Report the campaign, project, scheduled count, attempted count, and alarm
  window when present.

## Pattern 3: High failure rate

```text
ERROR Anomaly delivery detected for campaign_id: <id>, project_id: <id>, reason: high failure rate detected.
```

This is a real delivery signal. `isHighFailureRate()` checks that attempted
volume is at least 50 and that
`send_failure / messageCountsDeliveryTried` exceeds the channel threshold.

| Channel | Threshold |
|---|---:|
| Push notification, LINE, Kakao Friendtalk, Kakao Brand Message | 60% |
| Kakao Alimtalk, text message | 30% |
| Web push | 20% |
| Email and default | 5% |

Classify as `needs_fix`. Likely causes include invalid or expired provider
tokens, provider quota/capacity, APNS or FCM authentication errors, and
channel-specific payload failures. Do not name a cause that the evidence did
not confirm.

## Follow-up query

Use this only when the helper explicitly lists current log details as missing.
Replace the timestamps with a narrow alarm window, normally five minutes on
either side of `StateReasonData.startDate`.

```bash
aws logs filter-log-events \
  --log-group-name '/aws/lambda/anomaly-delivery-monitoring' \
  --region ap-northeast-2 \
  --start-time <alarm-start-minus-5m-ms> \
  --end-time <alarm-start-plus-5m-ms> \
  --filter-pattern 'ERROR' \
  --limit 100 \
  --query 'events[*].{t:timestamp,m:message}' \
  --output json
```

One bounded call should identify the current `reason:` and affected
campaign/project. Do not follow it with source-code, Git, SQS, DynamoDB, or
Athena exploration unless that second call is specifically required by the
helper.

## Frequency semantics

`history.alarm_count_*` counts alarm state transitions. It can be lower than
the number of matching log lines because one Lambda invocation can emit
multiple campaign errors before one alarm transition.

Use a log-event aggregate only when frequency is a listed required follow-up.
Keep it to one query:

```sql
fields @timestamp, @message
| filter @message like /high failure rate/
| stats count() as count by bin(1d) as day
| sort day desc
```

State clearly whether a number represents alarm transitions or log events.
Never combine them as if they were the same metric.

## Source mechanics

For scheduled-delivery analysis, the Lambda compares:

- Postgres `scheduled_message_counts`, grouped by campaign over a ten-minute
  scheduler window.
- Athena `notifly_message_events`, over the related delivery window, including
  `send_success`, `send_failure`, frequency-limit skips, pending, aborted, and
  rendering failures.

This explains the signal but does not justify querying those systems on every
alert. Use source or data-store inspection only for a separately requested
deep investigation.

## Response requirements

The final thread reply should contain:

- Current judgment: `no_action`, `needs_fix`, or `urgent`.
- Confirmed reason and affected campaign/project.
- Current-window evidence and whether the alarm recovered.
- Frequency with its exact unit: transitions or log events.
- One concrete next action.
- Any unavailable required field, after the two-follow-up limit.

Do not expose tool chatter or continue investigating after the evidence is
sufficient for this classification.
