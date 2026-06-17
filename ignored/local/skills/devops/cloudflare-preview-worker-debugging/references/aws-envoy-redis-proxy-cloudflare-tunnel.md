# AWS-side Envoy Redis proxy for Cloudflare Container Redis Cluster paths

Use this when Cloudflare Containers/Workers need a single reachable Redis endpoint but the production cache is ElastiCache/Valkey Redis Cluster mode.

## Production-shaped topology

```text
Cloudflare Container
  -> 127.0.0.1:6379
  -> cloudflared access tcp
  -> <cache-env-proxy-internal.notifly.tech>
  -> Cloudflare Access + existing remotely configured tunnel
  -> AWS internal NLB TCP :6379
  -> ECS/Fargate Envoy Redis proxy
  -> existing ElastiCache/Valkey cluster config endpoint and shard nodes
```

This keeps Cloudflare tunneling to **one stable proxy endpoint**. The app uses a single-node/RESP2 Redis client locally; Envoy owns Redis Cluster topology and `MOVED`/`ASK` handling.

## Split Terraform into dependency-safe PRs

When the repo's Terraform roots apply independently or in parallel, do not put cross-root producer/consumer changes in one PR unless apply order is manually guaranteed.

Recommended Notifly shape:

1. **Foundation PR**
   - `network`: internal NLB, TCP listener, IP target group, remote-state outputs.
   - `ecr`: mirror repository for upstream Envoy image.
   - No ECS service, no Cloudflare route, no app cutover.
2. **Stacked service PR** based on the foundation branch
   - `ecs`: Envoy task/service/autoscaling/logs/alarms.
   - `cloudflare`: DNS + tunnel ingress route.
   - Base the PR on the foundation branch so the diff excludes foundation files.
   - State clearly that `terraform plan` for roots consuming network remote-state will fail until the foundation PR is merged/applied.

## Cloudflare tunnel adoption

Existing remotely configured Cloudflare Tunnel routes can be managed by Terraform, but the tunnel config resource manages the **entire ingress list**, not just one hostname.

Safe pattern:

```hcl
import {
  to = cloudflare_zero_trust_tunnel_cloudflared_config.notifly_vpn
  id = "<account_id>/<tunnel_id>"
}

resource "cloudflare_zero_trust_tunnel_cloudflared_config" "notifly_vpn" {
  account_id = local.cloudflare_account_id
  tunnel_id  = local.notifly_vpn_tunnel_id
  source     = "cloudflare"

  config = {
    ingress = [
      # preserve all existing hostnames first
      { hostname = "..." service = "tcp://..." },
      # append the proxy hostname
      { hostname = "notifly-cache-prod-proxy-internal.notifly.tech" service = "tcp://<internal-nlb-dns>:6379" },
      { service = "http_status:404" },
    ]
  }
}
```

Also add a proxied CNAME record to `<tunnel-id>.cfargotunnel.com`. Existing Access apps that cover `*-internal.notifly.tech` may already protect the new hostname, so verify before creating another Access app.

## Envoy Redis config pitfalls

For an Envoy Redis Cluster upstream:

- Add `lb_policy: CLUSTER_PROVIDED`; otherwise slot-aware routing may degrade to default load balancing and rely too much on redirects.
- Add `admin.access_log_path: /dev/null` if enabling an admin listener; otherwise Envoy may reject the bootstrap.
- Do **not** set ECS `portMappings[].appProtocol = "tcp"`. ECS only accepts `http`, `http2`, or `grpc` there; use `protocol = "tcp"` only.
- Use upstream TLS/SNI when ElastiCache transit encryption is enabled.
- Keep `enable_redirection: true` and bounded `op_timeout` / topology refresh timeouts.
- Envoy Redis supports RESP2; avoid RESP3/`HELLO 3` clients.

## Verification checklist

After both PRs apply:

1. ECS service has the expected desired/running count.
2. NLB target group is healthy.
3. VPC client can connect as standalone Redis/RESP2 to the internal NLB.
4. Cloudflare Container path works via `cloudflared access tcp --hostname <proxy-host> --url 127.0.0.1:6379`.
5. Test `PING`, `SET/GET`, `HSET/HGET/HINCRBY/EXPIRE`, and hash-tagged `MULTI/EXEC`.
6. Exercise multiple scratch keys across slots and confirm `MOVED`/`ASK` does not reach the client.
7. Do not route pub/sub or strong-consistency lock/idempotency paths through the proxy until separately validated.
