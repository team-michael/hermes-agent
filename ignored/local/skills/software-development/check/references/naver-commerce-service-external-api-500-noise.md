# Lambda ConsoleErrors — naver-commerce-service External API 500/9999

## Pattern

`naver-commerce-service lambda error` `ConsoleErrors` alarm (`%ERROR|Status: timeout%` on
`/aws/lambda/naver-commerce-service`) fires when the Naver Commerce (Naver 스마트스토어) Open API
returns transient errors during scheduled order sync.

Two co-occurring signatures per invocation:
1. `ERROR Failed to sync orders AxiosError: Request failed with status code 500 ...` (or
   `Failed to sync orders for Token <token>: AxiosError: ...`)
2. `ERROR Error fetching last changed statuses, token: <token>, error: { code: '9999', message:
   '일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요.', traceId: '...' }` (Naver's own transient-error envelope)
3. Sometimes also `ERROR Error fetching product order details, token: <token>, error: {...}` and
   `ERROR Error fetching page <n> for Token <token>: AxiosError: ...`

## Root cause

Naver Commerce API returned HTTP 500 / internal error code `9999` (Naver's own "temporary error,
please retry later" code) during the order-sync Lambda invocation. The catch blocks in
`services/lambda/naver-commerce-service/lib/services/`:
- `NaverCommerceOrderEventService.ts:40` — `console.error('Failed to sync orders', error)`
- `NaverCommerceOrderEventService.ts:70` — same, in `syncDeliveredOrdersToEvents`
- `NaverCommerceOrderService.ts:33` — `console.error(\`Failed to sync orders for Token ${token}:\`, error)`
- `NaverCommerceOrderUserService.ts:24` — `console.error('Failed to sync orders', error)`

all catch and swallow the error, returning early / an empty array. The Lambda completes normally
(`AWS/Lambda Errors = 0`, `Throttles = 0`). The coarse `%ERROR%` metric filter matches the literal
`ERROR` in the log line even though this is a handled dependency failure, not an unhandled
exception.

## Scope attribution

Logs only carry a Naver `token` (per-store OAuth credential identifier, e.g. `33jENF0iEmIrDjKZRztmB`,
`33jBQf4PKghTtikQ3CUQI`), not a Notifly `project_id`. No `project_id`/`campaign_id` appear in any
trigger context. Treat scope as **service-wide / infra-wide (외부 Naver Commerce API 의존성)**,
project/campaign unknown, unless a future log revision adds `project_id` to the error line. If
needed, the `token` could theoretically be mapped to a project via an internal Naver integration
DynamoDB table, but no such lookup has been verified yet — do not assume one exists without
checking IAM access first (cf. `cafe24_integration` access-denied precedent).

## Frequency baseline (as of 2026-07-03)

- 30d: 8 alarm transitions (2026-06-04, 06-10 x2, 06-11, 06-18, 06-21, 07-03 x2)
- Not a daily periodic job — sporadic, correlates with Naver-side transient outages, not a fixed
  clock time.
- Lambda `Errors` metric stays at 0 across all observed windows.

## Classification

- **`no_action`** when: `AWS/Lambda Errors = 0`, trigger log shows `AxiosError: ... status code
  5xx` and/or Naver `code: '9999'` (or similarly worded "일시적인 오류" temporary-error envelope),
  and the pattern is not accelerating day over day.
- **Escalate to `needs_fix`** only if: daily count climbs for multiple consecutive days, `Errors`
  metric becomes non-zero, or a specific `token`/store shows sustained sync failure across many
  hours (indicates a real Naver credential/permission issue rather than a transient blip).

## Long-term remediation (not urgent)

1. Downgrade handled Naver API failures to `console.warn`, and log only `token` + status
   code/error code, not the full Axios error object with stack trace — mirrors the
   `cafe24-token-refresher` remediation pattern.
2. Consider a dedicated EMF metric (e.g. `NaverCommerceSyncFailures`) at WARN level instead of
   reusing the generic `%ERROR%` ConsoleErrors filter, so transient upstream 5xx doesn't trip a
   critical-looking alarm.

## Bounded trace commands

```bash
# Lambda runtime errors (must be 0)
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda --metric-name Errors \
  --dimensions Name=FunctionName,Value=naver-commerce-service \
  --start-time 'YYYY-MM-DDTHH:MM:SSZ' --end-time 'YYYY-MM-DDTHH:MM:SSZ' \
  --period 60 --statistics Sum --region ap-northeast-2

# Daily ConsoleErrors sum over 30d
aws cloudwatch get-metric-statistics \
  --namespace ConsoleErrors --metric-name 'naver-commerce-service lambda error' \
  --start-time 'YYYY-MM-DDTHH:MM:SSZ' --end-time 'YYYY-MM-DDTHH:MM:SSZ' \
  --period 86400 --statistics Sum --region ap-northeast-2
```
