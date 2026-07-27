# LiquidJS ParseError: illegal token on connected_content tag

## Alert shape

- Alarm: `/aws/ecs/notifly-services-prod/web-console console error`
- Metric filter: `%[Ee][Rr][Rr][Oo][Rr]|Exception%`
- Triggering log: `ParseError: illegal token {% connected_content <url> :save msg%}{% if msg.eligible %}{{ msg.message.title }}{% else %}{% abort_message %}{% endif %}, line:1, col:210`
- Companion log: `From Error: illegal token {% connected_content ... %}`
- Stack trace originates in `liquidjs@10.20.0` `Parser.parseToken` and `services/server/web-console/.next/server/chunks/8693.js`

## Root cause

A Notifly console user authored a campaign/message template containing a `connected_content` LiquidJS tag with syntax that liquidjs@10.20.0 cannot parse. Observed causes:

1. Multiple consecutive spaces between the URL and `:save msg` in the tag body
2. Bracket syntax `{{user["$user_id"]}}` inside the URL query string of the `connected_content` tag

The `connected_content` tag is a custom LiquidJS tag registered by web-console. When the parser encounters the malformed token, it throws `ParseError: illegal token`, which is caught and logged at `ERROR` level. The `%ERROR|Exception%` metric filter matches `ParseError` and `From Error` strings.

This is a **user-authored template syntax error**, not a service bug. The template rendering fails gracefully — the request returns an error response to the console user, and no message is sent with the broken template.

## Scope attribution

The `ParseError` and `From Error` log lines do not contain `project_id` or `campaign_id`. The helper's scope attribution returns `unknown`.

**Recovery technique**: Read the raw log stream (`get_log_events`) around the exact alarm datapoint timestamp. The ParseError is emitted during a template preview or test-send API call. The adjacent access log line at the same timestamp (±1 second) contains the project scope:

```
58.122.170.40 - - "POST /api/projects/f2e198e2448959908fe4f8e540f4057f/test_send/push_notification HTTP/1.1" 400 317 "https://console.notifly.tech/console/products/qmarket/campaign/create?environment=1"
```

Extract:
- `project_id` from the URL path: `/api/projects/<project_id>/test_send/...`
- `product_id` from the Referer header: `/console/products/<product_id>/campaign/create`
- Campaign ID is unknown because the error occurs on the campaign create screen before a campaign ID is assigned

Map `project_id` via DynamoDB `project` table. In the observed case: `f2e198e2448959908fe4f8e540f4057f` → `qmarket` (prod, `dev=false`).

## Frequency pattern

- 30-day alarm transitions: ~92 (daily average 3, range 1–11)
- 7-day: ~27
- 1-day: ~9
- This is a chronic low-volume pattern driven by various console users authoring templates with syntax errors
- Not a regression or deployment correlation

## Classification

`no_action` — user-authored template syntax error, handled gracefully by the template parser. No data loss, no service degradation, no customer-facing delivery impact. The console user sees the error and can fix the template syntax.

## Long-term improvement (non-urgent)

- Downgrade `ParseError` / `From Error` log level from `ERROR` to `WARN` in the web-console LiquidJS parsing path so the metric filter stops catching template syntax errors
- Or add a pre-parse validation step that catches `connected_content` syntax issues before the LiquidJS parser and returns a user-friendly validation message

## Related references

- `web-console-liquidjs-abort-message-false-positive.md` — covers `abort_message()` as intentional control-flow abort (different error: `RenderError: message is aborted`, not `ParseError: illegal token`)
- `web-console-scope-attribution-via-access-logs.md` — general technique for recovering scope from access log Referer headers
- `ecs-console-error-false-positive-patterns.md` — broad false-positive patterns on the `%ERROR|Exception%` filter
