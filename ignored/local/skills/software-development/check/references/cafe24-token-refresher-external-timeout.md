# Lambda ConsoleErrors — Cafe24 Token Refresher External Timeout

## Pattern

The `cafe24-token-refresher lambda error` `ConsoleErrors` alarm fires with metric filter `%ERROR%` (or `%ERROR|Status: timeout%`).
Lambda runtime `Errors` is `0`. The triggering log shows one of the following failure modes from the Cafe24 OAuth token endpoint:

- **Variant A — Connection timeout**: `ConnectTimeoutError` / `UND_ERR_CONNECT_TIMEOUT` from a `fetch` call to `https://${mall_id}.cafe24api.com/api/v2/oauth/token`.
- **Variant B — HTML maintenance page**: Cafe24 API returns an HTML page (공지사항/점검 페이지) instead of JSON. Log shows `ERROR Failed to parse response body as JSON <mall_id> <html>...`. Occurs when Cafe24 is in scheduled or emergency maintenance and serves a notice page instead of the API response.

## Root cause

**Variant A**: The Cafe24 API (`https://${mall_id}.cafe24api.com/api/v2/oauth/token`) timed out during the scheduled token-refresh Lambda invocation. The timeout is caught in `getFreshToken` (`services/lambda/cafe24-token-refresher/lib/cafe24.js:70-73`), logged with `console.error('Failed to get fresh token:', mid, error)`, and the function returns `null`.

**Variant B**: The Cafe24 API returned an HTML maintenance/notice page (`<html><head><title>공지사항</title>...`) instead of a JSON token response. The response body cannot be parsed as JSON. The same catch block logs `console.error('Failed to parse response body as JSON', mid, <html_body>)` and returns `null`.

In both variants, the Lambda handler continues normally, collects the successful tokens, emits a WARN for failed candidates, flushes to DynamoDB, and exits successfully. Because `console.error` emits the literal string `ERROR`, the coarse metric filter matches it even though:

- The exception was caught and handled.
- The invocation completed normally.
- Lambda runtime `Errors` metric is `0`.

## Concrete examples

### Variant A — Connection timeout

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

### Variant B — HTML maintenance page

**Alarm**: `cafe24-token-refresher lambda error`  
**Trigger log excerpt** (2026-06-22 16:10 KST):
```
ERROR	Failed to parse response body as JSON e650728 <html>
<head>
    <title>공지사항</title>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
    ...
```
**Accompanying WARN** (same invocation):
```
WARN	Some candidates failed to refresh access token.
WARN	Failed candidates: [{"mall_id":"looklikeme","status":"token_issued",...}]
```
Got 51 fresh tokens successfully; 1 mall failed. Lambda completed normally in 4.3s.

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

The `cafe24_integration` DynamoDB table is keyed by `mall_id`. Most items **do not store `project_id`** or `product_id` — only items where Cafe24 integration setup was completed (`status: completed`) tend to have `project_id`. Items at `status: token_issued` (integration setup incomplete) typically lack `project_id`.

Therefore scope attribution via DynamoDB is usually impossible for this alarm. When a `mall_id` is known from the log (e.g., `nepro88`, `moizto97`, `looklikeme`, `e650728`), the corresponding project often cannot be recovered from `cafe24_integration`. The alert is correctly **service-wide / Cafe24 infra-wide** in these cases.

**Quick check**: `aws dynamodb get-item --table-name cafe24_integration --key '{"mall_id":{"S":"<mall_id>"}}'` — if `project_id` is absent from the response, scope is unknown.

## IAM access limitation

The monitoring IAM role does NOT have dynamodb:Scan or dynamodb:GetItem permission on cafe24_integration. Do not attempt DynamoDB lookups for this alarm — AccessDeniedException will be returned. Scope is always service-wide / Cafe24 infra-wide unless a project_id appears directly in the Lambda log payload (rare).

## Rapid-cycling pattern

When Cafe24 API has a sustained connectivity issue (e.g., 60+ minutes of ConnectTimeoutError for the same mall_id), the alarm cycles INSUFFICIENT_DATA to ALARM and back every ~10 minutes because the Lambda runs on a ~10-minute EventBridge schedule and each invocation hits the same timeout. The helper rapid_recurrence.status will be rapid with alarm_count_within_10m: 2. This is expected for sustained Cafe24 API outages and does NOT change the no_action classification — each invocation completes normally (Duration ~10.9s, Errors=0), the old token remains valid, and no data is lost. Only escalate to needs_fix if the rapid cycling persists across multiple days or Errors metric becomes non-zero.

## Frequency pattern

This is **not** a daily periodic alarm. Historical `ConsoleErrors` daily sums are typically `0` with isolated spikes:
- 30 days: 26 total (2026-06-03 20건, 2026-06-04 4건, 2026-05-31 1건, 2026-06-22 1건)
- Variant A (timeout) and Variant B (HTML page) both correlate with Cafe24 API transient outages, not Notifly deployments.

The alarm transitions are `INSUFFICIENT_DATA → ALARM` because the metric filter only produces datapoints during the scheduled invocation.

## Classification

- **Immediate**: `no_action` when Lambda `Errors = 0`, the error is a transient Cafe24 API failure (timeout or HTML maintenance page), and the spike is not sustained across multiple days.
- **Escalate to `needs_fix` only if**: daily error sum increases for multiple consecutive days, or `Errors` metric becomes non-zero (indicating unhandled exception / timeout hang).

## Evidence to collect

1. Lambda runtime `Errors` and `Throttles` metrics for the window — must be `0`.
2. Bounded `filter-log-events` on `/aws/lambda/cafe24-token-refresher` around the alarm `StateReasonData.startDate`.
3. Identify which variant fired:
   - **Variant A**: `ERROR` log contains `ConnectTimeoutError` / `UND_ERR_CONNECT_TIMEOUT`.
   - **Variant B**: `ERROR` log contains `Failed to parse response body as JSON <mall_id> <html>`.
4. Note `mall_id` from ERROR/WARN lines; check `cafe24_integration` DynamoDB for `project_id` (most items lack it — scope is infra-wide).
5. Check daily `ConsoleErrors` metric sum over 30 days to confirm transient spike pattern vs. sustained increase.

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
