# AWS-side Envoy Redis proxy + Cloudflare tunnel pattern

Use this when Redis Cluster access from Lambda/ECS/Cloudflare Containers fails or is risky because the runtime can only reach one stable TCP endpoint while ElastiCache/Valkey Cluster requires slot-aware routing.

## Core recommendation

Expose a **new proxy endpoint**, not the existing direct cluster-config tunnel:

```text
Cloudflare Container
  -> 127.0.0.1:6379
  -> cloudflared access tcp
  -> notifly-cache-proxy-prod-internal.notifly.tech
  -> Cloudflare Access/Tunnel
  -> AWS internal NLB TCP :6379
  -> ECS Fargate Envoy Redis proxy
  -> ElastiCache/Valkey cluster config endpoint + shard nodes
```

Keep any existing hostname such as `notifly-cache-prod-internal.notifly.tech` if it points directly at `clustercfg...:6379`. That direct tunnel is useful as a baseline, but it is **not** proof that the proxy solves Redis Cluster topology problems.

## Why this shape

A Cloudflare Access TCP tunnel gives the container one local port. Redis Cluster is a topology: `MOVED`/`ASK` can require reconnecting to a different shard endpoint. Envoy Redis proxy keeps the topology handling inside AWS where all shard nodes are routable, and gives remote runtimes a single RESP2 Redis endpoint.

## Terraform planning checklist

For a Notifly-style AWS setup:

1. Add an internal NLB with TCP listener/target group on `6379`.
2. Add an ECS/Fargate `envoy-redis-proxy` service in the target prod/dev ECS cluster.
3. Use Fargate service autoscaling, not EC2 ASG:
   - desired/min 2
   - max 4-6 initially
   - CPU/memory target tracking
   - prefer FARGATE over Spot if the proxy becomes shared data-path infrastructure.
4. Add an ECR repository for future upstream Envoy image mirroring, but avoid a custom application image if the official Envoy image plus runtime/bootstrap config is enough.
5. Configure Envoy Redis filter for Redis Cluster support:
   - downstream RESP2 on `0.0.0.0:6379`
   - upstream TLS if ElastiCache transit encryption is enabled/preferred
   - cluster topology refresh via `CLUSTER SLOTS`
   - bounded operation/refresh timeouts
   - redirection handling and DNS cache for hostname redirects where needed.
6. Add Cloudflare Zero Trust tunnel public hostname, e.g. `notifly-cache-proxy-prod-internal.notifly.tech`, targeting `tcp://<internal-nlb-dns>:6379`.
7. Do not change app `REDIS_HOST` globally in the proxy infra PR. Set up first, then canary selected clients.

## App/runtime contract

For Cloudflare Containers behind the proxy:

```env
REDIS_MODE=single
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
```

Wrapper/tunnel example:

```bash
cloudflared access tcp \
  --hostname notifly-cache-proxy-prod-internal.notifly.tech \
  --url 127.0.0.1:6379
```

For plain Cloudflare Workers, do **not** assume a Container-style `cloudflared` process exists. Validate the exact runtime path first:

- Workers VPC / VPC Services may be the right private-network primitive for Worker-oriented bindings.
- If raw Redis TCP is not practical from the Worker runtime, expose a narrow HTTP internal service/shim instead of making the Worker speak Redis directly.

## Usage separation

Good initial candidates:

- best-effort counters
- delivery monitor/cache paths
- rate-limit/session-like paths after command compatibility validation

Avoid global cutover at first:

- Redis `SUBSCRIBE`/subscriber paths, because Envoy Redis docs include `PUBLISH` but not `SUBSCRIBE`.
- lock/idempotency/strong-consistency paths until canary proves behavior.

## Verification

Before signing off:

1. Test from inside the VPC against the NLB/proxy with a normal Redis client, not a cluster client.
2. Test through Cloudflare Access TCP tunnel from a Container-like environment.
3. Use many scratch keys across slots, not one lucky key.
4. Confirm no `MOVED`/`ASK` reaches the app/client.
5. Test actual command families used by the target path: `PING`, `GET/SET`, `HSET/HGET/HINCRBY/EXPIRE`, `MULTI/EXEC` on same hash-tagged key.
6. Confirm existing direct Redis clients are unchanged and ElastiCache is not replaced/migrated.

## PR wording pitfall

Be explicit that the first PR is infrastructure-only:

- creates proxy endpoint
- no app routing cutover
- no Redis cluster migration
- no global `REDIS_HOST` replacement
- later code/env PRs opt in by usage profile
