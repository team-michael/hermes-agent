# Lambda Alarm Name to Function Name Mapping Gaps

Notifly alarm names that reference a Lambda service may include priority tiers or
other suffixes that do not match the actual Lambda function name.

## Known mismatch

| Alarm name contains | Assumed function (helper) | Actual function |
|---------------------|---------------------------|-----------------|
| `ScheduledBatchDelivery-P2-...` | `ScheduledBatchDelivery-P2` | `scheduled-batch-delivery` |

The `-P2` suffix refers to a delivery priority tier within the same Lambda, not
a separate deployed function.

## Pitfalls

- The helper naively extracts the alarm-name prefix as a Lambda name; when that
  mismatches, the Lambda collector fails with `ResourceNotFoundException`.
- The actual log group is `/aws/lambda/<actual_name>`, not the alarm prefix.
- The metric namespace (`Notifly/ScheduledBatchDelivery`) is emitted by the base
  function across all priority tiers.

## Manual fallback when the helper Lambda collector fails

1. List Lambdas with `aws lambda list-functions` and filter for the base
   service name (e.g., `scheduled-batch`).
2. Check `LastModified` on the real function against the alarm window. A deploy
   near an alarm transition is worth investigating even for recurring alerts.
3. Use the real function name for:
   - `aws lambda get-function-configuration`
   - CloudWatch `AWS/Lambda` Duration/Errors/Throttles metrics
   - Log group `/aws/lambda/<real_name>`
4. Correlate deploys to spikes before concluding the alert is routine baseline.
