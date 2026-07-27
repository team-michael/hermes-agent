# CloudWatch probes for Redis Cluster ↔ Lambda issues

Use this when checking whether Notifly Redis/ElastiCache cluster-mode warnings are still causing Lambda/SQS user impact.

## Separate warning signals from timeout impact

Query Redis warnings and Lambda timeouts separately. Redis warnings can remain after a mitigation while actual Lambda timeouts/DLQs are fixed.

Useful log phrases:

- `ClusterAllFailedError`
- `Failed to refresh slots`
- `Redis connection timed out`
- `Failed to increment campaign delivery counts`
- `Task timed out after`
- `Status: timeout`

## Logs Insights aggregate pattern

```sql
fields @timestamp, @log, @message
| filter @message like /Task timed out after|Status: timeout|ClusterAllFailedError|Redis connection timed out|Failed to refresh slots/
| parse @message /(?<kind>Task timed out after|Status: timeout|ClusterAllFailedError|Redis connection timed out|Failed to refresh slots)/
| stats count(*) as count, min(@timestamp) as first, max(@timestamp) as last by @log, kind
| sort count desc
```

Follow with a timeout-only query:

```sql
fields @timestamp, @log, @message
| filter @message like /Task timed out after|Status: timeout/
| stats count(*) as count by @log
```

Interpretation:

- Redis warning count > 0 and timeout count = 0: current code is bounding impact, but topology/connect instability remains.
- Redis warning count + timeout count > 0: Redis may still be in the Lambda completion path or client lifecycle is leaking.
- Timeout count > 0 without Redis warnings: investigate provider/network/runtime timeout separately; do not overfit to Redis.

## AWS shape checks

Check in this order:

1. ElastiCache replication group: cluster mode, config endpoint, TLS mode, auth, shard/node count, security groups.
2. Lambda function config: VPC subnets/security groups, environment key shape for `REDIS_HOST`, runtime, timeout.
3. SQS event-source mapping: batch size and `ScalingConfig.MaximumConcurrency`.
4. ECS/Service Connect only if considering a Redis proxy tier; existing ECS Service Connect sidecars do not imply Redis proxying.

## Result phrasing

State both:

- whether Redis cluster connection errors are still observed; and
- whether those errors are currently producing Lambda timeout/SQS retry/DLQ impact.

This distinction prevents treating residual bounded warnings as an active delivery incident.
