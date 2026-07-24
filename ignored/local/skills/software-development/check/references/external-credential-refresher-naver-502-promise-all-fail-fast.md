# Lambda ConsoleErrors + Errors=1 — external-credential-refresher Naver Commerce 502 (Promise.all fail-fast)

## Pattern

`external-credential-refresher lambda error` `ConsoleErrors` alarm (`%ERROR|Status: timeout%` on
`/aws/lambda/external-credential-refresher`) fires with `AWS/Lambda Errors=1` (real invocation
failure, not just a caught log line) when Naver Commerce's own API gateway (nginx) returns HTTP
502/5xx for one `requestAuthToken(accountId)` call among the refresh batch.

Trigger log:
```
ERROR Error: HTTP error status: 502, account id: ncp_<...>, <html><head><title>502 Bad Gateway</title>...
    at NaverCommerceApiClient.requestAuthToken (/var/task/lib/clients/NaverCommerceApiClient.js:37:23)
ERROR Invoke Error {"errorType":"Error","errorMessage":"HTTP error status: 502, account id: ncp_<...>...
```

## Root cause mechanism

- `NaverCommerceApiClient.requestAuthToken()` (`lib/clients/NaverCommerceApiClient.ts:40-44`): on
  `!response.ok` (5xx), throws `Error('HTTP error status: ...')`. On 4xx it only `console.warn`s and
  returns `undefined` (handled). 5xx is NOT handled — it throws.
- `NaverCommerceRefreshService.getFreshTokens()` (`lib/services/NaverCommerceRefreshService.ts:65-76`)
  calls `requestAuthToken` for every DynamoDB `external_credentials` candidate inside a single
  `Promise.all(...)` with no per-item `.catch`. One account's 502 rejects the **entire** `Promise.all`.
- `index.ts` handler has no top-level try/catch, so the rejection propagates and the Lambda invocation
  fails (`AWS/Lambda Errors` increments by 1). **All other candidates in that batch are also dropped**
  — `flushCandidates` (the DynamoDB write-back of refreshed tokens) never runs for any candidate in the
  failed invocation, not just the one that hit 502.
- The Lambda is scheduled via EventBridge rule `every-ten-minutes` → `invoke_external_credential_refresher`
  (`infra/terraform/prod/ap-northeast-2/eventbridge/rules.tf`), so a failed batch is naturally retried
  within 10 minutes; tokens have a multi-hour TTL (`expires_in` ~10799s = ~3h) with a 10-minute refresh
  lookahead window, giving ample retry margin before actual expiry.

## Scope attribution

The failing `account id` (e.g. `ncp_2sSEyq1hAdPlz6D08qB8S`) maps to a Notifly project via DynamoDB:
```bash
aws dynamodb get-item --table-name external_credentials \
  --key '{"platform":{"S":"naver_commerce"},"id":{"S":"<account_id>"}}' \
  --projection-expression "id, project_id, product_id, platform, expires_at, last_refreshed" \
  --region ap-northeast-2
```
Then map `project_id` via the `project` table (`id`, `product_id`, `name`) as usual. Note: even though
only one account triggers the 502, the blast radius (skipped DynamoDB flush) covers **every** candidate
in that invocation's batch, not just the failing project. Report the triggering project explicitly but
note the batch-wide skip in the mechanism explanation.

## Verifying recovery

Check `last_refreshed`/`expires_at` on the same DynamoDB item after the alarm — if `last_refreshed` is
newer than the failed invocation's timestamp (usually within 1-10 minutes, matching the next scheduled
run), the retry succeeded and the token is current.

## Classification

- **`no_action`**: single sporadic 502 from Naver's gateway, `AWS/Lambda Errors` returns to 0 on the
  next scheduled run (~10 min later), and the affected project's credential `last_refreshed` shows a
  successful subsequent refresh. This is a transient upstream Naver outage, not a Notifly defect.
- **`needs_fix`**: recurs multiple times same day, escalating day over day, or a project's credential is
  observed to actually expire (delivery/sync failures downstream) because retries aren't catching up.
  The fail-fast `Promise.all` design is a legitimate hardening target regardless of urgency: wrap each
  `requestAuthToken` call with `.catch()` (like `getFreshTokens`'s existing per-candidate handled-token
  filtering) so one account's failure doesn't block refreshing/flushing every other candidate in the
  batch.

## Long-term remediation (not urgent, `needs_fix`-worthy only if recurrence increases)

1. In `NaverCommerceRefreshService.getFreshTokens`, wrap each `NaverCommerceApiClient.requestAuthToken`
   call with a per-item `.catch(() => undefined)` (mirroring the existing 4xx handling), so a single 5xx
   does not fail the whole batch.
2. Consider treating repeated 5xx for the same `account_id` (not just one-off) as WARN-worthy telemetry
   rather than ERROR, since Naver-side transient 502s are expected occasionally.

## Bounded trace commands

```bash
# Lambda runtime Errors (confirms real invocation failure vs handled log)
aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Errors \
  --dimensions Name=FunctionName,Value=external-credential-refresher \
  --start-time 'YYYY-MM-DDTHH:MM:SSZ' --end-time 'YYYY-MM-DDTHH:MM:SSZ' \
  --period 60 --statistics Sum --region ap-northeast-2

# Map failing Naver account id -> project
aws dynamodb get-item --table-name external_credentials \
  --key '{"platform":{"S":"naver_commerce"},"id":{"S":"<account_id>"}}' \
  --projection-expression "id, project_id, product_id, expires_at, last_refreshed" \
  --region ap-northeast-2
```
