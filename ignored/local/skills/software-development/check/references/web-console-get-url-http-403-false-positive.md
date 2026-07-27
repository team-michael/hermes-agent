# web-console `get_url` HTTP 403 False Positive

## Pattern

`web-console` metric filter `%ERROR|Exception%` matches `Error: HTTP error! status: 403` thrown from the `/api/get_url` Next.js API route (`pages/api/get_url.js`). The stack trace frame is:

```
at Array.<anonymous> (/app/services/server/web-console/.next/server/pages/api/get_url.js:1:2911)
```

## Root cause

The `get_url` endpoint fetches arbitrary user-provided URLs for preview/validation (e.g. Kakao BizMessage image URL, mobile-web link, or other campaign asset). If the remote origin returns HTTP 403 Forbidden, the internal fetch throws `HTTP error! status: <n>` matching the coarse metric filter.

Relevant source: `services/server/web-console/src/utils/db.ts` lines 19/40/60/122 (and any other client utility that wraps `fetch` with a generic `throw new Error(\`HTTP error! status: ${response.status}\`)`).

## Cross-reference

The same `web-console console error` alarm can also fire on unrelated handled rejection patterns within the same day (e.g., Kakao BizMessage `FailedToUploadImageException`, LiquidJS `abort_message()`, Sentry pipeline rejections). Do not assume historical `top_signatures` or `trigger_contexts` represent the current transition. Verify the exact most recent `OK -> ALARM` transition via bounded Logs Insights anchored to `StateReasonData.startDate`. See:

- `web-console-kakao-image-upload-validation-error.md`
- `web-console-liquidjs-abort-message-false-positive.md`
- `sentry-email-alert-pipeline-false-positives.md`

## Scope attribution via access log Referer

When `get_url` errors are the trigger, the access log in the same alarm window contains both project and campaign scope in the `Referer` header:

```
POST /api/get_url HTTP/1.1" 500 35 "https://console.notifly.tech/console/products/stepup/campaign/create?environment=1&id=M9wxrR&mode=edit"
```

- Project: extract `<productId>` from `/console/products/<productId>/...` (e.g. `stepup`).
- Campaign ID: extract `id=<campaignId>` from query string (e.g. `M9wxrR`).
- Map via DynamoDB `project` table GSI `product_id-project_id-index`, then confirm in Postgres `campaigns_<project_id>`.

## Classification

`no_action` when isolated to a single session. This is a handled external-service rejection that propagates as an unhandled exception to the client, tripping the broad metric filter. No customer-facing delivery impact; the campaign editor user sees a failed preview/validation.

## Remediation

- Log-level: downgrade `get_url` 4xx responses to `WARN` with compact context (target URL, status code) rather than unhandled `Error`.
- Metric filter: consider narrowing the web-console console filter to exclude known handled business-rejection endpoints, or add `get_url` to safe patterns. Alternatively, return a structured response for 4xx fetch failures instead of throwing.
