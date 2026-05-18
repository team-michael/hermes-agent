# Web-Console Kakao Image Upload Validation Error (False Positive)

**Alarm**: `/aws/ecs/notifly-services-prod/web-console console error`  
**Metric filter**: `%ERROR|Exception%`  
**Trigger log**: `[FailedToUploadImageException(유효하지 않은 URL입니다. : <url>)]` or `[InvalidImageFormatException(<filename>)]`

## What it is

KakaoTalk channel image upload fails because the provided image URL is invalid, unreachable, or the image format is unsupported. The web-console logs this as an ERROR with `FailedToUploadImageException` (invalid/unreachable URL) or `InvalidImageFormatException` (unsupported image format or filename encoding). Neither exception string exists in the `notifly-event` codebase — both originate from an external Kakao SDK or wrapper library. The exception string does **not** exist in the `notifly-event` codebase — it originates from an external Kakao SDK or wrapper library.

This is a **handled business rejection**: the image URL quality is a client/input issue, not a service bug. The web-console continues operating normally.

## Scope

Bare exception log lines do not contain structured `project_id` or `campaign_id`. However, when the current alarm window includes normal web-console traffic, inspect access logs in the same time range for `GET /api/projects/<project_id>/...` or `POST /api/projects/<project_id>/campaigns/...`. Extract the `project_id` and map via DynamoDB `project` for scope. In the most recent session the `mmtalk` project was recovered this way.

## Volume

Combined 30-day total for both exception types (`FailedToUploadImageException` + `InvalidImageFormatException`) is typically 30–40 events. The two patterns often appear together in bursts because the same client campaign contains multiple invalid images. Individual 30-day volume for either pattern alone is typically under 15. Because the metric filter threshold is `>= 1` with `datapoints_to_alarm = 1`, a single ERROR log triggers the alarm. Combined with rapid OK/ALARM cycling, this produces nuisance paging.

## Triage

When the helper returns `can_answer_root_cause: false` and manual follow-up shows `FailedToUploadImageException` or `InvalidImageFormatException` in current trigger contexts:

```sql
fields @timestamp, @message
| filter @message like 'FailedToUploadImageException' or @message like 'InvalidImageFormatException'
| stats count() as cnt
| limit 1
```

Run against `/aws/ecs/notifly-services-prod/web-console` for the current alarm window and 30d. If these are the dominant or sole ERROR patterns and no other ERROR patterns exist, classify as `no_action` regardless of absolute count — these are external provider rejections, not service bugs.

Also confirm the strings are absent from the codebase:

```bash
grep -r -E "FailedToUploadImageException|InvalidImageFormatException" /home/ubuntu/.hermes/workspace/notifly-event/src/ || echo "not found"
```

Absence confirms this is an external provider error, not a code path we control.

**Pitfall — `filter-log-events` case mismatch:** The metric filter uses `%[Ee][Rr][Rr][Oo][Rr]|Exception%`, so a bare `filterPattern='ERROR'` in `filter-log-events` may return zero matches while `filterPattern='Exception'` catches the trigger. Always test both terms, or run a raw tail without `filterPattern`, when the first query is empty.

## Remediation direction

- Downgrade the log level from `ERROR` to `WARN` when either exception is caught and handled, or
- Suppress `FailedToUploadImageException` / `InvalidImageFormatException` at the Kakao wrapper layer so they do not propagate as top-level `ERROR` logs.
