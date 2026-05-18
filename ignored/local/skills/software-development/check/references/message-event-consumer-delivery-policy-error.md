# message-event-consumer delivery policy error → ConsoleErrors false positive

## Symptom

CloudWatch alarm `message-event-consumer lambda error` (namespace `ConsoleErrors`, metric `message-event-consumer lambda error`) fires with 1–3 datapoints. The `AWS/Lambda` `Errors` metric is zero.

## Triggering log shape

The `message-event-consumer` Lambda emits:

```
ERROR\tInvalid Campaign Information {
  id: '<uuid>',
  type: 'MessageEvent',
  project_id: '<hex32>',
  resource_type: 'campaign',
  campaign_id: '<base62>',
  name: 'send_failure',
  time: <epoch_us>,
  notifly_user_id: '<hex32>',
  notifly_device_id: '<hex32>',
  event_params: {
    failure_reason: 'delivery_policy_inspection_failed__global_frequency_limit'
  },
  dt: 'YYYY-MM-DD',
  h: 'HH',
  pre_conversion: 'false'
}
```

This is a **planned business rejection**: the campaign has reached its global frequency limit, so the message is intentionally not sent. The Lambda continues processing normally after logging the rejection.

## Distinguishing from a real Lambda bug

- `AWS/Lambda` `Errors` (Sum) is **zero** for the function.
- `AWS/Lambda` `Throttles` is zero.
- `AWS/Lambda` `Duration` is normal (no timeout spikes).
- Log lines contain `Invalid Campaign Information` with `failure_reason: 'delivery_policy_inspection_failed__global_frequency_limit'`.
- The Lambda invocation ends normally; no `REPORT ... Status: timeout` or unhandled exception follows.

## Scope extraction

The structured payload carries both `project_id` and `campaign_id`:
1. Map `project_id` through DynamoDB `project` table for product/name.
2. Report as `product/campaign` pairs, e.g. `teuida-v2/sgyDeV`, `regather/uaZpu7`, `datepop/0eRBeD`.

Do not report user journey for this pattern; `resource_type: 'campaign'` is explicit.

## Alarm mechanics

The `ConsoleErrors` metric filter on `/aws/lambda/message-event-consumer` uses the broad pattern `%ERROR|Status: timeout%`. The literal string `ERROR` in the log line matches even though the failure is a handled policy outcome. Because `Threshold: 1.0` with `EvaluationPeriods: 1` and `Period: 60`, a single burst of 2–3 frequency-limit rejections crosses the threshold instantly.

## Customer impact

No direct customer impact. Messages were intentionally suppressed by the global frequency limit policy, which is the expected behavior. The only operational cost is alert noise.

## Triage decision

- `Errors == 0`, `Throttles == 0`, normal `Duration`, and only the `delivery_policy_inspection_failed__global_frequency_limit` pattern → `no_action`.
- If `Errors > 0` or timeout `REPORT` lines coexist → investigate as real bug (`needs_fix` or `urgent`).

## Bounded verification commands

```bash
# Lambda runtime Errors for past 7 days
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda --metric-name Errors \
  --dimensions Name=FunctionName,Value=message-event-consumer \
  --start-time 2026-05-08T00:00:00Z --end-time 2026-05-15T03:30:00Z \
  --period 86400 --statistics Sum --region ap-northeast-2

# Current alarm window logs (use exact StateReasonData.startDate epoch ms)
aws logs filter-log-events \
  --log-group-name /aws/lambda/message-event-consumer \
  --start-time 1778812800000 --end-time 1778814600000 \
  --filter-pattern '"Invalid Campaign Information" "send_failure"' \
  --region ap-northeast-2

# Check for timeout REPORT lines in the same window
aws logs filter-log-events \
  --log-group-name /aws/lambda/message-event-consumer \
  --start-time 1778812800000 --end-time 1778814600000 \
  --filter-pattern 'Status: timeout' \
  --region ap-northeast-2
```

## Remediation direction

Downgrade the `Invalid Campaign Information` log from `ERROR` to `WARN` (or `INFO`) inside the `message-event-consumer` delivery-policy validation path. The log should remain operator-visible because it indicates a campaign stopped sending due to frequency limits, but it does not represent a service fault.

Keep `ERROR` only for actual service failures: DB write errors, unexpected exceptions, malformed event payloads that cannot be parsed, or Kinesis processing failures.
