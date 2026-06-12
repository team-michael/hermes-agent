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

## Verification checklist

Before calling the fix done:

1. Exercise many scratch keys across slots, not one lucky key.
2. Confirm no `MOVED`/`ASK` reaches the app for keys whose slots belong to other shards.
3. Run the actual failing repository/service method in production-mode error handling.
4. Smoke the direct internal API POST before the web-console proxy/UI.
5. Only sign off UI AI assistant after create-session and one small chat message both succeed.

## References

- Envoy Redis proxy docs: https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/other_protocols/redis
- Cloudflare Workers VPC docs: https://developers.cloudflare.com/workers-vpc/
- Cloudflare VPC Services docs: https://developers.cloudflare.com/workers-vpc/configuration/vpc-services/
- Cloudflare Containers outbound handlers: https://developers.cloudflare.com/containers/platform-details/workers-connections/
