# Web-Console Kakao BizMessage Validation Error (False Positive)

**Alarm**: `/aws/ecs/notifly-services-prod/web-console console error`
**Metric filter**: `%ERROR|Exception%`

Three Kakao external-provider validation patterns currently trigger this alarm:

1. **`[FailedToUploadImageException(유효하지 않은 URL입니다. : <url>)]`** — image upload URL invalid or unreachable
2. **`[InvalidImageFormatException(<filename>)]`** — image format unsupported
3. **`Error: Failed to create Kakao BizMessage template: 변수명 형식이 올바르지 않습니다. 변수명은 최대 20자 이내 한/영/숫자/'-','_'로 작성 가능합니다.`** — template variable name violates Kakao naming rules

## What it is

All three originate from Kakao SDK/wrapper validation during BizMessage template creation or image upload. None of these strings exist in the `notifly-event` codebase. They are **handled business rejections** of client-provided input. The web-console continues operating normally after logging the rejection.

For the template-variable pattern, the code path is `POST /api/projects/{projectId}/test_send/kakao_brand_message` → Kakao BizMessage template creation → Kakao-side validation failure. The API returns the error to the caller (typically a 4xx response), and the web-console UI displays it to the user.

## Scope

Bare exception/error log lines do not contain structured `project_id` or `campaign_id`. For the template-variable pattern, the stack frame shows `/api/projects/[projectId]/test_send/kakao_brand_message.js` but the actual value is only in the access log, not the error log. Inspect access logs in the same time range for `POST /api/projects/<project_id>/test_send/kakao_brand_message` or other project-scoped paths. Extract the `project_id` and map via DynamoDB `project`. Because the web-console runs multiple Fargate tasks, the access log and error log for the same request may end up on different log streams — search across all active streams in the alarm window when the first stream yields no access match.

## Volume

Combined 30-day total for all three patterns is typically 30–60 events. The image upload pair (`FailedToUploadImageException` + `InvalidImageFormatException`) and the template-variable pattern may appear independently. Individual 30-day volume for any single pattern is typically under 25. Because the metric filter threshold is `>= 1` with `datapoints_to_alarm = 1`, a single ERROR log triggers the alarm.

## Triage

When the helper returns `can_answer_root_cause: false` and manual follow-up shows any of the three Kakao patterns in current trigger contexts:

```sql
fields @timestamp, @message
| filter @message like 'FailedToUploadImageException'
   or @message like 'InvalidImageFormatException'
   or @message like 'Failed to create Kakao BizMessage template'
| stats count() as cnt
| limit 1
```

Run against `/aws/ecs/notifly-services-prod/web-console` for the current alarm window and 30d. If these are the dominant or sole ERROR patterns and no other ERROR patterns exist, classify as `no_action` regardless of absolute count — these are external provider rejections, not service bugs.

Also confirm the strings are absent from the codebase:

```bash
grep -r -E "FailedToUploadImageException|InvalidImageFormatException|Failed to create Kakao BizMessage template" /home/ubuntu/.hermes/workspace/notifly-event/src/ || echo "not found"
```

Absence confirms these are external provider errors, not code paths we control.

**Pitfall — `filter-log-events` case mismatch:** The metric filter uses `%[Ee][Rr][Rr][Oo][Rr]|Exception%`, so a bare `filterPattern='ERROR'` in `filter-log-events` may return zero matches while `filterPattern='Exception'` catches the trigger. Always test both terms, or run a raw tail without `filterPattern`, when the first query is empty.

## Remediation direction

- Downgrade the log level from `ERROR` to `WARN` when any Kakao validation exception is caught and handled, or
- Suppress the three patterns at the Kakao wrapper layer so they do not propagate as top-level `ERROR` logs.
