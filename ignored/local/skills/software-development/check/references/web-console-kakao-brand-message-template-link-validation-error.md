# Web-Console Kakao Brand Message Template Link Validation Error

**Alarm**: `/aws/ecs/notifly-services-prod/web-console console error`
**Metric filter**: `%ERROR|Exception%`

## Error signature

```
Error: 템플릿 링크 검증 실패:
[모바일 웹 링크] 유효하지 않은 링크입니다: <url>
```

Concrete example observed 2026-06-24 (class101, user journey `Vh3QwP`):
```
Error: 템플릿 링크 검증 실패:
[모바일 웹 링크] 유효하지 않은 링크입니다: class101.net
```
The user entered `class101.net` (bare domain without `https://` protocol) as a mobile web link in a Kakao brand message template. Kakao requires fully-qualified URLs with `http://` or `https://` prefix.

The stack trace shows frames in:
- `KakaoBrandMessageTransformer.inline` (`services/server/web-console/.next/server/chunks/71260.js`)
- `KakaoBrandMessageTransformer.transform` (same file)
- `POST /api/projects/[projectId]/test_send/kakao_brand_message` handler

## Root cause

`KakaoBrandMessageTransformer.inline()` calls `validateResolvedTemplateLinks()` on the resolved template content before sending it to the Kakao API:

```typescript
const linkErrors = validateResolvedTemplateLinks(message.template.content, effectiveParams);
if (linkErrors.length > 0) {
    throw new Error(`템플릿 링크 검증 실패:\n${linkErrors.join('\n')}`);
}
```

If the campaign template contains an invalid mobile web link (e.g., malformed URL, unreachable domain, unsupported protocol), this error is thrown. The error propagates out of `KakaoBrandMessageTransformer.transform()` and is caught in the API handler:

File: `services/server/web-console/src/pages/api/projects/[projectId]/test_send/kakao_brand_message.ts`

```typescript
try {
    await queueTestKakaoBrandMessage({ ... });
    return res.status(201).json({ ... });
} catch (error) {
    console.error(error);          // ← ERROR-level log trips metric filter
    return res.status(400).json({  // ← this catch only covers queueTestKakaoBrandMessage, NOT transform()
        error: 'Invalid request data',
        details: error.message,
    });
}
```

**Important**: `KakaoBrandMessageTransformer.transform()` (which calls `validateResolvedTemplateLinks`) is called **before** the `try` block, so the validation error is **not** caught by this catch. It propagates as an unhandled error → Next.js returns 500 and logs `console.error` via `@sentry/core` `handleCallbackErrors`. The `res.status(400)` path only fires for errors inside `queueTestKakaoBrandMessage`.

The request returns **HTTP 500** (not 400) because `KakaoBrandMessageTransformer.transform()` is called **outside** the `try` block in the handler (see Remediation direction below). The unhandled error propagates to Next.js's error handler, which logs `console.error(error)` (matching the `%ERROR|Exception%` metric filter) and returns 500. Some successful test-sends in the same session return 201; only the ones with invalid links return 500.

## What it is NOT

- Not a Kakao API error — this validation runs **before** any external API call
- Not a service bug — it is user input validation
- Not a code crash — the web-console ECS task continues normally

## Scope recovery

The error log trace frame shows the Next.js parameterized route `/api/projects/[projectId]/test_send/kakao_brand_message.js` — the resolved `project_id` is **not** in the error log. It is in the HTTP access log for the same request:

```
POST /api/projects/<project_id>/test_send/kakao_brand_message HTTP/1.1
```

Also, the `Referer` header in the access log contains one of these patterns:

```
https://console.notifly.tech/console/products/<productId>/campaign/create?...&id=<campaignId>&mode=edit
https://console.notifly.tech/console/products/<productId>/user-journey/<userJourneyId>/edit?...
```

Extract `<productId>` from the Referer and `<project_id>` from the path parameter. Map `<productId>` via DynamoDB `project` table GSI `product_id-project_id-index`. Note the same `product_id` may map to multiple `project.id` values. The user-journey variant is common when a console user tests a Kakao brand message node inside a user journey editor.

**Multi-stream pitfall**: web-console runs multiple Fargate tasks. The error log and access log for the same request may appear on different log streams. Search all active streams in the alarm window using `describe_log_streams` followed by `get_log_events` or `filter_log_events` on each stream.

## Frequency

This pattern is typically low-volume (single-digit to low double-digit per 30 days) but can spike during campaign editing when a single user repeatedly clicks "test send" with the same invalid link. Because the metric filter threshold is `>= 1` with `datapoints_to_alarm = 1`, each individual ERROR log triggers a separate ALARM transition. Rapid recurrence (2+ transitions within 10 minutes) from the same user is common.

## Triage and classification

- **Pitfall — helper `current_error_details` may be empty**: The helper may report `current_error_details: []` even when `current_trigger_contexts` contains the clear `템플릿 링크 검증 실패` signature. The root cause is identifiable from `current_trigger_contexts` alone.
- **Pitfall — both `current_trigger_contexts` and `current_error_details` may be empty during rapid recurrence**: When the alarm fires 3+ times within 10 minutes, the helper's `current_trigger_contexts` can be empty (Logs Insights ingestion lag on the narrow 60-second alarm window). In this case, `recent_trigger_contexts` entries from the same rapid-recurrence cycle (within ~3-5 minutes of the current datapoint) are a reliable hint. Use them to identify the likely trigger pattern, then verify the exact alarm-window trigger with `get_log_events` on the specific log stream from the `recent_trigger_contexts` entry. Do not use `recent_trigger_contexts` directly as root cause evidence in the final answer without verification.
- Scope is not service-wide; it is project/campaign-specific. Do not report "unknown" when access logs are available.
- Cross-check the API handler returns 500 (not 400) by inspecting access logs for the same request. Successful test-sends return 201.

Classification:
- `no_action` when volume is low and the 500 response path is the known validation rejection (not a service crash)
- `needs_fix` when recurrence is noisy or the `console.error` logging creates alert fatigue

## Remediation direction

Short term: Move `KakaoBrandMessageTransformer.transform()` call inside the `try` block (it is currently at lines 38-44 of the handler, before the `try` at line 47) so the validation error returns a proper 400 instead of 500. Long term: downgrade the validation rejection log from `console.error` to `console.warn` since the validation rejection is a handled business rejection, not a service error.

## Related

- `references/web-console-kakao-image-upload-validation-error.md` — external Kakao provider validation errors (image upload, format, template variable name)
- `references/web-console-scope-attribution-via-access-logs.md` — access log scope recovery when parameterized routes hide project_id in error logs
