# Lambda Redis ClusterAllFailedError Timeout

## Trigger signature

```
[timestamp] [uuid] ERROR [ioredis] Unhandled error event: ClusterAllFailedError: Failed to refresh slots cache. at tryNode (/var/task/node_modules/ioredis/built/cluster/index.js:310:31) ...
```

Followed by:

```
REPORT RequestId: [uuid] Duration: 900000.00 ms Billed Duration: 900000 ms Memory Size: [n] MB Max Memory Used: [n] MB Status: timeout
```

## Root cause

The `@notifly/redis` package (`packages/redis/src/index.ts`) creates an ioredis `Cluster` client for the `CACHE` profile with:

- `enableOfflineQueue: true`
- `slotsRefreshInterval: 10000`
- `slotsRefreshTimeout: 10000`

When the Redis cluster cannot refresh its slots cache — due to a deployment-induced connectivity change, cluster node failure, or `REDIS_HOST` misconfiguration — ioredis emits `ClusterAllFailedError` as an unhandled `error` event. Because the `CACHE` profile enables the offline command queue, any subsequent Redis commands (e.g., `multi().incrby().expire().exec()` in `email-delivery/lib/redis.js`) are queued indefinitely rather than failing fast. The Lambda invocation never resolves the awaiting Promise and eventually times out at the 900s limit.

If `callbackWaitsForEmptyEventLoop` is `false`, the timeout may appear without an unhandled Lambda exception; the `AWS/Lambda Errors` metric registers the timeout.

## Scope extraction

SQS payload bodies in the Lambda log typically contain:

```json
{"project_id":"...","campaign_id":"...","delivery_type":"scheduled_once", ...}
```

When the helper sanitizes `project_id` in the payload, pair the project from `table_refs` (e.g., `delivery_result_<project_id>`, `users_<project_id>`) with the `campaign_id` from the SQS body.

## Bounded trace commands

1. Check Lambda `LastModified` deploy time correlation:
   ```bash
   aws lambda get-function-configuration --function-name <function-name> --region ap-northeast-2 | jq -r '.LastModified'
   ```

2. Check `AWS/Lambda` `Errors` and `Duration` (Maximum) around the alarm window:
   ```bash
   aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Errors --dimensions Name=FunctionName,Value=<function-name> --start-time ... --end-time ... --period 60 --statistics Sum --region ap-northeast-2
   ```

3. Inspect current-alarm-window logs for the `ClusterAllFailedError` signature:
   ```bash
   aws logs filter-log-events --log-group-name /aws/lambda/<function-name> --start-time $(date -d '...' +%s000) --end-time $(date -d '...' +%s000) --filter-pattern 'ClusterAllFailedError' --region ap-northeast-2
   ```

4. Verify SQS DLQ depth and `maxReceiveCount`:
   ```bash
   aws sqs get-queue-attributes --queue-url https://sqs.ap-northeast-2.amazonaws.com/<account>/<queue-name> --attribute-names RedrivePolicy ApproximateNumberOfMessages --region ap-northeast-2
   ```

## Classification guidance

- **30d/7d baseline**: If `ClusterAllFailedError` appears only after a specific `LastModified` timestamp, treat as deployment-induced.
- **`needs_fix`**: When queue backlog is moderate (< ~1,000 messages) and DLQ count is limited. Fix target: `packages/redis/src/index.ts` cluster client error handling and `REDIS_HOST` env.
- **`urgent`**: When DLQ count is rising rapidly (> 100 messages/hour), queue depth is very large, or multiple Redis-dependent Lambdas are simultaneously affected.

## Implementation target

- `packages/redis/src/index.ts` — add `error` event listener on cluster client or set `enableOfflineQueue: false` for profiles that must fail fast.
- `services/lambda/<function-name>/lib/redis.js` — wrap `multi().exec()` in a timeout or use `CONTROL` profile if strong consistency is needed.
- `infra/terraform/prod/ap-northeast-2/lambda/functions.tf` — review DLQ `maxReceiveCount` (commonly `1` for email-delivery and similar channel Lambdas).
