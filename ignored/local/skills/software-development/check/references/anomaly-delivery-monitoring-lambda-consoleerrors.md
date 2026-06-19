# anomaly-delivery-monitoring Lambda ConsoleErrors — Pattern Guide

**Quick classifier** (always read `reason:` in actual log lines):
- `reason: not aggregated nhn pending messages exist` → Pattern 1 → `no_action`
- `reason: There exist messages that were scheduled but not delivered` → Pattern 2 → `no_action`
- `reason: high failure rate detected` → **Pattern 3 → `needs_fix`** (real delivery failures)

The `anomaly-delivery-monitoring` Lambda fires `ConsoleErrors` alarms via the
broad metric filter `%ERROR|Status: timeout%` on
`/aws/lambda/anomaly-delivery-monitoring`.  The Lambda itself is healthy;
runtime `AWS/Lambda` `Errors` and `Throttles` are usually zero.

**Do NOT assume all anomaly-delivery-monitoring alarms are false positives.**
Pattern 3 (`high failure rate detected`) is a real signal requiring investigation.

## Three ERROR patterns emitted by the routine

### 1. NHN pending delivery-result messages (false positive / `no_action`)

```
ERROR Anomaly delivery detected for project_id: <id>, reason: not aggregated nhn pending messages exist.
```

This indicates the `notifly-nhn-delivery-result-collector` has outstanding
`delivery_result_${projectId}` rows pending aggregation.  It is a backlog
indicator, not a Lambda crash.

### 2. Scheduled-but-not-delivered messages (false positive / `no_action`)

```
ERROR Anomaly delivery detected for campaign_id: <id>, project_id: <id>, reason: There exist messages that were scheduled but not delivered, scheduledMessageCounts: <n>, messageCountsDeliveryTried: <m> <console_url>
```

This means a scheduled campaign/user-journey has messages queued but fewer
delivery attempts than expected.  The counts show the gap size.  The Lambda
invocation completes normally after logging.

### 3. High failure rate detected (`needs_fix` — real delivery failures)

```
ERROR Anomaly delivery detected for campaign_id: <id>, project_id: <id>, reason: high failure rate detected.
https://console.notifly.tech/ko/console/products/<product>/campaign/<id>/stats?environment=1
```

This is emitted by `isHighFailureRate()` in `index.js:49-54` when
`send_failure / messageCountsDeliveryTried > CHANNEL_HIGH_FAILURE_RATE_MAP[channel]`
(or `DEFAULT_HIGH_FAILURE_RATE = 0.05` for channels not in the map) AND
`messageCountsDeliveryTried >= TOTAL_MESSAGE_COUNTS_THRESHOLD_FOR_CHECKING_HIGH_FAILURE (50)`.

**This is NOT a false positive.** It means real messages are failing at a rate
exceeding the channel threshold for the named campaign/project.

Channel thresholds (`lib/constants.js`):
- push-notification: 60%
- line: 60%
- kakao-friendtalk: 60%
- kakao-brand-message: 60%
- kakao-alimtalk: 30%
- web-push-notification: 20%
- text-message: 30%
- default / email / others: 5%

Note: two inline suppression guards in `index.js:97-108` silence this alert
for a hardcoded `project_id` and `CAMPAIGN_IDS_MAY_OCCUR_404_TOKEN_ISSUE`
(FCM 404 token issue). Bladderly and other projects without these guards will
always fire.

**Triage for this pattern:**
- `Errors=0`, `Throttles=0`, `Duration` healthy → Lambda itself is fine;
  the real issue is in the delivery pipeline for the named campaigns.
- Check actual `send_failure` causes: FCM token expiry, invalid tokens,
  provider quota exhaustion, APNS auth errors.
- Query `delivery_result_<project_id>` (Athena or Postgres) around the alarm
  window for `event_name='send_failure'` grouped by reason/error code.
- Classify as `needs_fix` when: (a) same campaign fires repeatedly across
  multiple alarm windows, or (b) the failure is new and project-owner
  notification is warranted.
- Classify as `no_action` only when: isolated single-window spike for a known
  campaign that was already suppressed in code and recovered.

**Sudden volume increase pattern:**
If this pattern appeared sporadically before (e.g. 1 event/day for 30 days)
and then spikes sharply (e.g. 24 events on one day), check `LastModified` on
the Lambda function. A deployment the previous day that changes anomaly
detection logic or thresholds is a strong contributing factor. Correlate:
1. `describe-function-configuration` → `LastModified`
2. Logs Insights daily count for `high failure rate` over 30d (`bin(1d)`)
3. Whether the campaigns involved are newly created or running continuously

## Code-level mechanics of scheduled-but-not-delivered

When the user asks "which messages" or "why are they undelivered", trace the
Lambda source (`services/lambda/anomaly-delivery-monitoring/index.js` and
`lib/db.js`) instead of guessing.

### Data sources

1. **Postgres `scheduled_message_counts`** — 10-minute aggregate table written by
the scheduler. The Lambda queries:
   ```sql
   SELECT MIN(project_id) AS project_id, campaign_id, SUM(count) AS count,
          MIN(channel) AS channel, MIN(id) AS id
   FROM scheduled_message_counts
   WHERE created_at BETWEEN to_timestamp(<cutoff>) AND to_timestamp(<cutoff+10min>)
   GROUP BY campaign_id
   ```
2. **Athena `notifly_message_events`** — delivery-attempt telemetry. The Lambda
runs an Athena query per campaign:
   ```sql
   SELECT name AS event_name, COUNT(*) AS count
   FROM notifly_message_events
   WHERE project_id = '<pid>' AND campaign_id = '<cid>'
     AND time BETWEEN <cutoff_us> AND <cutoff_us + 20min_us>
     AND name IN ('send_success', 'send_failure',
                  'skipped__global_frequency_limit_filter', 'pending',
                  'skipped__aborted_message', 'rendering_failure')
   GROUP BY name
   ```

### Time window

`timeCutoff` is computed as:
```js
NMinutesAgoInSec(Math.floor(now / TEN_MINUTES_IN_MS) * TEN_MINUTES_IN_MS, 30)
```
This means the Lambda inspects the **10-minute bucket that started 30–40 minutes
ago** (nearest prior 10-minute boundary minus 30 minutes).

### Undelivered check (`doesExistNotTriedMessage`)

```js
if (!isThrottled && scheduled > delivered)        → undelivered
if (isThrottled    && scheduled > 0 && delivered === 0) → undelivered
```
- `scheduled` = `SUM(count)` from `scheduled_message_counts`
- `delivered` = sum of all Athena event rows (any delivery-result name)
- Email channel is special-cased: when `channel === 'email'` and
  `messageCountsDeliveryTried > 0`, the code logs a `WARN` and returns early,
  because email delivery is intentionally throttled.

### What "undelivered" actually means

The gap (`scheduled - delivery_tried`) is **not** message loss. It is the
portion of messages that were scheduled into the 10-minute Postgres window but
have not yet produced a corresponding Athena `message_events` row within the
20-minute Athena look-ahead. Typical explanations:

- **Batch processing delay**: `scheduled-batch-delivery` or
  `instant-batch-scheduler` has not yet consumed the SQS work for this
campaign window.
- **Athena ingestion lag**: delivery results may have happened but not yet
  landed in `notifly_message_events`.
- **Large campaign backpressure**: campaigns with 100 k+ scheduled messages
  (e.g. `KxhxvO`, `Ha1fLS`) naturally create wider gaps simply because the
  delivery pipeline cannot complete within the 20-minute Athena window.

When asked for the root cause, state that the Lambda is a monitoring probe
comparing two async data sources, and the gap most often reflects normal batch
latency rather than a fault.

## Extracting pending counts from logs

If the user wants the list of affected campaigns and pending counts, run a
bounded CloudWatch Logs Insights query on
`/aws/lambda/anomaly-delivery-monitoring`:

```sql
fields @timestamp, @message
| filter @message like /scheduled but not delivered/
| parse @message "scheduledMessageCounts: *, messageCountsDeliveryTried: *" as scheduled, tried
| parse @message "campaign_id: *" as campaign_id
| stats count() as occurrences, max(scheduled) as max_scheduled, max(tried) as max_tried by campaign_id
| sort max_scheduled desc
```

KST timestamps in the final answer (`YYYY-MM-DD HH:mm KST`).

## Why the alarm fires

The metric filter counts any log line containing `ERROR` or
`Status: timeout`.  One Lambda run emitting 2–3 anomaly lines is enough to
cross the alarm threshold (`Sum >= 2` over 60 s with 1 datapoint to alarm).

### Structural explanation — scheduled Lambda + tight threshold

`anomaly-delivery-monitoring` is a **scheduled Lambda** (EventBridge rule,
no EventSourceMapping).  It runs on a fixed interval and each invocation
emits **two to three** `ERROR` anomaly lines when conditions are met.  The
Terraform alarm configuration is:

- `Period = 60`
- `Threshold = 2.0`
- `DatapointsToAlarm = 1`
- `EvaluationPeriods = 1`

Because `DatapointsToAlarm = 1` and the period is **1 minute**, a single
scheduled invocation that logs 2+ `ERROR` lines in any 60-second wall-clock
bucket immediately transitions the alarm to `ALARM`.  This is deterministic
metric-filter behavior, not an unexpected spike.

### Finding current trigger logs when `filter-log-events` returns empty

The scheduled Lambda creates a new log stream per invocation.  CloudWatch
Logs indexing can lag behind metric-filter evaluation, and `filter-log-events`
with `--filter-pattern 'ERROR'` often returns zero results even though the
metric filter demonstrably breached.

**Reliable fallback:** Enumerate the latest stream and read it directly.

```bash
# List most-recent stream for this Lambda
aws logs describe-log-streams \
  --region ap-northeast-2 \
  --log-group-name /aws/lambda/anomaly-delivery-monitoring \
  --order-by LastEventTime --descending --limit 5

# Then read the stream with the latest lastEventTimestamp
aws logs get-log-events \
  --region ap-northeast-2 \
  --log-group-name /aws/lambda/anomaly-delivery-monitoring \
  --log-stream-name 'YYYY/MM/DD/[$LATEST]<stream-id>'
```

This bypasses the CloudWatch Logs filter index and reads the raw events
directly, confirming the exact ERROR lines that triggered the alarm.

## Verification steps

1. Check `AWS/Lambda` `Errors` metric for `anomaly-delivery-monitoring`.
   - If `Errors > 0`, the Lambda actually crashed/timed out; investigate the
     stack trace, not the anomaly text.
2. Check `AWS/Lambda` `Throttles`.
   - If `Throttles > 0`, concurrency limits may be the real cause.
3. Check `AWS/Lambda` `Duration` (p99).
   - If p99 is near the 300 s timeout, the alarm may be a genuine timeout
     caught by the `Status: timeout` arm of the filter.
4. Inspect the actual log lines in the alarm window with `filter-log-events` on
   `/aws/lambda/anomaly-delivery-monitoring`.
   - If the only matches are the two patterns above, the alarm is metric-filter
     noise from routine logging.

## Scope extraction

The scheduled-but-not-delivered pattern carries both `campaign_id` and
`project_id`.  Map `project_id` through DynamoDB `project` for product/name.
Reporting format: `mmtalk/6VeTG3` or similar `product/campaign` pair.

When the log line contains only `project_id` (NHN pending pattern), campaign
and user journey are unknown; state this explicitly.

## Triage decision tree

First, identify which of the three patterns dominates the alarm window:

- **Pattern 1 (NHN pending)** or **Pattern 2 (scheduled but not delivered)**,
  `Errors == 0`, `Throttles == 0`, `Duration` well below 300s →
  `no_action`; track log-level downgrade as long-term fix.
- **Pattern 3 (high failure rate)**, `Errors == 0`, `Throttles == 0` →
  `needs_fix`; Lambda is healthy but real messages are failing for the named
  campaign/project. Investigate delivery failure causes.
- **Pattern 3 + sudden volume spike** (e.g. was 1/day, now 20+/day) →
  `needs_fix`; correlate with recent Lambda `LastModified` deployment.
- `Errors > 0` or `Duration` near 300s timeout with actual stack traces →
  real bug or timeout; investigate as `needs_fix` or `urgent`.
- `Throttles > 0` → investigate concurrency and event-source mapping.

**Mixed-pattern day**: a single alarm window may contain both Pattern 2 and
Pattern 3 (both can be present in the same invocation). Always check all
`reason:` values in the log stream — do not dismiss as `no_action` if any
`high failure rate detected` line is present.

## Remediation direction

Downgrade the anomaly detection logs from `ERROR` to `WARN` (or `INFO` for the
scheduled-but-not-delivered branch when the gap is within normal batching
variance).  Keep `ERROR` only when the Lambda itself encounters an unhandled
exception, SQS/Kinesis write failure, or actual provider timeout.
