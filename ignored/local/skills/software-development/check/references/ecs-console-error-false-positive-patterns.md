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

Any ECS service whose log group contains mixed application logs + HTTP access logs is vulnerable to this class of false positive when the metric filter uses broad substrings such as `ERROR` or `Exception`. Additional benign patterns to watch for:
- `error` in static asset paths (`/error.html`, `/404-error.svg`)
- `exception` in marketing or analytics query parameters
- `ERROR` in user-generated content fields logged as part of a request

**Remediation direction**: narrow the metric filter pattern so it does not match access logs, or move access logs to a separate log stream.

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
