# Email Delivery Bounce Rate Circuit Breaker (EmailBlockDueToBounce)

Alarm: `email-delivery blocked due to bounce rate`
Namespace: `EmailBlockDueToBounce`
Metric filter: `%EMAIL_CB_TRIGGERED%` on `/aws/lambda/email-delivery`
Metric name: `email-delivery blocked due to bounce rate`

## Alarm behavior
- `Statistic`: `Sum`, `Period`: 300s, `EvaluationPeriods`: 1, `DatapointsToAlarm`: 1, `Threshold`: 50.0
- `TreatMissingData`: `missing`
- The alarm cycles `OK <-> INSUFFICIENT_DATA` when the metric is absent or zero, and transitions `OK -> ALARM` only when `Sum > 50` during a single 5-minute period.
- Trigger count 50 means at least 50 separate SQS batch invocations hit the bounce-rate threshold in 5 minutes, not a single fatal error.

## What triggers the metric
The `email-delivery` Lambda (`services/lambda/email-delivery/lib/send_email.js:89-95`) computes `campaignBounceRate` before sending each batch. If `sendCount > 100 && campaignBounceRate > 0.05`, it logs a structured INFO event:

```json
{
  "event": "EMAIL_CB_TRIGGERED",
  "email_send_blocked_bounce": {
    "campaign_id": "<id>",
    "bounce_rate": 0.056,
    "send_count": "5750",
    "triggered_at": "...",
    "project_id": "<id>",
    "reason": "bounce_rate_exceeded_threshold",
    "message": "Email sending paused due to high bounce rate"
  }
}
```

The EMF metric filter `%EMAIL_CB_TRIGGERED%` counts each such log line as 1.

## Scope extraction from trigger logs
The log stream events are structured and carry explicit IDs:
- `email_send_blocked_bounce.project_id` — required. Map via DynamoDB `project` table.
- `email_send_blocked_bounce.campaign_id` — required.
- `email_send_blocked_bounce.bounce_rate` — decimal (e.g. 0.056 = 5.6%).
- `email_send_blocked_bounce.send_count` — string-form integer of total attempted sends.

The same Lambda invocation also writes `delivery_result_<project_id>` and `delivery_failure_log_<project_id>` rows with `event_name: email_send_blocked_bounce`.

**Pitfall — Postgres sharded campaign lookup may return empty for valid campaigns**: The `campaigns_<project_id>` shard table may not contain every campaign ID that appears in Lambda logs (e.g., `8slb3k` returned empty in `campaigns_0c61d690...` while `i5oPIt` in the same shard succeeded). When the sharded lookup fails, trust the Lambda `EMAIL_CB_TRIGGERED` log as the authoritative scope source rather than concluding the campaign is deleted. Do not force a Postgres lookup if the log already supplies `project_id` and `campaign_id`.

## Investigation when the helper fails
The helper text parser does not detect `email-delivery blocked due to bounce rate` because it lacks heuristics for custom-namespace alarm names and the `blocked due to bounce` phrasing.

Manual trace (bounded, read-only):
1. `aws cloudwatch describe-alarms --query 'MetricAlarms[?contains(AlarmName, \`bounce\`)].{Name:AlarmName,Namespace:Namespace,MetricName:MetricName,StateValue:StateValue,StateReason:StateReason,Threshold:Threshold,EvaluationPeriods:EvaluationPeriods,Period:Period}' --output json`
2. From alarm metadata, extract `StateReasonData.startDate` / `recentDatapoints[].timestamp`.
3. `aws logs describe-log-streams --log-group-name '/aws/lambda/email-delivery' --order-by LastEventTime --descending --limit 15`
4. `aws logs get-log-events` on streams active during the alarm window (tail-first).
5. Search for `EMAIL_CB_TRIGGERED` in the returned events.
6. Map `project_id` via DynamoDB `project` table.
7. Optionally cross-check `aws sesv2 get-account` (or `aws ses get-send-statistics`) for SES account health and `Bounces` vs `DeliveryAttempts` in the same window.

## Classification rules
- This is an **intentional circuit breaker**, not a service fault. The Lambda completes normally; Runtime `Errors = 0`.
- The `email_send_blocked_bounce` event is logged at `INFO` level, not `ERROR`.
- `no_action` is correct when:
  - The trigger shows a single campaign with bounce rate > 5%.
  - `email-delivery` Lambda Errors are zero.
  - SES account status is `HEALTHY`.
  - The campaign is not an internal test project (i.e., actual customer campaign).
- `needs_fix` is only appropriate when the same campaign or project triggers repeatedly over multiple days with escalating blocked send counts, indicating stale/low-quality email lists that the customer has not cleaned.

## Multi-campaign sequential firing pattern
On a single day the same project can trigger the circuit breaker across **multiple campaigns** in sequence, not just one. Example (2026-06-05):
- `i5oPIt` → `pZKtr6` → `8slb3k`, all under `sconn`, all with bounce rate > 5%.
When this occurs, the root cause is **project-level email list hygiene** (stale or low-quality addresses shared across campaigns), not an isolated bad template or audience segment.

## Reclassification guidance
- `no_action` when:
  - A **single** campaign triggers on a single day.
  - `email-delivery` Lambda Errors are zero.
  - SES account status is `HEALTHY`.
- `needs_fix` when **either**:
  - The **same project** triggers across **multiple campaigns on the same day** (sequential multi-campaign pattern above).
  - The same project triggers on **3+ days within 7 days**.
  - The metric transitions exceed `1d: 3` or show consecutive-day recurrence.
  In these cases, the bounce-rate circuit breaker is still functioning correctly, but the underlying list quality is deteriorating and real customer delivery work is being blocked for hours. Track as a customer-success / list-hygiene follow-up.

## Historical baseline
The `EmailBlockDueToBounce` metric existed before the alarm was created. Daily Sum from `get-metric-statistics` (Period=86400) shows sporadic spike days:
- 2026-05-08: 1,389
- 2026-05-10: 482
- 2026-05-16: 1,347
- 2026-05-29: 341 (first day the alarm fired after creation)
- 2026-06-01: 2 transitions (sconn campaigns)
- 2026-06-05: 5 transitions (sconn campaigns `i5oPIt`, `pZKtr6`, `8slb3k`)

Between spike days the metric is typically 0–3/day. A single spike day for one campaign is normal operational behavior. A single day with 3+ transitions for the same project is the multi-campaign sequential pattern.

## Known Terraform source
- `infra/terraform/prod/ap-northeast-2/lambda/functions.tf` — `email-delivery` Lambda inventory entry
- Metric alarm spec: `metric_alarm_details["email-delivery blocked due to bounce rate"]`
- Metric filter spec: `metric_filters["email-delivery blocked due to bounce rate"]` with `filter_pattern: "%EMAIL_CB_TRIGGERED%"`
