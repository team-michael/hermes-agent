# ECS Console Error False Positive Patterns

Concrete benign-substring patterns that have triggered `ConsoleErrors` alarms for ECS services despite being normal requests.

## `service_error` referrer pattern (web-console)

**Alarm**: `/aws/ecs/notifly-services-prod/web-console console error`  
**Metric filter**: `%ERROR|Exception%`  
**Trigger**: Access log lines such as:
```
125.129.101.58 - - [...] "GET /auth/signout HTTP/1.1" 200 -
"https://console.notifly.tech/console/products/break/in-app-message/modification?templateName=service_error&environment=1"
```

**Mechanism**: the substring `service_error` in the `templateName` query parameter matches the case-insensitive `%ERROR%` arm of the metric filter.

**Triage**: when the helper returns `can_answer_root_cause: false` and the only trigger contexts are access logs, run a secondary Logs Insights query that explicitly excludes the benign substring:

```sql
fields @timestamp, @message
| filter @message like /ERROR/ or @message like /Exception/
| filter @message not like /service_error/
| sort @timestamp desc
| limit 50
```

If this returns zero results, the alarm is a false positive caused by the metric filter matching benign URL parameters.

## `receipt-error-*` referrer pattern (web-console)

**Alarm**: `/aws/ecs/notifly-services-prod/web-console console error`  
**Metric filter**: `%ERROR|Exception%`  
**Trigger**: Access log lines such as:
```
221.146.182.32 - - [...] "POST /api/s3/upload_html HTTP/1.1" 200 158
"https://console.notifly.tech/console/products/regather/in-app-message/modification?environment=1&templateName=receipt-error-AOSup-0519"
```

**Mechanism**: the substring `error` inside the `templateName` query parameter matches the case-insensitive `%ERROR%` arm of the metric filter. The request is a normal 200 OK S3 upload during in-app message template editing.

**Triage**: when the helper returns `can_answer_root_cause: false` and the only trigger contexts are access logs (`POST /api/s3/upload_html`, `POST /api/s3/upload_dataurl`, `POST /api/s3/get_html`), run a secondary bounded log check excluding the benign substring:

```sql
fields @timestamp, @message
| filter @message like /ERROR/ or @message like /Exception/
| filter @message not like /receipt-error/
| sort @timestamp desc
| limit 50
```

If this returns zero results, the alarm is a false positive caused by the metric filter matching a benign template-name query parameter.

**Scope note**: The referrer URL reveals the product (`regather`) and the in-app-message modification screen. Because the `project` GSI for `product_id=regather` returns multiple `project_id` items, the precise project/campaign scope remains ambiguous for this access-log-only trigger. Use the product name in the scope field when exact project mapping is non-unique.

## Generalisation

## Concrete root-cause reporting rule

When a later manual log lookup reveals the actual trigger line, prefer that concrete evidence in the final answer over the alarm name or a broad service-level label. The root-cause line should name the exact failure signature, the surrounding request/job context, and the code path or SQL/table reference when visible.

Make this a hard default:
- `원인:` must start with the exact trigger signature when one exists.
- Follow with the immediate mechanism in plain language.
- Then include the emitting code path, SQL fingerprint, table name, or external provider only if visible.
- Do not lead with the alarm name, metric namespace, or a generic service description when a concrete log signature is available.

Examples:
- PostgreSQL deadlock: report the `ERROR: deadlock detected` line plus the locked relation and repository method.
- External-provider rejection: report the exact provider error string and the route that emitted it.
- Handled business rejection: report the exact validation/error message that triggered the metric filter.

This keeps alert triage anchored on the real failure mechanism instead of a generic metric-filter explanation.

Any ECS service whose log group contains mixed application logs + HTTP access logs is vulnerable to this class of false positive when the metric filter uses broad substrings such as `ERROR` or `Exception`. Additional benign patterns to watch for:
- `error` in static asset paths (`/error.html`, `/404-error.svg`)
- `exception` in marketing or analytics query parameters
- `ERROR` in user-generated content fields logged as part of a request

**Remediation direction**: narrow the metric filter pattern so it does not match access logs, or move access logs to a separate log stream.

## `abort_message` LiquidJS tag — rendered test-send abort (web-console)

**Alarm**: `/aws/ecs/notifly-services-prod/web-console console error`  
**Metric filter**: `%ERROR|Exception%`  
**Trigger log**:
```
RenderError: message is aborted, line:9, col:3
    at Tag.render (/app/services/server/web-console/.next/server/chunks/8693.js:1:9640)
...
From AbortError: message is aborted
```

**Mechanism**: When a console user previews or test-sends a push/in-app message whose Liquid template contains `{% abort_message() %}`, the web-console API (`POST /api/projects/{projectId}/test_send/push_notification` and siblings) intentionally throws an `AbortError`. The API route wraps the call in `try/catch` and returns HTTP 400 with `"Invalid request data"`, but the caught error is first emitted via `console.error`. The resulting stack trace contains both `RenderError` and `AbortError`, which matches the coarse `%ERROR|Exception%` metric filter even though no service fault occurred.

**Triage**: When the current trigger context shows `RenderError: message is aborted` or `From AbortError: message is aborted`, verify:
1. The surrounding log lines contain a `POST /api/projects/{pid}/test_send/push_notification` (or `email`, `kakao_alimtalk`, etc.) request with HTTP status 400.
2. The `Referer` header shows a campaign-creation or campaign-clone screen (e.g. `/console/products/{productId}/campaign/create`).
3. No other ERROR/Exception patterns appear in the same alarm window.

If all three hold, this is a handled business rejection (user-initiated template abort during preview/test-send) and should be classified as `no_action`.

**Scope extraction**: The `projectId` path parameter is visible on the `POST` access log line. Map it via DynamoDB `project` table. The `Referer` product slug can be mapped via the `product_id-project_id-index` GSI when needed.

**Remediation direction**: The `catch` block in `services/server/web-console/src/pages/api/projects/[projectId]/test_send/push_notification.ts` (and sibling channel files) could log at `warn` level instead of `console.error` for `AbortError`, or the metric filter could exclude `RenderError.*message is aborted`.

## `FailedToUploadImageException` — Kakao image URL validation (web-console)

**Alarm**: `/aws/ecs/notifly-services-prod/web-console console error`
**Metric filter**: `%ERROR|Exception%`
**Trigger log**: `[FailedToUploadImageException(유효하지 않은 URL입니다. : <url>)]`

**Mechanism**: KakaoTalk channel image upload fails because the provided image URL is invalid or unreachable. The web-console logs this as an ERROR. The exception string does **not** exist in the `notifly-event` codebase — it originates from an external Kakao SDK or wrapper library.

**Triage**: When the helper returns `can_answer_root_cause: false` and manual follow-up shows this signature in current trigger contexts, run a bounded Logs Insights query:

```sql
fields @timestamp, @message
| filter @message like 'FailedToUploadImageException'
| stats count() as cnt
| limit 1
```

If the 30d count is single-digit and no other ERROR patterns exist, classify as `no_action` — this is a handled business rejection, not a service bug.

See `references/web-console-kakao-image-upload-validation-error.md` for full triage and remediation direction.

## Node.js internal object properties with `error`/`errored` substring

**Alarm**: `/aws/ecs/notifly-services-prod/web-console console error` (and potentially any ECS service with a coarse `%ERROR|Exception%` metric filter)  
**Metric filter**: `%ERROR|Exception%`  
**Trigger log**: Property-dump lines such as:
```
      error: [Function: contextWrapper],
      [Symbol(events.errorMonitor)]: [Function: contextWrapper]
    [Symbol(errored)]: null,
      error: [WeakMap],
      [Symbol(events.errorMonitor)]: [WeakMap]
      [Symbol(errored)]: null,
```

**Mechanism**: These are Node.js internal object property names (from `net.Socket`, `tls.TLSSocket`, or HTTP client objects) that contain the substring `error` or `errored` (e.g. `error`, `[Symbol(errored)]`, `[Symbol(events.errorMonitor)]`, `_closeAfterHandlingError`). When a library or code path serializes an error object with deep property enumeration via `console.error(e)` or `console.dir(e, {depth: ...})`, the resulting log dump includes these property names. The case-insensitive `%ERROR%` arm of the metric filter matches them even though no application-level error occurred. The surrounding context often reveals the source object (e.g. `encrypted: true`, `_host: 'mud-kage.kakao.com'`, `ssl: [TLSWrap]`, `timeout: 5000`), confirming this is a serialized network client state, not a service fault.

**Triage**: When the current alarm window shows only property-dump lines and no actual stack traces or application ERROR logs:
1. Run `filter-log-events` with `ERROR` to see the matching lines.
2. Run `filter-log-events` with `Exception` on the same window.
3. If the `Exception` query returns empty and the `ERROR` results are exclusively object-property dumps (no `at ` stack frames, no `Error:` messages), classify as `no_action`.

**Classification**: `no_action` when this signature dominates and no real ERROR/Exception patterns coexist in the same alarm window.

**Remediation direction**: If this becomes frequent, consider narrowing the metric filter to require a stack trace anchor (`at `) or an `Error:` prefix, instead of the raw `%ERROR%` substring. Alternatively, move object-serialization debugging lines to a lower log level in the emitting code path.

## AWS Athena `INTERNAL_ERROR: RESOURCE_UNHEALTHY` — handled transient backend failure (`campaign-event-data-export`)

**Alarm**: `campaign-event-data-export ECS task error`  
**Metric filter**: `%ERROR|Error%`  
**Trigger log** (structured):
```
{
  "event": "EXPORT_FAILED",
  "timestamp": "2026-06-03T20:11:58.279Z",
  "error": {
    "message": "Query failed with state: FAILED",
    "name": "Error",
    "durationMs": 1220
  },
  "input": {
    "projectId": "<project_id>",
    "exportId": "<uuid>",
    "start": "...",
    "end": "...",
    "isMessageDataIncluded": true
  },
  "context": { "memoryUsage": {...} }
}
```

**Underlying cause log line**:
```
"StateChangeReason": "[ErrorCode: INTERNAL_ERROR: RESOURCE_UNHEALTHY] Amazon Athena experienced an internal error while executing this query..."
```

**Mechanism**: `campaign-event-data-export` is a batch ECS task that runs Athena queries against `notifly_message_events` (and `notifly_event_logs`) to export campaign event data. When Athena returns a transient internal `RESOURCE_UNHEALTHY` error, the task catches the exception, logs `EXPORT_FAILED` at ERROR level via `console.error`, and updates the export status to `failed` in S3 (`services/task/campaign-event-data-export/lib/exporter.ts`). The ERROR log exists only because the application records the failure so the user can see it; there is no code bug, data loss, or retry exhaustion.

**Triage**:
1. When the helper returns empty `current_trigger_contexts` for this alarm, run a bounded `filter-log-events` on `/aws/ecs/notifly-services-prod/campaign-event-data-export` with `Error` in the alarm window.
2. Look for `EXPORT_FAILED` structured logs with `error.message = "Query failed with state: FAILED"`.
3. Read the surrounding stream lines for the Athena `StateChangeReason` containing `INTERNAL_ERROR` and `RESOURCE_UNHEALTHY`.
4. If confirmed, verify recurrence: this pattern is typically a single isolated occurrence with no 7-day or 30-day repetition.

**Classification**: `no_action` when:
- The alarm window shows only this Athena internal-error signature,
- No other ERROR patterns exist in the same window,
- The occurrence is isolated (single 10m/1d transition, no rapid recurrence).

**Scope**: Extract `projectId` from the `EXPORT_FAILED` JSON input field and map via DynamoDB `project` table. Campaign/user journey is typically unknown because the export is a batch job, not a specific campaign send.

**Remediation direction**: The `EXPORT_FAILED` log is intentionally ERROR-level so that export failures are visible in operation dashboards. Re-classifying it to WARN is only viable if the export status is already reliably surfaced to the calling user via the S3 status file or an upstream API response. The metric filter on `/aws/ecs/notifly-services-prod/campaign-event-data-export` could instead be narrowed to exclude the known `EXPORT_FAILED` event name, but doing so would hide real export failures caused by application bugs or persistent Athena query errors. Prefer to keep the current filter and classify these transient AWS errors as `no_action` during triage.

**Generalisation**: Any ECS batch task that calls external AWS services (Athena, Glue, EMR, SageMaker, etc.) and logs handled failures at ERROR level will trigger `ConsoleErrors` alarms when the upstream service has transient internal errors. The triage pattern is the same: verify that the ERROR log is a structured handled-failure event (not an unhandled stack trace), check the upstream service error for `INTERNAL_ERROR` / `RESOURCE_UNHEALTHY` / `ThrottlingException` / `ServiceUnavailable`, confirm isolation, and classify as `no_action`.
