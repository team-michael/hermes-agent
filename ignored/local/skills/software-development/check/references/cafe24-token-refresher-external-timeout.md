# Lambda ConsoleErrors — Cafe24 Token Refresher External Timeout

## Pattern

The `cafe24-token-refresher lambda error` `ConsoleErrors` alarm fires with metric filter `%ERROR%` (or `%ERROR|Status: timeout%`).
Lambda runtime `Errors` is `0`. The triggering log shows `ConnectTimeoutError` or `UND_ERR_CONNECT_TIMEOUT` from a `fetch` call to the Cafe24 OAuth token endpoint.

## Root cause

The Cafe24 API (`https://${mall_id}.cafe24api.com/api/v2/oauth/token`) timed out during the scheduled token-refresh Lambda invocation. The timeout is caught in `getFreshToken` (`services/lambda/cafe24-token-refresher/lib/cafe24.js:70-73`), logged with `console.error`, and the function returns `null`. The Lambda handler continues normally, flushes the other successful tokens, and exits successfully.

Because `console.error` emits the literal string `ERROR`, the coarse metric filter matches it even though:

- The exception was caught and handled.
- The invocation completed normally.
- Lambda runtime `Errors` metric is `0`.

## Concrete example

**Alarm**: `cafe24-token-refresher lambda error` (and `[CRITICAL] cafe24-token-refresher lambda error`)  
**Metric filter**: `%ERROR%` on `/aws/lambda/cafe24-token-refresher`  
**Trigger log excerpt**:
```
ERROR	Failed to get fresh token: nepro88 TypeError: fetch failed
    at async getFreshToken (/var/task/lib/cafe24.js:28:26)
    ...
  [cause]: ConnectTimeoutError: Connect Timeout Error
      (attempted addresses: 183.111.139.235:443, timeout: 10000ms)
      code: 'UND_ERR_CONNECT_TIMEOUT'
```

**Handler** (`services/lambda/cafe24-token-refresher/index.js:35-37`):
```javascript
const tokens = await Promise.all(
    candidates.map((candidate) => getFreshToken(candidate.mall_id, candidate.token.refresh_token))
);
```

**Token fetch** (`services/lambda/cafe24-token-refresher/lib/cafe24.js:27-73`):
```javascript
try {
    const response = await fetch(url, requestBody);
    // ... 404/405 handled explicitly ...
} catch (error) {
    console.error('Failed to get fresh token:', mid, error);
    return null;
}
```

## Scope attribution

The `cafe24_integration` DynamoDB table is keyed by `mall_id`. Items **do not store `project_id`** or `product_id`. Therefore scope attribution via DynamoDB is impossible for this alarm.

When a `mall_id` is known from the log (e.g., `nepro88`, `moizto97`), the corresponding project cannot be recovered from `cafe24_integration`. The alert is correctly **service-wide / Cafe24 infra-wide**.

## Frequency pattern

This is **not** a daily periodic alarm. Historical `ConsoleErrors` daily sums are typically `0` with isolated spikes:
- 30 days: 15 total (example: 2026-05-21 4, 2026-05-31 1, 2026-06-03 10)
- Spikes correlate with Cafe24 API transient outages, not Notifly deployments.

The alarm transitions are `INSUFFICIENT_DATA → ALARM` because the metric filter only produces datapoints during the scheduled invocation.

## Classification

- **Immediate**: `no_action` when Lambda `Errors = 0`, the error is a transient Cafe24 connect timeout, and the spike is not sustained.
- **Escalate to `needs_fix` only if**: daily error sum increases for multiple consecutive days, or `Errors` metric becomes non-zero (indicating unhandled exception / timeout hang).

## Evidence to collect

1. Lambda runtime `Errors` and `Throttles` metrics for the window — must be `0`.
2. Bounded `filter-log-events` on `/aws/lambda/cafe24-token-refresher` around the alarm `StateReasonData.startDate`.
3. Confirm `ERROR` log originates from `getFreshToken` catch block with `ConnectTimeoutError` or `UND_ERR_CONNECT_TIMEOUT`.
4. Check daily `ConsoleErrors` metric sum over 30 days to confirm transient spike pattern vs. sustained increase.
5. If `describe-alarm-history` is throttled, fall back to `get-metric-statistics` with `Period=86400` for daily alarm-metric sums.

## Bounded trace commands

```bash
# 1. Lambda runtime errors (must be 0)
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=cafe24-token-refresher \
  --start-time 'YYYY-MM-DDTHH:MM:SSZ' \
  --end-time   'YYYY-MM-DDTHH:MM:SSZ' \
  --period 60 --statistics Sum --region ap-northeast-2

# 2. ERROR logs in the exact alarm window
start_ms=$(date -d 'YYYY-MM-DD HH:MM:00 UTC' +%s)000
end_ms=$(date   -d 'YYYY-MM-DD HH:MM:00 UTC' +%s)000
aws logs filter-log-events \
  --region ap-northeast-2 \
  --log-group-name '/aws/lambda/cafe24-token-refresher' \
  --start-time "$start_ms" --end-time "$end_ms" \
  --filter-pattern 'ERROR' \
  --output json --query 'events[*].{Time:timestamp,Message:message}'

# 3. Daily metric sum over 30d (alarm-history throttling fallback)
aws cloudwatch get-metric-statistics \
  --region ap-northeast-2 \
  --namespace ConsoleErrors \
  --metric-name 'cafe24-token-refresher lambda error' \
  --start-time 'YYYY-MM-DDTHH:MM:SSZ' \
  --end-time   'YYYY-MM-DDTHH:MM:SSZ' \
  --period 86400 --statistics Sum
```

## Post-deletion verification

When a problematic `mall_id` is removed from `cafe24_integration` after repeated timeouts:

1. Verify deletion with `batch_get_item` on the `mall_id` keys; expect empty responses.
2. Check `ConsoleErrors` metric sums for ≥1 hour after deletion to confirm zero datapoints.
3. Note that remaining `mall_id` records (the table may still contain dozens of other tenants) can still trigger the same alarm if Cafe24 API experiences broader outages.

## Long-term remediation

1. **Downgrade log level**: For handled Cafe24 API timeouts (caught, returns `null`, continues processing), use `console.warn` instead of `console.error`.
2. **Compact logging**: Log only `mall_id`, error code (`UND_ERR_CONNECT_TIMEOUT`), and a short message. Do not dump the full `fetch` error object with stack trace.
3. **Consider a custom metric**: Replace the coarse `%ERROR%` metric filter with a purpose-built CloudWatch EMF metric (e.g., `Cafe24TokenRefreshFailures`) emitted at `WARN` level, so transient external timeouts do not trip a generic critical alarm.
