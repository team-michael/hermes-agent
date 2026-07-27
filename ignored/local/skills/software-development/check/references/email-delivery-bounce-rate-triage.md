# Email-Delivery `blocked due to bounce rate` Alarm

Session: 2026-05-16  
Alarm: `email-delivery blocked due to bounce rate`  
Namespace: `EmailBlockDueToBounce`  
Metric filter: `%EMAIL_CB_TRIGGERED%` on `/aws/lambda/email-delivery`  

## What the alarm fires on

The metric filter matches `EMAIL_CB_TRIGGERED` log events emitted by the `email-delivery` Lambda when a project's email bounce rate exceeds a provider-side threshold. The Lambda inserts a `delivery_result_<project_id>` record with `event_name: email_send_blocked_bounce` and a companion `delivery_failure_log_<project_id>` row, then emits the `EMAIL_CB_TRIGGERED` structured log.

Example trigger log:
```
INFO {"event":"EMAIL_CB_TRIGGERED","email_send_blocked_bounce":{
  "event":"email_send_blocked_bounce",
  "campaign_id":"ifrxyr",
  "bounce_rate":0.0693,
  "send_count":"101",
  "triggered_at":"...",
  "project_id":"cb0bf8882d145a6d81e466687caa8791",
  "reason":"bounce_rate_exceeded_threshold",
  "message":"Email sending paused due to high bounce rate"
}}
```

Key fields for triage:
- `project_id` — always present; map via DynamoDB `project` table.
- `campaign_id` — present but **may refer to a user journey**, not a campaign. Always verify `resource_type` in the companion `delivery_result` insert.
- `send_count` — string-encoded integer (e.g., `"101"`). This is the number of recipients whose email was blocked in that batch.
- `bounce_rate` — actual measured bounce rate (may be well below 50%); the alarm threshold is on the count of `EMAIL_CB_TRIGGERED` events (`Sum > 50` in 5m), not on the bounce rate itself.

## Calculating blocked recipients

`EMAIL_CB_TRIGGERED` events carry `send_count` per batch. Multiply event count by `send_count` to get total blocked recipients in the alarm window.

```bash
# Example: 70 events × 101 send_count = 7,070 blocked recipients
```

When asked "how many were not sent", do not report just the event count (70); report the aggregated `send_count` sum (7,070).

## Scope — campaign vs user_journey pitfall

The `campaign_id` field name is historical and does **not** guarantee the resource is a campaign. The `delivery_result` insert lines show the actual `resource_type`:

```
SendResultsInsertQuery: INSERT INTO delivery_result_<project_id>
  (... campaign_id, variant_id, resource_type, channel)
VALUES ('...', 'ifrxyr', 'L1SoCe', 'user_journey', 'email');
```

When `resource_type = 'user_journey'`, the correct scope is a **user journey**, not a campaign.

### Verification steps
1. If `campaign_id`/`user_journey_id` from logs looks like a campaign, query `campaigns_<project_id>` first:
   ```sql
   SELECT id, name, status FROM campaigns_<project_id> WHERE id = '<id>';
   ```
2. If the table exists but returns **zero rows**, the resource is **not** a deleted campaign — it is likely a user journey. Query `user_journeys_<project_id>`:
   ```sql
   SELECT id, name, status FROM user_journeys_<project_id> WHERE id = '<id>';
   ```
3. Use the name and status from whichever table returns a row. Report `user_journey` scope explicitly in the final answer.

**Do not** tell the user the campaign was deleted merely because `campaigns_*` has no matching row. The resource may be an active user journey.

## Classification guidance

- `no_action` is correct when:
  - The trigger shows a single campaign with bounce rate > 5% on a single day.
  - `email-delivery` Lambda Runtime `Errors` are zero and SES account status is `HEALTHY`.
  - The alarm is a sporadic single-campaign spike (different campaigns on different days), indicating an intentional circuit breaker operating as designed.
- `needs_fix` is only appropriate when the same project/campaign triggers repeatedly over multiple days with escalating blocked send counts, indicating stale/low-quality email lists that the customer has not cleaned.
- This alarm counts circuit-breaker events (`Sum > 50` in 5 minutes), not a catastrophic SES account failure. The metric line is `INFO`, not `ERROR`.
- See `email-delivery-bounce-rate-circuit-breaker.md` for full historical baseline and Terraform source.

## Terraform / code locations

- `infra/terraform/prod/ap-northeast-2/lambda/functions.tf` lines ~1411, 1443: alarm and metric filter definitions for `email-delivery`.
- Metric filter pattern: `%EMAIL_CB_TRIGGERED%`
- Alarm threshold: `Sum > 50.0` over 300s (5-minute period).