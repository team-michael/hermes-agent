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
| `not aggregated nhn pending messages exist` | `no_action` when isolated and not escalating |
| `There exist messages that were scheduled but not delivered` | `no_action` when isolated and recovered |
| `high failure rate detected` | `needs_fix` |

Do not assume every `ConsoleErrors` alarm is a Lambda failure. The alarm uses
the broad metric filter `%ERROR|Status: timeout%` on
`/aws/lambda/anomaly-delivery-monitoring`; the Lambda can complete successfully
while reporting a delivery anomaly.

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
