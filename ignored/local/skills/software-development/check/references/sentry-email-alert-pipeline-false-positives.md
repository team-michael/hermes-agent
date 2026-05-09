# Sentry Email Alert Pipeline False Positives

Alarm family: `/aws/ecs/notifly-services-prod/web-console/sentry alert` (metric namespace `ConsoleErrors`).

## Root cause

The `ops-email-receiver` Lambda receives Sentry alert emails via SES and writes them
to CloudWatch Logs as structured JSON. The Sentry payload contains fields such as:
- `"level":"error"`
- `"issue":{"title":"Error"}` or `"title":"SyntaxError"` etc.

The log group has a metric filter with pattern `%[Ee][Rr][Rr][Oo][Rr]%` (or
broad `ERROR`-style substrings). This matches the JSON payload text, so every
Sentry alert that arrives produces a `ConsoleErrors` datapoint even though the
Lambda itself is operating correctly.

## Verification recipe

1. The helper may return `current_trigger_contexts: []` because Logs Insights
   indexing lags behind metric-filter ingestion, especially for very recent
   alarms (within 5–10 min of the metric datapoint).
2. Fall back to `aws logs filter-log-events` on the exact log group with a
   narrow time window (±5 min around the breaching datapoint timestamp):
   ```bash
   aws logs filter-log-events \
     --log-group-name '/aws/ecs/notifly-services-prod/web-console/sentry' \
     --start-time <epoch-ms> --end-time <epoch-ms> \
     --limit 5 --region ap-northeast-2
   ```
3. If a candidate stream is known, fetch the exact event with
   `aws logs get-log-events --log-stream-name <stream>`.
4. Inspect the `@message` JSON for `sentryAlert.issue.title`,
   `sentryAlert.level`, and `sentryAlert.request.url`.

## Scoping technique

The Sentry JSON payload `request.url` / `tags.url` often contains a Notifly
product slug, e.g.:

```
https://console.notifly.tech/console/products/hybiome/campaign/create
```

Extract `<productId>` (here `hybiome`) from the URL path or query string.

**Critical pitfall**: `sentryAlert.project.id` (e.g. `4506086856196096`) is the
**Sentry** project ID, not the Notifly project ID. Do not attempt DynamoDB
mapping with it.

Map the extracted product slug to a Notifly project via the DynamoDB `project`
table GSI:

```bash
aws dynamodb query \
  --table-name project \
  --index-name product_id-project_id-index \
  --key-condition-expression "product_id = :v" \
  --expression-attribute-values '{":v":{"S":"hybiome"}}' \
  --projection-expression "id, #n, product_id, dev" \
  --expression-attribute-names '{"#n":"name"}' \
  --region ap-northeast-2
```

**Duplicate-item pitfall**: the same `product_id` can appear twice in the table
(`dev: true` and `dev: false`). Use the item where `dev = false` for production
scope.

## Triage conclusion

- `ops-email-receiver` Lambda is healthy; the alarm is a noisy metric filter.
- The actual errors are `web-console` (Next.js) issues already tracked in Sentry
  (`greybox` organization).
- This pattern fires routinely (baseline ~1–2×/day, up to ~10×/day on busy
  Sentry days).
- Default status: `no_action` unless recurrence is sharply increasing or the
  Sentry issue volume itself indicates a customer-facing incident.
