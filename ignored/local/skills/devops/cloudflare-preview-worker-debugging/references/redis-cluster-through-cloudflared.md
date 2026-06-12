# Redis Cluster through Cloudflare Access TCP tunnels

Use this note when a Cloudflare Container preview reaches the app and DB, but runtime paths that touch Redis fail or behave like limits are exhausted.

## Failure shape

Typical symptoms:

- Service `/health` is healthy.
- Auth/routing works for read-only endpoints.
- A write path that starts with Redis rate-limit/session accounting returns `500`.
- A UI may show quota exhausted, e.g. `dailySessionsRemaining = 0`, while the expected Redis key is absent when inspected directly.
- Direct service POST and web-console proxy POST both fail, while GET succeeds. That usually moves the suspicion from web-console proxy/auth to service runtime dependencies.

## Mechanism

Cloudflare Access TCP tunnel exposes one local TCP port. Redis Cluster is not a single-node protocol: a command can return `MOVED <slot> <node>:6379` or `ASK ...` and expect the client to reconnect to the slot owner.

If the container only has a tunnel to the cluster config endpoint, then one of these happens:

1. a cluster-aware client learns nodes it cannot reach from inside the container, or
2. a single-node client receives `MOVED` and treats it as an error, or
3. config-endpoint load balancing makes the same key sometimes hit the right shard and sometimes return `MOVED`.

This can manifest as unstable Redis reads/writes even though the tunnel itself is up.

## Diagnostic sequence

1. Split UI/proxy from service runtime:
   - compare web-console proxy POST with direct internal-api POST.
   - if both fail, stop debugging React/UI and inspect service write-path dependencies.
2. Confirm the relevant Redis key directly without printing secrets:
   - check `GET` and `TTL` for the exact rate-limit/session key.
   - if app says quota is exhausted but key is absent, suspect Redis client/tunnel behavior before assuming user limit state.
3. Reproduce locally at the same abstraction level as the failing code, not just with raw Redis probes:
   - start a local TCP forwarder that listens where the app expects Redis and forwards to the Redis Cluster config endpoint/tunnel.
   - run the actual repository/service method that fails (for Notifly AI Agent this was `RateLimitRepository.getRemainingLimit()` and `incrementUsage()`), with `NODE_ENV=production` so development fallback does not mask errors.
   - expected failure shape for this class: `getRemainingLimit()` conservatively returns `0`, while `incrementUsage()` throws a Redis `MOVED <slot> <node>` error; this maps directly to UI quota=0 plus create-session 500.
4. Test cluster behavior against the tunnel/config endpoint:
   - run repeated `GET`/`INCR` for multiple scratch keys, not only one key. Redis Cluster slot distribution can make one key look healthy by luck.
   - look specifically for `MOVED`/`ASK` responses.
   - inspect `CLUSTER SLOTS` to see slot owners.
   - if a standalone client succeeds for a few keys but fails for others, or a cluster client with all nodes NAT-mapped to one local port has partial success, treat that as proof the topology is unstable, not as intermittent Redis health.
5. Tail the Worker while triggering the failing POST so HTTP 500 timing lines up with Redis-touching code.

## Wrapper/proxy remediation pattern

When the goal is to keep app code unchanged, put a small RESP-aware proxy in the container wrapper:

- `cloudflared access tcp` listens on an internal port, e.g. `127.0.0.1:6380`.
- the proxy listens where the app expects Redis, e.g. `127.0.0.1:6379`.
- the proxy forwards commands to the config endpoint tunnel.
- on `MOVED`/`ASK`, it must route the retried command to the indicated slot owner through a reachable path: a node-specific tunnel, an explicit node mapping, or a real cluster-aware proxy inside the reachable network.

Minimum behavior for rate-limit/session paths:

- support simple RESP arrays and bulk strings.
- pass through `GET`, `SET`, `INCR`, `EXPIRE`, `DEL`, `TTL`.
- retry one redirect per command; avoid infinite redirect loops.
- preserve errors that are not cluster redirects.
- keep logging minimal and never print key values if they contain user/project identifiers.

Important pitfall: do **not** call a wrapper fixed just because it catches `MOVED` and retries against the same config endpoint. That can produce partial success by luck because the config endpoint/load balancer may sometimes land on the slot owner. Validate with a batch of scratch keys across many slots; partial success such as “most keys pass, a few still return MOVED” means the proxy is still topology-broken.

## Verification

Before deploying:

- locally run the proxy in front of the same tunnel/config endpoint.
- verify `GET`, `INCR`, `EXPIRE`, `TTL`, `DEL` on a scratch key.
- verify repeated commands for many scratch keys, not just one, because cluster slot ownership is key-dependent.
- verify the actual application method that failed, e.g. AI Agent `RateLimitRepository.getRemainingLimit()` and `incrementUsage()`, under production-mode error handling.
- verify repeated commands for a key whose slot maps away from the initial config endpoint do not surface `MOVED` to the app.

After deploying:

- health check the service.
- call the previously failing direct POST first.
- then repeat the web-console proxy/UI smoke.
- only conclude AI assistant success after create-session and a small chat message both succeed.

## Caveats

- This is a compatibility wrapper, not a substitute for a proper reachable Redis Cluster topology.
- Prefer a native cluster-aware client when every shard endpoint is routable from the runtime.
- Prefer wrapper/proxy only when the constraint is “do not change app code; fix Cloudflare container runtime wiring.”
- Do not persist session-specific project IDs, auth tokens, or raw Redis keys in notes or final summaries.
