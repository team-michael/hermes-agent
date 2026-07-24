# Lambda ConsoleErrors — External API 5xx False Positive

## Pattern

A Lambda `ConsoleErrors` alarm fires with a coarse metric filter such as `%ERROR|Status: timeout%`, Lambda runtime `Errors` is zero, and the triggering logs show an external provider returned HTTP 5xx (e.g., `500 Internal Server Error`).

## Root cause

The Lambda code calls an external API inside a `try...catch` block and uses `console.error(e)` to log the caught error. The full serialized HTTP-client error object (AxiosError, fetch Response, etc.) contains the literal substring `ERROR` in multiple places (`code: 'ERR_BAD_RESPONSE'`, stack trace, status text). The coarse metric filter matches this substring even though:

- The exception was caught and handled.
- The Lambda invocation completed normally.
- Lambda runtime `Errors` metric is `0`.

## Concrete example: naver-commerce-service

**Alarm**: `naver-commerce-service lambda error`  
**Metric filter**: `%ERROR|Status: timeout%`  
**Provider**: Naver Commerce API (`api.commerce.naver.com`)  
**Provider response**:
```json
{
  "code": "9999",
  "message": "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
  "traceId": "...",
  "timestamp": "..."
}
```
Also observed:
- `code: 'GW.INTERNAL_SERVER_ERROR'`, `message: '작업 중 오류가 발생하였습니다.'` with HTTP 500.
- `504 Gateway Timeout` returning an HTML error page (`일시적인 서비스 장애 입니다.`).

**Trigger log excerpt**:
```
ERROR	Error fetching product order details, token: <token>, error: {
  code: 'GW.INTERNAL_SERVER_ERROR',
  message: '작업 중 오류가 발생하였습니다.',
  traceId: '...',
  timestamp: '...'
}
ERROR	Error fetching page 1 for Token <token>: AxiosError: Request failed with status code 500
    at settle (...)
    ...
ERROR	Failed to sync orders for Token <token>: AxiosError: Request failed with status code 500
    at settle (...)
    ...
```

**Code path** (`services/lambda/naver-commerce-service/lib/services/NaverCommerceSyncService.ts`):
```typescript
try {
    // ... Naver Commerce API calls ...
} catch (e) {
    console.error(e);
}
```

## Classification

- **Immediate**: `no_action` when Lambda `Errors = 0`, the provider error indicates a transient issue, and the alarm recovers to OK within minutes.
- **Escalate to `needs_fix` only if**: the external error is sustained for hours, the same API endpoint fails across multiple provider tokens, or the `Errors` metric becomes non-zero (indicating an unhandled exception or timeout).
- **Deploy correlation**: If the Lambda `LastModified` is within hours of the alarm, verify the same signature existed before the deploy (via `filter-log-events` or Logs Insights on prior days). If the signature is historic, the deploy is likely not causal.

## Evidence to collect

1. Lambda runtime `Errors` and `Throttles` metrics for the window — must be `0`.
2. Bounded `filter-log-events` or Logs Insights query around the alarm datapoint time on `/aws/lambda/<function-name>`.
3. Confirm the `ERROR` log line originates from a caught exception (`try...catch`) and the invocation ends without a runtime failure.
4. Check the HTTP status code and provider error code — look for provider-specific transient indicators (`9999`, `Internal Server Error`, `Service Unavailable`, etc.).

## Long-term remediation

1. **Downgrade log level**: For handled external 5xx errors, use `console.warn` instead of `console.error`.
2. **Compact logging**: Log only the fields needed for operator visibility:
   - `projectId` or `productId`
   - `statusCode`
   - Provider error `code` and short `message`
   - Do **not** dump the full HTTP client error object or stack trace.
3. **Reduce metric-filter noise**: If a Lambda has many handled external-API rejections, consider whether the coarse `%ERROR|Status: timeout%` filter is the right signal for that function, or if a purpose-built metric (e.g., `ExternalAPICallFailures`) in a custom namespace would be cleaner.

## Bounded trace commands

```bash
# 1. Confirm Lambda Errors=0 in the alarm window
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=naver-commerce-service \
  --start-time '2026-05-15T19:30:00Z' \
  --end-time   '2026-05-15T20:00:00Z' \
  --period 60 --statistics Sum --region ap-northeast-2

# 2. Read ERROR logs in the alarm window
start_ms=$(date -d '2026-05-15 19:40:00 UTC' +%s)000
end_ms=$(date   -d '2026-05-15 19:50:00 UTC' +%s)000
aws logs filter-log-events \
  --region ap-northeast-2 \
  --log-group-name '/aws/lambda/naver-commerce-service' \
  --start-time "$start_ms" --end-time "$end_ms" \
  --filter-pattern 'ERROR' \
  --output json --query 'events[*].{Time:timestamp,Message:message}'
```

## Scope resolution: mapping the credential token to project_id (naver-commerce-service specific)

The trigger log carries only a Naver Commerce `Token <token>` string (e.g.
`33jBQf4PKghTtikQ3CUQI`), never a `project_id`. The helper's `scope_attribution`
will report `scope_kind: "unknown"` for this alarm family because no
`project_id`/`campaign_id` appears in the log payload. Do not stop at "scope
unknown" — the token is resolvable via a read-only DynamoDB scan.

Credentials live in DynamoDB table `external_credentials`
(`services/lambda/naver-commerce-service/lib/repositories/ExternalCredentialRepository.ts`),
keyed by `project_id` with a `platform` attribute and a nested
`credential.access_token`. Scan filtered by `platform = naver_commerce`, then
match the token prefix from the trigger log against `credential.access_token`:

```bash
set -a; source ~/.hermes/profiles/hashimoto/.env 2>/dev/null; set +a
python3 - <<'PY'
import boto3, os
session = boto3.Session(
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-2"),
)
ddb = session.client("dynamodb")
resp = ddb.scan(
    TableName="external_credentials",
    FilterExpression="#platform = :platform",
    ExpressionAttributeNames={"#platform": "platform"},
    ExpressionAttributeValues={":platform": {"S": "naver_commerce"}},
    ProjectionExpression="project_id, credential",
)
TARGET_TOKEN_PREFIX=***  # from the trigger log's "Token <token>"
for item in resp.get("Items", []):
    pid = item.get("project_id", {}).get("S")
    token = item.get("credential", {}).get("M", {}).get("access_token", {}).get("S")
    if token and token.startswith(TARGET_TOKEN_PREFIX):
        print("MATCH project_id:", pid)
PY
```

Then map the resulting `project_id` through the standard DynamoDB `project`
table lookup (`id`, `product_id`, `name`) to fill the `범위:` field. This scan
is small (tens of Naver Commerce credentials as of 2026-07) and safe to run
read-only per investigation; do not fetch full items on the `project` table
(may contain sender credentials) — use `ProjectionExpression`.
