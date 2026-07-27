# Tracing api-service errors from non-existent project IDs

## Scenario

api-service logs show `ERROR` with PostgreSQL code `42P01` (relation does not exist) for a table like `campaign_statistics_<project_id>` or `users_<project_id>`. The `<project_id>` is absent from the DynamoDB `project` table.

## Confirmation steps

1. **DynamoDB `project` table**: `get_item(Key={'id': '<project_id>'})` → `Item` not found.
2. **Check for supporting tables**:
   - DynamoDB `event_list_<project_id>` → not found.
   - Postgres `campaign_statistics_<project_id>` / `users_<project_id>` / `user_journey_statistics_<project_id>` → not found.

When all three are missing, the project is effectively non-existent in the system.

## Client trace from CloudWatch Logs

Use CloudWatch Logs Insights on `/aws/ecs/notifly-services-prod/api-service`:

```bash
fields @timestamp, @message
| filter @message like /<project_id>/
| sort @timestamp desc
| limit 20
```

Look for the structured api-service access/error log that includes:

- `ip`: client IP (may include Cloudflare proxy IPs, e.g., `175.196.116.1, 172.71.111.143`)
- `userAgent`: e.g., `curl/7.81.0`, browser strings, SDK names
- `method` and `path`: the exact endpoint being hit (e.g., `POST /v1/projects/<project_id>/statistics`)
- `status`: usually `500`
- `duration` and `responseBody`

A `curl` user-agent often indicates manual testing, an internal script, or a partner integration test—not a real end-user application.

## Impact assessment

| Pattern | Likely cause | Customer impact |
|---|---|---|
| Single/few requests from an unrecognized IP with `curl` UA | Misconfigured client test or internal script | None |
| Recurring requests with a valid SDK user-agent (e.g., `notifly-sdk/...`) | Real customer deployment with a stale/deleted project ID | Low; notify account team |
| Wide volume of different non-existent project IDs | Possible scraping, scanning, or fuzzing | Noise; evaluate rate-limiting or WAF rules |

## Response

- Do **not** treat as a service regression unless the same `42P01` error occurs for a valid, existing project with an existing table.
- Consider whether the statistics endpoint should return `404 Not Found` (with a clear message) instead of `500 InternalServerError` and an `ERROR`-level log for a non-existent project. A `404` is a correct client rejection and should not trigger a `ConsoleErrors` alarm.
- If the source IP is internal or a known partner, reach out to the owner to correct the `project_id`.
