# Web-Console Kakao Brand Message Template Link Validation Error

**Alarm**: `/aws/ecs/notifly-services-prod/web-console console error`
**Metric filter**: `%ERROR|Exception%`

## Error signature

```
Error: 템플릿 링크 검증 실패:
[모바일 웹 링크] 유효하지 않은 링크입니다: <url>
```

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
    return res.status(400).json({  // ← handled: user gets 400 with details
        error: 'Invalid request data',
        details: error.message,
    });
}
```

The request is handled correctly (400 response returned to the client), but `console.error(error)` emits an ERROR-level log line that matches the `%ERROR|Exception%` metric filter.

## What it is NOT

- Not a Kakao API error — this validation runs **before** any external API call
- Not a service bug — it is user input validation
- Not a code crash — the web-console ECS task continues normally

## Scope recovery

The error log trace frame shows the Next.js parameterized route `/api/projects/[projectId]/test_send/kakao_brand_message.js` — the resolved `project_id` is **not** in the error log. It is in the HTTP access log for the same request:

```
POST /api/projects/<project_id>/test_send/kakao_brand_message HTTP/1.1
```

Also, the `Referer` header in the access log contains:

```
https://console.notifly.tech/console/products/<productId>/campaign/create?...&id=<campaignId>&mode=edit
```

Extract `<productId>` from the Referer and `<project_id>` from the path parameter. Map `<productId>` via DynamoDB `project` table GSI `product_id-project_id-index`. Note the same `product_id` may map to multiple `project.id` values.

**Multi-stream pitfall**: web-console runs multiple Fargate tasks. The error log and access log for the same request may appear on different log streams. Search all active streams in the alarm window using `describe_log_streams` followed by `get_log_events` or `filter_log_events` on each stream.

## Frequency

This pattern is typically low-volume (single-digit to low double-digit per 30 days) but can spike during campaign editing when a single user repeatedly clicks "test send" with the same invalid link. Because the metric filter threshold is `>= 1` with `datapoints_to_alarm = 1`, each individual ERROR log triggers a separate ALARM transition. Rapid recurrence (2+ transitions within 10 minutes) from the same user is common.

## Triage and classification

- **Pitfall — helper `current_error_details` may be empty**: The helper may report `current_error_details: []` even when `current_trigger_contexts` contains the clear `템플릿 링크 검증 실패` signature. The root cause is identifiable from `current_trigger_contexts` alone.
- Scope is not service-wide; it is project/campaign-specific. Do not report "unknown" when access logs are available.
- Cross-check the API handler returns 400 (not 500) by inspecting access logs for the same request.

Classification:
- `no_action` when volume is low and the 400 response path is working normally
- `needs_fix` when recurrence is noisy or the `console.error` logging creates alert fatigue

## Remediation direction

Short term: Move `KakaoBrandMessageTransformer.transform()` call inside the `try` block (it is currently at lines 38-44 of the handler, before the `try` at line 47). Long term: downgrade the validation rejection log from `console.error` to `console.warn` since the API handler already returns a proper 400 with error details.

## Related

- `references/web-console-kakao-image-upload-validation-error.md` — external Kakao provider validation errors (image upload, format, template variable name)
- `references/web-console-scope-attribution-via-access-logs.md` — access log scope recovery when parameterized routes hide project_id in error logs
