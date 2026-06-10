# Web-Console Kakao BizMessage Validation Error (False Positive)

**Alarm**: `/aws/ecs/notifly-services-prod/web-console console error`
**Metric filter**: `%ERROR|Exception%`

Four Kakao BizMessage validation patterns currently trigger this alarm:

1. **`[FailedToUploadImageException(유효하지 않은 URL입니다. : <url>)]`** — image upload URL invalid or unreachable
2. **`[InvalidImageFormatException(<filename>)]`** — image format unsupported
3. **`Error: Failed to create Kakao BizMessage template: 변수명 형식이 올바르지 않습니다. 변수명은 최대 20자 이내 한/영/숫자/'-','_'로 작성 가능합니다.`** — template variable name violates Kakao naming rules
4. **`Error: 템플릿 링크 검증 실패:`** — mobile/PC web link validation failure before Kakao API call

## What it is

The first three originate from Kakao SDK/wrapper validation during BizMessage template creation or image upload. None of those strings exist in the `notifly-event` codebase. The fourth (`템플릿 링크 검증 실패`) originates from our `validateResolvedTemplateLinks` utility (`services/server/web-console/src/domains/message/transformers/KakaoBrandMessageTransformer.ts:145`), but it is still a **handled business rejection** of client-provided input — the console user entered an invalid mobile-web link in the Kakao brand-message template editor.

All four are handled business rejections; the web-console continues operating normally after logging the rejection.

For the template-variable and link-validation patterns, the code path is typically `POST /api/projects/{projectId}/test_send/kakao_brand_message`. The external-provider patterns (1–3 above) can also appear during user journey node editing:

```
at Array.q (/app/services/server/web-console/.next/server/pages/api/projects/[projectId]/user_journeys/[userJourneyId].js:1:6973)
```

This occurs when a user journey node includes a Kakao brand-message action and the template image or variable fails Kakao validation during save/preview.

## Scope

Bare exception/error log lines do not contain structured `project_id` or `campaign_id`. For the template-variable and link-validation patterns, the stack frame shows `/api/projects/[projectId]/test_send/kakao_brand_message.js` but the actual value is only in the access log, not the error log. Inspect access logs in the same time range for `POST /api/projects/<project_id>/test_send/kakao_brand_message` or other project-scoped paths. Extract the `project_id` and map via DynamoDB `project`. Because the web-console runs multiple Fargate tasks, the access log and error log for the same request may end up on different log streams — search across all active streams in the alarm window when the first stream yields no access match.

## Volume

Combined 30-day total for the first three patterns is typically 30–60 events. The fourth adds additional volume on top.

## Triage

When the helper returns `can_answer_root_cause: false` and manual follow-up shows any of the four Kakao patterns in current trigger contexts:

```sql
fields @timestamp, @message
| filter @message like 'FailedToUploadImageException'
   or @message like 'InvalidImageFormatException'
   or @message like 'Failed to create Kakao BizMessage template'
   or @message like '템플릿 링크 검증 실패'
| stats count() as cnt
| limit 1
```

Run against `/aws/ecs/notifly-services-prod/web-console` for the current alarm window and 30d. If these are the dominant or sole ERROR patterns and no other ERROR patterns exist, classify as `no_action` regardless of absolute count — these are handled client-input rejections, not service bugs.

Also confirm the external strings are absent from the codebase:

```bash
grep -r -E "FailedToUploadImageException|InvalidImageFormatException|Failed to create Kakao BizMessage template" /home/ubuntu/.hermes/workspace/notifly-event/src/ || echo "not found"
```

Absence confirms the first three are external provider errors, not code paths we control. The fourth (`템플릿 링크 검증 실패`) exists in `KakaoBrandMessageTransformer.ts` but is intentionally thrown as a handled client-input validation.

**Pitfall — `filter-log-events` case mismatch:** The metric filter uses `%[Ee][Rr][Rr][Oo][Rr]|Exception%`, so a bare `filterPattern='ERROR'` in `filter-log-events` may return zero matches while `filterPattern='Exception'` catches the trigger. Always test both terms, or run a raw tail without `filterPattern`, when the first query is empty.

## Remediation direction

- For the first three external-provider patterns: downgrade the log level from `ERROR` to `WARN` when the exception is caught and handled, or suppress them at the Kakao wrapper layer.
- For the fourth (link validation): downgrade from `throw new Error(...)` to a normal validation response or `WARN`-level log, because the error is already returned to the UI and does not need a top-level `ERROR` stack trace.
