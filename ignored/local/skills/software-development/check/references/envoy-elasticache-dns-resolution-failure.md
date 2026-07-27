# Envoy Redis cluster proxy DNS resolution failure

## Pattern

An Envoy proxy deployed as an ECS service (`notifly-cache-prod-proxy`) that forwards traffic to an ElastiCache Redis cluster fails to resolve cluster node hostnames.

### Alarm signature

- **Log group**: `/aws/ecs/notifly-services-prod/notifly-cache-prod-proxy`
- **Metric filter**: `%error|ERROR|Exception|upstream failure|no upstream host%`
- **Alarm**: `notifly-cache-prod-proxy console error` (namespace `ConsoleErrors`)
- **Threshold**: Sum > 1.0 per 60s

### Error logs

```
[2026-06-17 04:37:15.705][1][error][upstream] [source/extensions/clusters/redis/redis_cluster.cc:384] Unable to resolve cluster slot primary hostname notifly-cache-prod-0001-002.notifly-cache-prod.bcs
[2026-06-17 04:37:16.411][1][error][upstream] [source/extensions/clusters/redis/redis_cluster.cc:384] Unable to resolve cluster slot primary hostname notifly-cache-prod-0002-001.notifly-cache-prod.bcs
[2026-06-17 04:37:21.463][1][warning][main] [source/server/server.cc:976] caught ENVOY_SIGTERM
[2026-06-17 04:37:21.463][1][info][main] [source/server/server.cc:1120] shutting down server instance
```

### Root causes

1. **VPC DNS resolver timeout or service discovery delay**: ElastiCache cluster node DNS records (`.bcs` suffix indicates Elastic Cluster Service FQDN) are not resolving from the Envoy proxy's VPC. This can occur when:
   - VPC DNS (Route53 Resolver) is overloaded or temporarily unavailable.
   - ElastiCache cluster is undergoing node maintenance, scaling, or failover and DNS entries are not synchronized.
   - Envoy container DNS resolver configuration is stale or points to incorrect nameservers.

2. **ElastiCache cluster topology change**: Node addition/removal without corresponding DNS record updates can cause some slot-to-hostname mappings to fail resolution.

3. **Network connectivity issue**: Security group, NACLs, or route table misconfiguration prevents DNS queries from reaching the resolver.

### Investigation steps

1. **Verify ElastiCache cluster status**:
   ```bash
   aws elasticache describe-replication-groups \
     --region ap-northeast-2 \
     --replication-group-id notifly-cache-prod \
     --query 'ReplicationGroups[0].{Status:Status,ClusterEnabled:ClusterEnabled,MemberClusters:MemberClusters}'
   ```
   Expected: `Status: available`, `ClusterEnabled: true`, all member clusters listed.

2. **Check DNS resolution from VPC**:
   ```bash
   # From an EC2 instance or ECS task in the same VPC
   nslookup notifly-cache-prod-0001-002.notifly-cache-prod.bcs
   nslookup notifly-cache-prod-0002-001.notifly-cache-prod.bcs
   ```
   If resolution fails or times out, the issue is VPC DNS or ElastiCache DNS record synchronization.

3. **Verify Envoy task status**:
   ```bash
   aws ecs describe-services \
     --cluster notifly-services-prod \
     --services notifly-cache-prod-proxy \
     --region ap-northeast-2 \
     --query 'services[0].{RunningCount:runningCount,DesiredCount:desiredCount,Events:events[0:5]}'
   ```
   Look for: `runningCount < desiredCount` and events like `task remained in deregistered state for too long` (indicates healthcheck/DNS failures killed the task).

4. **Check VPC/security group configuration**:
   - Verify Envoy task security group allows outbound DNS (port 53 UDP/TCP).
   - Verify route to VPC DNS resolver (typically `.2` on the VPC CIDR, e.g., `10.0.0.2`).
   - Check Route53 Resolver endpoint association with the task VPC.

5. **Review Envoy configuration**:
   - Confirm Envoy cluster definition points to `.bcs` domain (ElastiCache service discovery FQDN).
   - Check DNS timeout and retry settings in the Envoy config (`source/extensions/clusters/redis/redis_cluster.cc`).

### Classification

- **Pattern**: Infrastructure-level DNS resolution failure, not application code.
- **Scope**: Service-wide (all Redis clients affected when proxy is down).
- **Severity**: 
  - **Transient (1-2 ERROR logs, recovered within minutes)**: `no_action` if ElastiCache status is `available` and DNS resolves after recovery.
  - **Sustained (5+ ERROR logs, tasks deregistrated, 0/N running)**: `needs_fix` — escalate to infrastructure team for VPC DNS verification, ElastiCache DNS sync audit, or security group rules.

### Long-term mitigation

1. **Healthcheck tuning**: Increase Envoy startup timeout in ECS task definition to allow DNS resolver warm-up.
2. **DNS caching**: Consider local dnsmasq or systemd-resolved inside Envoy container to cache ElastiCache cluster topology.
3. **Metrics**: Add Envoy upstream cluster health metric (`envoy_cluster_membership_healthy`) to CloudWatch to detect DNS-caused failures earlier than proxy restart.
4. **Runbook**: Document VPC DNS verification and ElastiCache DNS record sync checks as part of on-call playbook for `notifly-cache-prod-proxy console error` alarms.

### Code references

- Envoy Redis cluster extension: `source/extensions/clusters/redis/redis_cluster.cc:384`
- Envoy DNS resolver: Envoy's built-in c-ares-based resolver (configurable via `dns_resolvers` in cluster config)
- ElastiCache service discovery: AWS ElastiCache uses `.bcs.<region>.cache.amazonaws.com` FQDN for cluster mode nodes

## Variant: `cache-proxy-prod console error` (2026-06-23 session)

A newer deployment of the Envoy Redis proxy uses different naming:

- **Alarm name**: `cache-proxy-prod console error`
- **Log group**: `/aws/ecs/notifly-services-prod/cache-proxy`
- **Metric filter**: `%error|ERROR|Exception|upstream failure|no upstream host%`
- **Threshold**: Sum ≥ 1.0 per 60s (more sensitive than the `notifly-cache-prod-proxy` variant's `> 1.0`)
- **DNS suffix**: `.bcshxz.apn2.cache.amazonaws.com` (full ElastiCache FQDN, not truncated `.bcs`)
- **ElastiCache cluster**: `notifly-cache-prod` (Valkey engine, 2 shards × 2 nodes: `0001-001`, `0001-002`, `0002-001`, `0002-002`)
- **Transition pattern**: `INSUFFICIENT_DATA → ALARM` (not `OK → ALARM`), same as periodic batch alarms

### Error signature (identical Envoy source)

```
[2026-06-23 03:11:07.938][1][error][upstream] [source/extensions/clusters/redis/redis_cluster.cc:384] Unable to resolve cluster slot primary hostname notifly-cache-prod-0002-001.notifly-cache-prod.bcshxz.apn2.cache.amazonaws.com
[2026-06-23 03:11:08.024][1][error][upstream] [source/extensions/clusters/redis/redis_cluster.cc:384] Unable to resolve cluster slot primary hostname notifly-cache-prod-0001-002.notifly-cache-prod.bcshxz.apn2.cache.amazonaws.com
```

### Session findings (2026-06-23)

- **Recurrence**: 4 occurrences in 30 days (6/19 14:13, 6/20 00:57, 6/23 03:12, 6/23 08:58 UTC), each producing 1–2 log lines within 1 second, then no further errors. The 08:58 UTC alarm produced only 1 error line (`0001-002` only), showing the pattern can emit 1 or 2 lines per occurrence.
- **DNS resolution at investigation time**: Both hostnames resolved successfully via `nslookup` (10.0.155.108, 10.0.130.71).
- **ElastiCache status**: All 4 nodes `available`, engine Valkey 8.0.1, node type `cache.t4g.micro`, no replication-group or cache-cluster events in the alarm windows. AutomaticFailover enabled, 2 shards × 2 nodes.
- **ElastiCache snapshot window correlation**: The 03:12 UTC alarm fell within the daily snapshot window (02:30–03:30 UTC). The snapshot creates a brief I/O and CPU spike on the snapshot-target node that can cause transient DNS resolution delay from the Envoy proxy. However, 2 of 4 alarms (6/19 14:13, 6/20 00:57, 6/23 08:58) occurred outside the snapshot window, so the snapshot is a contributing factor for some occurrences but not the sole root cause.
- **EngineCPUUtilization**: 2–3% on both `0001-002` and `0002-001` during the 08:57 UTC alarm window, confirming no real load issue.
- **Customer impact**: None — errors lasted <1 second, proxy self-recovered, cache operations continued normally.
- **Classification**: `no_action` — transient DNS resolution spike during Envoy Redis cluster slot refresh.
- **Long-term suggestion**: The metric filter `%error|ERROR|Exception|upstream failure|no upstream host%` is overly broad for this service. Consider raising the alarm threshold to `Sum >= 5` over `Period 300s`, or adding a filter exclusion for `redis_cluster.cc` transient DNS errors to reduce alert noise.

### Pitfall — `filterPattern='ERROR'` does not match Envoy lowercase `[error]`

Envoy logs use lowercase `[error]` as the log level label. When performing manual `filter_log_events` with `filterPattern='ERROR'`, zero results are returned even though the triggering log lines exist in the stream. The metric filter pattern `%error|ERROR|Exception|upstream failure|no upstream host%` catches both cases, but manual follow-up must use either no filter pattern or a case-insensitive approach.

**Fix**: Use `filter_log_events` with no `filterPattern` (broad scan) or use `filterPattern='error'` (lowercase) when investigating Envoy proxy logs.

### Pitfall — helper `current_trigger_contexts` empty despite alarm breach

The helper returned `current_trigger_contexts: []` for this alarm even though the alarm window (03:11:00–03:12:00 UTC) contained 2 matching log events at 03:11:07 and 03:11:08. This is the CloudWatch Logs Insights ingestion delay pattern already documented in SKILL.md. Manual `filter_log_events` (the direct API, not Logs Insights) found the events immediately. When the helper reports empty `current_trigger_contexts` for a cache-proxy alarm, fall back to direct `filter_log_events` with no filter pattern on the exact alarm window.

### Verification commands (2026-06-23 session)

```python
# DNS resolution check (from the Hermes host — not VPC-internal, but confirms record exists)
import socket
socket.gethostbyname("notifly-cache-prod-0002-001.notifly-cache-prod.bcshxz.apn2.cache.amazonaws.com")

# ElastiCache cluster status
aws elasticache describe-replication-groups --region ap-northeast-2 \
  --query 'ReplicationGroups[?ReplicationGroupId==`notifly-cache-prod`].{Status:Status,Engine:Engine,NodeGroups:NodeGroups[*].{NodeGroupId:NodeGroupId,Status:Status,Members:NodeGroupMembers[*].{ClusterId:CacheClusterId,NodeId:CacheNodeId,Role:CurrentRole}}}' \
  --output json

# Manual log search (no filterPattern — avoids Envoy lowercase [error] pitfall)
aws logs filter-log-events \
  --log-group-name /aws/ecs/notifly-services-prod/cache-proxy \
  --start-time $(date -d '2026-06-23 03:10:00 UTC' +%s)000 \
  --end-time $(date -d '2026-06-23 03:13:00 UTC' +%s)000 \
  --region ap-northeast-2
```

### See also

- `oncall-cloudwatch-alert-triage` — general ECS console error alert methodology
- `references/rds-aurora-replica-recovery-conflict.md` — related infrastructure-level DB connectivity patterns
