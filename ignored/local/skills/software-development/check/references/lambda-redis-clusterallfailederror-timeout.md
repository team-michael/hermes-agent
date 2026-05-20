# Lambda Redis ClusterAllFailedError Timeout

## Trigger signature

```
[timestamp] [uuid] ERROR [ioredis] Unhandled error event: ClusterAllFailedError: Failed to refresh slots cache. at tryNode (/var/task/node_modules/ioredis/built/cluster/index.js:310:31) ...
```

Followed by:

```
REPORT RequestId: [uuid] Duration: 900000.00 ms Billed Duration: 900000 ms Memory Size: [n] MB Max Memory Used: [n] MB Status: timeout
```

### Variant B — handled error with normal completion
Some Lambdas wrap each Redis call in a service-level `try...catch` with a fallback return (e.g., `ses-bounce-tracker/lib/redis.ts` returns `0` on any Redis error). The Lambda invocation completes normally, `AWS/Lambda Errors` stays `0`, and `Duration` is well below `Timeout`. However, ioredis still emits `ERROR Error: Cluster isn't ready and enableOfflineQueue options is false` for every failed command. The `%ERROR|Status: timeout%` metric filter matches the literal substring `ERROR`, so the `ConsoleErrors` alarm fires even though no timeout occurred.

**Concrete `ses-bounce-tracker` safety-critical consequence**: When Redis is down, `lib/redis.ts` `catch(e)` returns `0` for both `incrementBounceCount()` and `getSendCount()`. In `index.ts` the auto-termination guard requires `sendCount > MIN_SEND_COUNT_THRESHOLD` (1000) AND `bounceRate >= CAMPAIGN_HIGH_BOUNCE_RATE_THRESHOLD` (0.05). If Redis fails during a high-bounce campaign, `sendCount` becomes `0`, the threshold check fails (`0 > 1000` is false), and the campaign is **never terminated** even though the bounce rate is actually dangerous. The alarm correctly indicates that a safety mechanism is being bypassed; do not classify as a benign false positive without confirming the specific functional impact.

**Time-of-day recurrence**: `ses-bounce-tracker` processes SES bounce events via Firehose transformation and tends to fire at roughly the same clock time daily (observed ~00:02 UTC / ~09:02 KST) because the inbound SES bounce batch is time-of-day correlated. An increasing daily ERROR log count (e.g., 20 → 29 → 72) confirms worsening Redis connectivity, not random noise.

## Root cause

The `@notifly/redis` package (`packages/redis/src/index.ts`) creates an ioredis `Cluster` client for the `CACHE` profile with:

- `enableOfflineQueue: true`
- `slotsRefreshInterval: 10000`
- `slotsRefreshTimeout: 10000`

When the Redis cluster cannot refresh its slots cache — due to a deployment-induced connectivity change, cluster node failure, or `REDIS_HOST` misconfiguration — ioredis emits `ClusterAllFailedError` as an unhandled `error` event. Because the `CACHE` profile enables the offline command queue, any subsequent Redis commands (e.g., `multi().incrby().expire().exec()` in `email-delivery/lib/redis.js`) are queued indefinitely rather than failing fast. The Lambda invocation never resolves the awaiting Promise and eventually times out at the 900s limit.

If `callbackWaitsForEmptyEventLoop` is `false`, the timeout may appear without an unhandled Lambda exception; the `AWS/Lambda Errors` metric registers the timeout.

## Scope extraction

### SQS-triggered Lambdas
SQS payload bodies in the Lambda log typically contain:

```json
{"project_id":"...","campaign_id":"...","delivery_type":"scheduled_once", ...}
```

When the helper sanitizes `project_id` in the payload, pair the project from `table_refs` (e.g., `delivery_result_<project_id>`, `users_<project_id>`) with the `campaign_id` from the SQS body.

### Firehose transformation handlers (e.g., `ses-bounce-tracker`)
There is no SQS payload. Project and campaign IDs appear in companion **INFO** logs, not the ERROR line:
- `Excluding user email of project: <project_id>, campaign: <campaign_id>, notiflyUserId: ...`
- `Terminating project <project_id> campaign <campaign_id> due to high bounce rate.`

These INFO lines may be sanitized by the helper. If `current_trigger_contexts` contains only the Redis ERROR signature and no IDs, search the same log stream for `Excluding` or `Terminating` within the same invocation window to recover scope.

Concrete bounded trace for `ses-bounce-tracker` scope recovery:
```bash
# Recover project/campaign IDs from INFO lines in the alarm window
aws logs filter-log-events \
  --region ap-northeast-2 \
  --log-group-name /aws/lambda/ses-bounce-tracker \
  --start-time $(date -d '2026-05-19 23:47:00 UTC' +%s000) \
  --end-time $(date -d '2026-05-20 00:07:00 UTC' +%s000) \
  --filter-pattern 'Excluding user email' \
  --limit 20
```
Then map `<project_id>` through DynamoDB `project` table and report the `product_id` + `name` pair.

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

5. Cross-check deployed Lambda config (`MemorySize`, `Timeout`) against repo source (`serverless.yml` or Terraform). Config drift can mask root-cause signals. For example, `ses-bounce-tracker/serverless.yml` declares `memorySize: 512, timeout: 300` but deployed config may show `128 MB / 60 s`.

## Classification guidance

- **30d/7d baseline**: If `ClusterAllFailedError` appears only after a specific `LastModified` timestamp, treat as deployment-induced.
- **Increasing trend even when handled**: If `AWS/Lambda Errors = 0` but daily ERROR log counts are rising (e.g., 20 → 29 → 72) and the Lambda performs safety-critical logic (bounce-rate thresholds, campaign auto-termination), classify as `needs_fix`. Handled failures accumulate into functional drift even when individual invocations complete cleanly.
- **`ses-bounce-tracker` specific rule**: This Lambda is **never** `no_action` when the Redis ERROR count is increasing and the `Excluding user email` INFO line shows active campaign processing. The `catch(e) return 0` fallback in `lib/redis.ts` silently disables SES reputation auto-protection (`index.ts` sendCount > 1000 check fails). Classify as `needs_fix` (or `urgent` if multiple high-bounce campaigns are being processed during the failure window).
- **`needs_fix`**: When queue backlog is moderate (< ~1,000 messages) and DLQ count is limited. Fix target: `packages/redis/src/index.ts` cluster client error handling and `REDIS_HOST` env.
- **`urgent`**: When DLQ count is rising rapidly (> 100 messages/hour), queue depth is very large, or multiple Redis-dependent Lambdas are simultaneously affected.

## Implementation target

- `packages/redis/src/index.ts` — add `error` event listener on cluster client or set `enableOfflineQueue: false` for profiles that must fail fast.
- `services/lambda/<function-name>/lib/redis.js` — wrap `multi().exec()` in a timeout or use `CONTROL` profile if strong consistency is needed.
- `infra/terraform/prod/ap-northeast-2/lambda/functions.tf` — review DLQ `maxReceiveCount` (commonly `1` for email-delivery and similar channel Lambdas).
