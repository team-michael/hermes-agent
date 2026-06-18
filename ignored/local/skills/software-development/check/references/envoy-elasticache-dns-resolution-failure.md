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

### See also

- `oncall-cloudwatch-alert-triage` — general ECS console error alert methodology
- `references/rds-aurora-replica-recovery-conflict.md` — related infrastructure-level DB connectivity patterns
