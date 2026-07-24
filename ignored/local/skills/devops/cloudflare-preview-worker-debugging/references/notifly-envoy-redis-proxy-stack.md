# Notifly AWS-side Envoy Redis proxy for ElastiCache Cluster Mode

Use when setting up or reviewing a Notifly Redis Cluster proxy for Lambda/ECS/Cloudflare Container clients without migrating `notifly-cache-prod`.

## Shape

```text
Cloudflare Container / Lambda canary / VPC clients
  -> notifly-cache-prod-proxy-internal.notifly.tech or internal NLB :6379
  -> Cloudflare Access/Tunnel or AWS internal NLB
  -> ECS Fargate service: notifly-cache-prod-proxy
  -> Envoy Redis proxy filter
  -> existing ElastiCache/Valkey cluster config endpoint
```

Keep the direct cluster tunnel hostname (`notifly-cache-prod-internal.notifly.tech`) separate from the proxy hostname (`notifly-cache-prod-proxy-internal.notifly.tech`). The direct hostname can still surface Redis Cluster `MOVED`/`ASK` to single-node clients; do not use it to validate proxy behavior.

## Terraform PR sequencing

Use stacked PRs when the consumer roots need remote-state outputs from a foundation root:

1. Parent PR: `network` + `ecr` foundation only.
   - ECR repository for image mirroring.
   - Internal NLB, TCP listener, IP target group.
   - No ECS service, no Cloudflare route, no app cutover.
2. Child PR based on the parent branch: `ecs` + `cloudflare`.
   - ECS Fargate Envoy service/task/autoscaling/alarms.
   - Cloudflare DNS + `cloudflare_zero_trust_tunnel_cloudflared_config` ingress.
   - PR body must state that full `terraform plan` fails until the parent has merged/applied and remote state has the new keys.

After parent apply, re-run child plans before merge.

## Naming convention

Align AWS resource names with the DNS/service prefix, not the implementation technology:

- Good: `notifly-cache-prod-proxy`, `notifly-cache-prod-proxy-tg`, `notifly-cache-prod-proxy-internal.notifly.tech`
- Avoid: `envoy-redis-proxy-*` as durable Notifly resource names

AWS load balancer names have a 32-character limit. The full DNS stem `notifly-cache-prod-proxy-internal` is too long, so use `notifly-cache-prod-proxy` for AWS NLB/service/resource names and keep `-internal.notifly.tech` only in DNS/Cloudflare Access.

## Cloudflare Tunnel adoption

The `notifly-vpn` tunnel is remote-configured. Terraform can manage it with `cloudflare_zero_trust_tunnel_cloudflared_config`, but this resource owns the whole ingress list. Preserve existing ingress entries and fallback when adopting.

CI gotcha: the normal Cloudflare DNS token may be able to create the CNAME and read/import the tunnel config but still fail on the tunnel config update with `PUT /accounts/<account>/cfd_tunnel/<tunnel>/configurations: 403 {code:10000, message:"Authentication error"}`. For this Terraform resource, add account permission `Cloudflare One Connector: cloudflared = Edit`; if it still fails because the API path is `cfd_tunnel`, add fallback `Argo Tunnel (Legacy) = Edit`. Keep zone `DNS = Edit` for the CNAME. If token scope cannot be changed, a human can update the tunnel ingress in the Cloudflare dashboard and rerun plan to refresh state.

Example:

Cloudflare Tunnel DNS records should use the bare tunnel target as the CNAME content, e.g. `7d018870-...cfargotunnel.com`. If Slack/GitHub renders that value as `<http://...|...>` or appends `(http://...)`, that is just auto-link formatting around a bare domain; do not add `http://` to Terraform `content`. The actual TCP routing is controlled by the tunnel ingress `service = "tcp://...:6379"`, not by an HTTP URL in DNS.

Example adoption:

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
      { hostname = "notifly-db-prod-internal.notifly.tech", service = "tcp://...:5432" },
      { hostname = "notifly-db-prod-read-only-internal.notifly.tech", service = "tcp://...:5432" },
      { hostname = "notifly-cache-prod-internal.notifly.tech", service = "tcp://clustercfg...:6379" },
      { hostname = "notifly-cache-prod-proxy-internal.notifly.tech", service = "tcp://${data.terraform_remote_state.network.outputs.load_balancer_dns_names["notifly-cache-prod-proxy"]}:6379" },
      { service = "http_status:404" },
    ]
  }
}
```

The existing Access application covers `*-internal.notifly.tech`, so a new Access app is usually unnecessary for this hostname.

The standard standalone-client smoke probe is packaged as `scripts/redis_proxy_smoke_ioredis.js`. Run it from a scratch directory with `npm install --no-audit --no-fund ioredis@5` and `REDIS_HOST=<internal-nlb-dns> REDIS_PORT=6379 node <skill>/scripts/redis_proxy_smoke_ioredis.js`. Success means connect, PING, SET/GET, hash ops, hash-tagged MULTI/EXEC, and 32 cross-slot keys all pass with no MOVED/ASK reaching the client.

## Envoy bootstrap pitfalls

For Redis Cluster mode upstreams:

- Add `lb_policy: CLUSTER_PROVIDED`; otherwise Envoy may not use slot-aware cluster routing.
- Set `enable_redirection: true` in Redis proxy connection pool settings to handle `MOVED`/`ASK`.
- Also set `dns_cache_config` when `enable_redirection` is true; otherwise Envoy logs `redirections without DNS lookups enabled might cause client errors` and may pass MOVED/ASK hostname redirections downstream instead of resolving them. If this warning triggers an error alarm, prefer fixing the source with `dns_cache_config` over a filter-only PR.
- If alerting on Envoy logs, do not match bare lowercase `error` because the above warning contains `client errors` and creates false positive CloudWatch alarms. Prefer matching `[error]`, `[critical]`, `ERROR`, `Exception`, `upstream failure`, or `no upstream host`; but treat this as alarm hygiene, not a substitute for `dns_cache_config`.
- If using `admin.address`, set `admin.access_log_path: /dev/null` or an access log target; Envoy can reject admin config without access logging.
- Remove ECS port mapping `appProtocol = "tcp"`; ECS `appProtocol` only accepts `http`, `http2`, or `grpc`. Use `protocol = "tcp"` only.
- For ElastiCache transit encryption, configure upstream TLS and SNI to the config endpoint host.

Minimal Redis-proxy listener settings with redirection DNS cache:

```yaml
settings:
  op_timeout: 1s
  enable_redirection: true
  dns_cache_config:
    name: notifly_cache_prod_proxy_dns_cache
    dns_lookup_family: V4_ONLY
    dns_refresh_rate: 30s
    dns_min_refresh_rate: 5s
    host_ttl: 300s
  enable_command_stats: true
  max_upstream_unknown_connections:
    value: 100
```

Minimal Redis-cluster upstream pattern:

```yaml
clusters:
  - name: notifly_cache_prod
    connect_timeout: 1s
    dns_lookup_family: V4_ONLY
    lb_policy: CLUSTER_PROVIDED
    load_assignment:
      cluster_name: notifly_cache_prod
      endpoints:
        - lb_endpoints:
            - endpoint:
                address:
                  socket_address:
                    address: clustercfg.notifly-cache-prod.example.cache.amazonaws.com
                    port_value: 6379
    cluster_type:
      name: envoy.clusters.redis
      typed_config:
        "@type": type.googleapis.com/google.protobuf.Struct
        value:
          cluster_refresh_rate: 5s
          cluster_refresh_timeout: 3s
          redirect_refresh_interval: 5s
          redirect_refresh_threshold: 1
          failure_refresh_threshold: 1
    transport_socket:
      name: envoy.transport_sockets.tls
      typed_config:
        "@type": type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext
        sni: clustercfg.notifly-cache-prod.example.cache.amazonaws.com
```

## Validation checklist

- `terraform fmt -check`, `init`, `validate`, `tflint`, `diff --check` for changed roots.
- Foundation PR plan should only create ECR repo/lifecycle and NLB/listener/target group.
- Child PR can validate but plan may fail before parent apply due to expected missing remote-state outputs; document the exact keys.
- After parent apply, test `PING`, `SET/GET`, `HSET/HGET/HINCRBY/EXPIRE`, and hash-tagged `MULTI/EXEC` through the internal NLB first. Use `scripts/redis_proxy_smoke_ioredis.js` as the standard standalone-client probe.
- Test many scratch keys across slots and confirm `MOVED`/`ASK` does not reach the standalone client.
- Treat Cloudflare hostname success separately from AWS/NLB success: the proxy can be healthy and pass Redis client smoke tests while the `*-internal.notifly.tech` path still fails if the tunnel ingress has not been applied. Validate it with `cloudflared access tcp --hostname notifly-cache-prod-proxy-internal.notifly.tech --url 127.0.0.1:16379` using Access service-token env/flags, then run the standalone ioredis smoke probe against `127.0.0.1:16379`.
- ECS task definition changes are replacements in Terraform. If the root has `prevent_destroy` on an `aws_ecs_task_definition`, any later bootstrap/config change will fail plan with `Instance cannot be destroyed`; remove that guard up front or use a reviewed/manual apply path for task definition revisions. For the proxy, if a follow-up PR changes the Envoy bootstrap, make the PR about `dns_cache_config` + removing task-definition `prevent_destroy`, not just an alarm filter tweak. Expect `Plan: 1 to add, 1 to change, 1 to destroy` (`aws_ecs_task_definition` replacement + `aws_ecs_service` in-place update). Main auto-apply may block this as destructive; use `workflow_dispatch action=apply directories=infra/terraform/prod/ap-northeast-2/ecs allow_destructive=true` after review.