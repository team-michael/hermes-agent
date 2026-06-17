# Cloudflare Container + Redis Cluster connectivity options

Use this note after you have proven that a Cloudflare Container can reach the app/DB but Redis Cluster paths fail with `MOVED`/`ASK` or generic write-path `500`s.

## Core mechanism

A Cloudflare Access TCP tunnel gives the container one local TCP endpoint. ElastiCache Redis Cluster is a topology, not a single socket: commands are routed by hash slot and may redirect with `MOVED <slot> <node>:6379` or `ASK ...`.

Therefore the runtime needs one of these:

1. every Redis Cluster node endpoint routable from the container, plus a cluster-aware client and NAT mapping; or
2. a reachable proxy that understands Redis Cluster topology and exposes a single Redis endpoint to the app; or
3. a non-cluster Redis endpoint for preview-only smoke tests.

## Recommended production-shaped pattern: AWS-side Envoy Redis proxy

For Cloudflare Containers that should avoid app rewrites, the cleanest public pattern is usually:

```text
Cloudflare Container
  -> 127.0.0.1:<redis-port>
  -> cloudflared access tcp
  -> AWS VPC internal Redis proxy, e.g. Envoy Redis proxy
  -> ElastiCache Redis Cluster nodes
```

Why this works:

- Cloudflare only tunnels to one stable private endpoint.
- The app can use a single-node Redis connection (`REDIS_MODE=single`).
- Envoy tracks Redis Cluster topology with `CLUSTER SLOTS` and routes commands to the slot owner.
- Envoy Redis proxy supports the common command families used by session/rate-limit paths, including `GET`, `SET`, `INCR`, `EXPIRE`, `TTL`, `DEL`, and scripting commands such as `EVAL`/`EVALSHA`.

Operational shape:

- Deploy Envoy in the AWS VPC, e.g. ECS/Fargate or EC2/private subnet.
- Allow proxy -> ElastiCache nodes on Redis port.
- Allow Cloudflare tunnel connector/origin path -> proxy port.
- Optionally put an internal NLB or service discovery name in front of multiple proxy tasks.
- Cloudflare Container runs `cloudflared access tcp` to the proxy hostname, not to the ElastiCache cluster config endpoint.
- For Notifly-style `*-internal.notifly.tech` hostnames, first inspect the existing Cloudflare Tunnel config and DNS records. Existing DNS may be Terraform-managed while Tunnel ingress is dashboard/remote-config managed. If adopting the tunnel into Terraform, preserve the full ingress list and fallback because `cloudflare_zero_trust_tunnel_cloudflared_config` manages the whole config, not a single route append.
- Check the existing Access app wildcard before creating new policy. A hostname like `notifly-cache-prod-proxy-internal.notifly.tech` is covered if the app domain is already `*-internal.notifly.tech`.

## App/env contract

Avoid deriving topology from hostnames like `REDIS_HOST.includes('dev')`. Add an explicit mode:

```env
REDIS_MODE=single | cluster
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
```

Recommended mapping:

- Cloudflare Container + AWS-side Envoy proxy: `REDIS_MODE=single`, `REDIS_HOST=127.0.0.1`.
- ECS/prod app directly inside the VPC with all cluster nodes routable: `REDIS_MODE=cluster`, `REDIS_HOST=clustercfg...`.
- Preview-only non-cluster Redis: `REDIS_MODE=single`.

## Alternatives and tradeoffs

### Node-specific tunnels + ioredis NAT map

```text
node-0001 -> 127.0.0.1:6381
node-0002 -> 127.0.0.1:6382
...
ioredis natMap maps advertised cluster nodes to local tunnel ports
```

Good when you want to preserve native Redis Cluster semantics in the app. Bad when node counts/failover change often, because workflow/env/wrapper complexity grows quickly.

### Preview-only single-node Redis

Fastest way to unblock UI smoke if production parity is not required. Do not present this as equivalent to ElastiCache Cluster Mode validation.

### RedisLabs `redis-cluster-proxy`

The shape matches the problem, but upstream has warned it is not actively maintained / production discouraged. Treat it as an experiment or preview-only fallback, not the first operating recommendation.

### Cloudflare Workers VPC / VPC Services

Cloudflare Workers VPC is a public path for Workers to reach private TCP/HTTP services through Cloudflare Tunnel/VPC Services. Be careful with Cloudflare Containers:

- the documented binding interface is Worker-oriented, commonly `env.BINDING.fetch(...)`;
- existing Node `ioredis` code inside a Container expects raw Redis TCP sockets;
- this does not transparently turn a Container's Redis client into a cluster-aware private-network client.

So Workers VPC may be useful for HTTP/private service access or future architecture, but it is not currently a simple drop-in fix for Container + `ioredis` + Redis Cluster.

## Notifly pattern: existing Cloudflare Tunnel + AWS-side Envoy proxy

When adding an AWS-side Redis Cluster proxy for Notifly Cloudflare Containers, first inspect the existing Cloudflare Tunnel state before deciding that Dashboard/manual setup is required.

Durable current shape observed for Notifly:

- Existing tunnel: `notifly-vpn`, remotely configured (`remote_config=true`).
- Existing internal TCP hostnames are proxied CNAMEs to `<tunnel-id>.cfargotunnel.com`.
- The Access app `Notifly Internal` covers `*-internal.notifly.tech`, so a new hostname that preserves this suffix pattern does not require a new Access application/policy.
- Existing direct Redis hostname `notifly-cache-prod-internal.notifly.tech` targets the ElastiCache cluster config endpoint directly; this is useful for backward compatibility but is not a proxy validation path.

Recommended proxy hostname pattern:

```text
notifly-cache-prod-proxy-internal.notifly.tech
```

Target shape:

```text
Cloudflare Container
  -> 127.0.0.1:6379
  -> cloudflared access tcp
  -> notifly-cache-prod-proxy-internal.notifly.tech
  -> existing Cloudflare Tunnel / Access
  -> AWS internal NLB :6379
  -> ECS Fargate Envoy Redis proxy
  -> notifly-cache-prod Redis/Valkey Cluster
```

Terraform can manage this if the existing tunnel config is adopted, not merely by adding a DNS record:

1. In the Cloudflare Terraform root, add a proxied CNAME for the new hostname to the existing tunnel target.
2. Manage `cloudflare_zero_trust_tunnel_cloudflared_config` for the existing tunnel and include the **entire** ingress list: all existing RDS/Redis routes, the new proxy route, and the fallback `http_status:404`.
3. Import/adopt the existing tunnel config into Terraform state first. For provider v5.x the import shape is `<account_id>/<tunnel_id>`.
4. Point the new tunnel ingress service at the internal NLB DNS, e.g. `tcp://<envoy-redis-proxy-internal-nlb-dns>:6379`.

Pitfall: `cloudflare_zero_trust_tunnel_cloudflared_config` is whole-config ownership. Do not create a partial resource containing only the new hostname; that can overwrite/drop existing ingress rules. If the NLB DNS is produced by a separate Terraform root, split PRs so the network root applies first, then have the Cloudflare/ECS root consume the output.

Manual Dashboard setup is only the fallback when the team intentionally does not want to adopt the tunnel config into Terraform.

## Verification checklist

Before calling the fix done:

1. Exercise many scratch keys across slots, not one lucky key.
2. Confirm no `MOVED`/`ASK` reaches the app for keys whose slots belong to other shards.
3. Run the actual failing repository/service method in production-mode error handling.
4. Smoke the direct internal API POST before the web-console proxy/UI.
5. Validate the Cloudflare path through the **proxy hostname**, not the legacy direct cluster hostname.
6. Only sign off UI AI assistant after create-session and one small chat message both succeed.

## References

- Envoy Redis proxy docs: https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/other_protocols/redis
- Cloudflare Workers VPC docs: https://developers.cloudflare.com/workers-vpc/
- Cloudflare VPC Services docs: https://developers.cloudflare.com/workers-vpc/configuration/vpc-services/
- Cloudflare Containers outbound handlers: https://developers.cloudflare.com/containers/platform-details/workers-connections/
