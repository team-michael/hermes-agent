# web-console LiquidJS `abort_message()` false positive

## Pattern

CloudWatch alarm `/aws/ecs/notifly-services-prod/web-console console error` fires on log lines matching `%ERROR|Exception%`.
When the current trigger contains:

```
From AbortError: message is aborted
RenderError: message is aborted, line:<n>, col:<n>
```

with a surrounding LiquidJS template frame such as:

```
>> 9| {%- abort_message() -%}
```

this is a **benign false positive**.

## Root cause

`abort_message()` is an intentional LiquidJS custom tag that stops rendering a message template when a user-journey or campaign condition is not met (e.g. no matching push data for the day). The web console logs this at ERROR level because the Liquid renderer throws an `AbortError`, and the broad metric filter `%ERROR|Exception%` matches the word "AbortError" or "RenderError".

The code path is:
- `services/server/web-console/.next/server/chunks/8693.js` (compiled `abort_message` tag render)
- `liquidjs` engine throws `RenderError` which wraps `AbortError`
- web console logs the caught error

## Classification rules

- `no_action` when the trigger context clearly shows `abort_message()` in the Liquid frame and no other ERROR/exception patterns coexist.
- `needs_fix` only if the same project shows a sudden spike in `abort_message()` frequency (e.g. external API dependency in `connected_content` tag failed, causing repeated aborts). In that case the real issue is the dependency, not the abort tag.

## Scope attribution

The Liquid template itself may not carry a `project_id` in the log line. Scope recovery options:
1. Check the same stream for preceding/following access logs with `Referer: /console/products/<productId>/...` and map `<productId>` through DynamoDB `project` GSI `product_id-project_id-index`.
2. The `user_journey_sessions_<hash>` table name may appear elsewhere in the logs; `<hash>` is the `project.id`.
3. If no project evidence exists, state "서비스 공통(web-console)" in the scope field.

## Remediation options

1. **Log level downgrade**: Change the abort path from `console.error` to `console.warn` or `console.info` so it drops out of the `%ERROR|Exception%` metric filter.
2. **Metric filter refinement**: Replace the broad substring with a more precise pattern that excludes known benign Liquid aborts.
3. **Keep `no_action`**: If frequency is low and stable, this is acceptable noise.

## Verification commands

Bounded manual trace to confirm the abort pattern:

```bash
# Identify active web-console log streams around the alarm window
aws logs describe-log-streams \
  --log-group-name /aws/ecs/notifly-services-prod/web-console \
  --order-by LastEventTime --descending --limit 5 \
  --region ap-northeast-2

# Read the stream matching the alarm datapoint minute
aws logs get-log-events \
  --log-group-name /aws/ecs/notifly-services-prod/web-console \
  --log-stream-name prod/web-console/<STREAM_ID> \
  --start-time $(date -d '2026-05-21T01:45:00Z' +%s)000 \
  --end-time $(date -d '2026-05-21T01:48:00Z' +%s)000 \
  --limit 100 \
  --region ap-northeast-2
```

## Concrete `connected_content` → PostgREST 404 variant

When a Liquid template uses the `connected_content` tag to query a PostgREST/Supabase endpoint, a 404 (`PGRST205`) can trigger `abort_message()` from inside the tag render. The log chain looks like:

```
<url> responded with 404:
{
  "code": "PGRST205",
  "details": null,
  "hint": "Perhaps you meant the table 'public.<table_name>'",
  "message": "Could not find the table 'public.<misspelled_table>' in the schema cache"
}
message is aborted, line:1, col:<n>
>> 1| {%- assign today = "now" | date: "%Y-%m-%d", "Asia/Seoul" -%}{%- connected_content <url> ...
^
RenderError: message is aborted, line:1, col:<n>
at Render.renderTemplates ...
...
From AbortError: message is aborted
at Tag.render (/app/services/server/web-console/.next/server/chunks/8693.js:1:9626)
```

In this variant the Liquid source line shows `connected_content`, not `abort_message()` directly. The compiled `Tag.render` at `chunks/8693.js` is still the definitive anchor because that is the compiled `abort_message` tag handler.

Classification is the same: `no_action` if this is isolated test/playground traffic or a single-template misconfiguration. `needs_fix` only if the same project shows a sustained spike caused by a broken `connected_content` dependency.
