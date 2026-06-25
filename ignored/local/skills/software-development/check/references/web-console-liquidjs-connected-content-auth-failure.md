# web-console LiquidJS `connected_content` authentication failure → abort pattern

## Pattern

CloudWatch alarm `/aws/ecs/notifly-services-prod/web-console console error` fires with trigger logs showing:

```
<supabase_url> responded with 401:
{
  "error": "Unauthorized"
}
message is aborted, line:1, col:413

>> 1| {% connected_content <url> user["$user_id"] }} :headers { "Authorization": "Bearer sb_secret_..." } :save u %}{% if u.activity_label == 'dormant' %}...
^
RenderError: message is aborted, line:1, col:413
  at Render.renderTemplates (/app/node_modules/.pnpm/liquidjs@10.20.0/node_modules/liquidjs/dist/liquid.node.js:1232:53)
  ...
From AbortError: message is aborted
  at Tag.render (/app/services/server/web-console/.next/server/chunks/8693.js:1:9227)
```

Or with **400 (Bad Request)**:

```
<supabase_url> responded with 400:
{
  "error": "user_id is required and must be a number"
}
```

## Root cause

A Liquid template in a user journey or campaign uses the `connected_content` tag to call a Supabase PostgREST endpoint (or other external API). The request includes an Authorization header with a Bearer token. The endpoint rejects the request with 401 (invalid/expired token, missing credentials) or 400 (validation error — e.g., `user_id` parameter format incorrect, missing required field).

The `connected_content` tag handler (in the compiled web-console chunks) catches the HTTP error, logs it, and then calls `abort_message()` internally to stop template rendering. The abort is logged at ERROR level because LiquidJS throws `RenderError` wrapping `AbortError`.

The broad metric filter `%[Ee][Rr][Rr][Oo][Rr]|Exception%` matches the literal strings in the error object and the stack frame, triggering the alarm.

**This is NOT a Notifly service bug.** It is a customer-side template configuration issue:
- **401 variant**: The Supabase API key/token in the template header is invalid, expired, or revoked. The user needs to update the key in the campaign/user-journey template editor.
- **400 variant**: The template is passing an invalid value for a required parameter (e.g., user_id is null, not a number, or a required field is missing).

The message delivery pipeline **continues normally** after the abort; the message is either sent with a fallback/cached content or skipped if the condition-based abort is intentional.

## Classification

- **`no_action`** when:
  - This is a **single isolated instance** affecting one campaign/user-journey template.
  - The customer can fix it by updating the Supabase credentials or template parameter handling.
  - Frequency is low (≤ 5 per day) and does not indicate a broader service issue.

- **`needs_fix`** when:
  - The **same error spike repeats daily or across multiple projects**, suggesting a systematic issue (e.g., shared Supabase key revoked, token expiration cron ran).
  - The error frequency is **high and sustained** (hundreds per hour), blocking normal campaign delivery.
  - Multiple unrelated projects show the pattern simultaneously, indicating a Notifly platform change (e.g., header injection, parameter binding change) broke a common template usage pattern.

## Scope attribution

The template source line (`>> 1| {% connected_content ...`) may not include the `project_id` directly. Recover scope using:

1. **Access log Referer header**: Check the same ECS log stream for a preceding `GET /api/projects/<project_id>/campaigns/<campaign_id>...` line in an access log. That request came from a user browsing the campaign editor; the `project_id` is the scope.
   - Example Referer in access log: `https://console.notifly.tech/console/products/mom-sitter/campaign/list?environment=1`
   - Map `mom-sitter` (productId) via DynamoDB `project` GSI `product_id-project_id-index` to get Notifly `project.id`.

2. **Sharded table references**: If the logs show other errors mentioning `user_journey_session_statistics_<hash>` or `user_journey_nodes_<project_id>`, the `<project_id>` or `<hash>` is the scope.

3. **Service-wide scope**: If no project evidence is found after checking 5 minutes before and after the error timestamp, state the scope as `web-console 서비스 공통` in the final answer.

## Verification commands

Bounded manual trace to confirm the auth failure pattern:

```bash
# Get recent web-console streams
aws logs describe-log-streams \
  --log-group-name /aws/ecs/notifly-services-prod/web-console \
  --order-by LastEventTime --descending \
  --region ap-northeast-2 | jq '.logStreams[0:3] | .[].logStreamName'

# Read the stream around the alarm datapoint timestamp
# E.g., alarm fired at 2026-06-17T07:27:45Z, so check 07:26:00-07:28:00
STREAM_ID="prod/web-console/8293803ce2f04c57a46643d91349cfda"
aws logs get-log-events \
  --log-group-name /aws/ecs/notifly-services-prod/web-console \
  --log-stream-name "$STREAM_ID" \
  --start-time 1781681560000 \
  --end-time 1781681680000 \
  --limit 100 \
  --region ap-northeast-2 | jq '.events[] | select(.message | contains("responded with 401") or contains("responded with 400")) | {timestamp, message}'

# Identify the project from access logs in the same stream
aws logs get-log-events \
  --log-group-name /aws/ecs/notifly-services-prod/web-console \
  --log-stream-name "$STREAM_ID" \
  --start-time 1781681500000 \
  --end-time 1781681680000 \
  --region ap-northeast-2 | jq '.events[] | select(.message | contains("GET /api/projects/")) | {timestamp, message: .message[:200]}'

# Map the productId from access log Referer to project_id via DynamoDB
aws dynamodb get-item \
  --table-name project \
  --key "{\"product_id\":{\"S\":\"mom-sitter\"}}" \
  --projection-expression "id,product_id,#n" \
  --expression-attribute-names '{"#n":"name"}' \
  --region ap-northeast-2
```

## Remediation options

### Option 1: Customer self-service fix (fastest)
Guide the affected project/campaign owner to:
1. Visit the campaign/user-journey template editor.
2. Find the `connected_content` tag with the failing URL.
3. Verify the Supabase API key is valid and not expired.
4. Verify all required parameters (e.g., `user_id`) are passed correctly.
5. Test the endpoint manually with `curl` or Postman to confirm it responds with 200/2xx.
6. Re-save the template.

### Option 2: Platform-side downgrade or filter (if widespread)
If the spike is service-wide or affects multiple projects:
1. Downgrade the `connected_content` error logging from `console.error` to `console.warn` in the Liquid tag implementation.
2. Or refine the metric filter in Terraform to exclude known benign abort patterns:
   - Current: `%[Ee][Rr][Rr][Oo][Rr]|Exception%`
   - Refined: `%TypeError|ReferenceError|SyntaxError|Unhandled%` (excludes benign "RenderError" and "AbortError" stemming from intentional template control flow)
   - File: `infra/terraform/prod/ap-northeast-2/ecs/services.tf:1013, 1025, 1079, 1085`

### Option 3: Keep `no_action` (if low frequency)
If the frequency is ≤ 5 instances per day and already-recovered, log it as expected customer-side template misconfiguration and monitor for escalation.

## Example: API key rotation impact

When a Supabase organization rotates API keys, all active campaigns using the old key will fire this alarm on the first render attempt after key expiration. The spike is time-bound (typically hours to days until campaigns complete or are paused). This is **expected** and **not** a Notifly bug.

Recommended response:
1. Verify the event correlates with a known Supabase credential rotation or web-console deployment that changed key handling.
2. Notify affected projects of the key rotation and ask them to update templates.
3. Consider adding a pre-flight validation in the campaign editor UI to test `connected_content` URLs at save time, so customers catch invalid keys before campaigns send.

## Variant: Liquid Playground external API 400 (no abort, rendering succeeds)

The same Supabase personalization endpoint can return 400 when invoked from the **Liquid Playground** testing tool (`/console/products/<productId>/utils/liquid-playground`), not just from a campaign/user-journey send.

Key differences from the abort variant:
- **No `RenderError` / `AbortError`**: The template rendering **does not abort**. The external API's 400 response body is logged directly, but rendering continues.
- **`POST /api/liquid/template` returns 200**: The Liquid rendering itself succeeds. The personalization fetch failure is a non-critical side effect.
- **Trigger log shape**: Only the HTTP response lines appear — `<url> responded with 400:` + `{"error": "..."}` — with no LiquidJS stack trace.
- **User-initiated, sporadic**: Triggered by a console user testing templates in the Playground, not by automated batch delivery. Frequency is low (<= 5 per day) and sporadic.

### Helper URL masking limitation

The helper sanitizes URLs to `<url>` in `surrounding_lines`, so `current_trigger_contexts[].surrounding_lines` shows:
```
"<url> responded with 400:"
"{"
"\"error\": \"user_id is required and must be a number\""
"}"
```

When the trigger context shows `<url> responded with <status>:`, the actual URL is critical to determine whether the error is from an internal Notifly endpoint or an external API. Use `get_log_events` on the trigger stream with `startTime`/`endTime` bounded to the alarm datapoint window to read the full unmasked context:

```python
resp = logs.get_log_events(
    logGroupName="/aws/ecs/notifly-services-prod/web-console",
    logStreamName=trigger_stream,
    startTime=start_ms,  # alarm window start in epoch ms
    endTime=end_ms,
    startFromHead=True,
    limit=50
)
```

The full URL (e.g., `https://htcxkbijmiptoubmkhkm.supabase.co/functions/v1/personalization?user_id=`) immediately identifies this as an external Supabase Edge Function call, not an internal service error.

### Scope attribution for Liquid Playground

The trigger log itself does not contain `project_id`. Recover scope from the access log line immediately following the error in the same stream:
- `POST /api/liquid/template HTTP/1.1` -> 200 with Referer `https://console.notifly.tech/ko/console/products/<productId>/utils/liquid-playground`
- Map `<productId>` via DynamoDB `project` table GSI `product_id-project_id-index` (prefer `dev=false` for production scope).

### Frequency pattern

- 7d count of `"user_id is required and must be a number"`: typically <= 6 (sporadic, user-initiated)
- Previous spike observed on 2026-06-17 (15 events) -- likely a single user testing multiple templates
- Classification: **`no_action`** -- handled external API validation error, rendering succeeds, no customer-facing impact

## Related references

- `references/web-console-liquidjs-abort-message-false-positive.md` -- broader class of LiquidJS abort patterns.
- `references/web-console-scope-attribution-via-access-logs.md` -- Referer-based scope recovery for web-console alerts.
