# Web-Console Kakao BizMessage Validation Error (False Positive)

**Alarm**: `/aws/ecs/notifly-services-prod/web-console console error`
**Metric filter**: `%ERROR|Exception%`

Five Kakao BizMessage validation patterns currently trigger this alarm:

1. **`[FailedToUploadImageException(유효하지 않은 URL입니다. : <url>)]`** — image upload URL invalid or unreachable
2. **`[InvalidImageFormatException(<filename>)]`** — image format unsupported
3. **`Error: Failed to create Kakao BizMessage template: 변수명 형식이 올바르지 않습니다. 변수명은 최대 20자 이내 한/영/숫자/'-','_'로 작성 가능합니다.`** — template variable name violates Kakao naming rules
4. **`Error: 템플릿 링크 검증 실패:`** — mobile/PC web link validation failure before Kakao API call
5. **`Error: Unacceptable characters in title and body.`** — Kakao BizMessage template title or body contains characters the provider rejects (e.g., certain symbols, unescaped markup, or unsupported Unicode blocks)
6. **`Failed to create Kakao BizMessage template: 파라미터 <name>은(는) NBSP(U+00A0) 문자가 포함되었습니다. 해당 문자는 허용되지 않습니다.`** — the `content` parameter of a Kakao BizMessage template contains a non-breaking space (U+00A0). This occurs on `POST /api/projects/{projectId}/test_send/kakao_brand_message`; the Kakao API rejects the request because NBSP is not in the allowed character set for template body content. Sentry payloads for this pattern include `tags.handled: "yes"`, confirming the error is caught and handled.

## What it is

The first three originate from Kakao SDK/wrapper validation during BizMessage template creation or image upload. None of those strings exist in the `notifly-event` codebase. The fourth (`템플릿 링크 검증 실패`) originates from our `validateResolvedTemplateLinks` utility (`services/server/web-console/src/domains/message/transformers/KakaoBrandMessageTransformer.ts:145`), but it is still a **handled business rejection** of client-provided input — the console user entered an invalid mobile-web link in the Kakao brand-message template editor.

The fifth (`Unacceptable characters in title and body.`) appears as a Kakao provider response during `POST /api/projects/{projectId}/test_send/kakao_brand_message`. Sentry payloads for this pattern include `tags.handled: "yes"`, confirming the error is caught and handled. Stack-trace frames typically show `KakaoBrandMessageTransformer.inline` (`services/server/web-console/.next/server/chunks/71260.js`) and `g.failoverTextMessage` / `T.inline`.

All five are handled business rejections; the web-console continues operating normally after logging the rejection.

For the template-variable and link-validation patterns, the code path is typically `POST /api/projects/{projectId}/test_send/kakao_brand_message`. The external-provider patterns (1–3 above) can also appear during user journey node editing:

```
at Array.q (/app/services/server/web-console/.next/server/pages/api/projects/[projectId]/user_journeys/[userJourneyId].js:1:6973)
```

Stack-trace signatures for the user-journey variant include:

```
at async Promise.all (index 10)
at async b.upsert (.../chunks/17968.js:19:1946)
at async Array.q (.../pages/api/projects/[projectId]/user_journeys/[userJourneyId].js:1:6973)
```

The `Promise.all (index N)` frame indicates a bulk save of multiple user-journey nodes, one of which contains a Kakao brand-message template reference that fails validation.

## Scope

Bare exception/error log lines do not contain structured `project_id` or `campaign_id`. For the template-variable, link-validation, NBSP-content, and "unacceptable characters" patterns, the stack frame shows `/api/projects/[projectId]/test_send/kakao_brand_message.js` but the actual value is only in the access log or Sentry payload `request.url`, not the error log. In Sentry pipeline logs, `request.url` often contains the literal project ID directly in the path (e.g., `https://console.notifly.tech/api/projects/b2b4a8f879a75673b755bff42fc1deb6/test_send/kakao_brand_message`), so scope can be resolved by extracting that segment and mapping via DynamoDB `project.id` directly. For non-Sentry alarms, inspect access logs in the same time range for `POST /api/projects/<project_id>/test_send/kakao_brand_message` or other project-scoped paths. Because the web-console runs multiple Fargate tasks, the access log and error log for the same request may end up on different log streams — search across all active streams in the alarm window when the first stream yields no access match.

## Volume

Combined 30-day total for the first three patterns is typically 30–60 events. The fourth and fifth add additional volume on top.

## Triage

When the helper returns `can_answer_root_cause: false` and manual follow-up shows any of the four Kakao patterns in current trigger contexts:

```sql
fields @timestamp, @message
| filter @message like 'FailedToUploadImageException'
   or @message like 'InvalidImageFormatException'
   or @message like 'Failed to create Kakao BizMessage template'
   or @message like '템플릿 링크 검증 실패'
   or @message like 'Unacceptable characters'
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

## Related: LMS 대체 문자 title 필드 미입력 오류

`Error: The title can not be empty.`는 위 목록과 별개의 패턴이다. Kakao 외부 제공자 오류가 아니라 web-console 서버 사이드 자체 검증 오류 (LMS 타입 선택 시 title 필수 입력 미준수). 동일 IP에서 rapid recurrence 형태로 반복 발생할 수 있음. 분류는 동일하게 `no_action`. 상세 내용은 `references/web-console-kakao-brand-message-test-send-title-empty.md` 참조.

## Remediation direction

- For the first three and fifth external-provider patterns: downgrade the log level from `ERROR` to `WARN` when the exception is caught and handled, or suppress them at the Kakao wrapper layer.
- For the fourth (link validation): downgrade from `throw new Error(...)` to a normal validation response or `WARN`-level log, because the error is already returned to the UI and does not need a top-level `ERROR` stack trace.
