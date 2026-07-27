# Redis Cluster through Cloudflare Access TCP tunnels

Use this note when a Cloudflare Container preview reaches the app and DB, but runtime paths that touch Redis fail or behave like limits are exhausted.

## Failure shape

Typical symptoms:

- Service `/health` is healthy.
- Auth/routing works for read-only endpoints.
- A write path that starts with Redis rate-limit/session accounting returns `500`.
- A UI may show quota exhausted, e.g. `dailySessionsRemaining = 0`, while the expected Redis key is absent when inspected directly.
- A Notifly web-console realtime monitor that is Redis-backed may render a graceful fallback such as `일시 조회 불가` / `status: unavailable`, while the slower DB/stat fallback still renders ordinary counts. If the exact Redis monitor hash exists when probed through a trusted Redis path, treat this as preview runtime Redis connectivity/topology first, not as missing campaign data or React rendering.
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
2. For Notifly web-console preview endpoints behind Cloudflare Access, first prove the deployed Worker/container SHA and auth boundary:
   - `curl /health` with `CF-Access-Client-Id` / `CF-Access-Client-Secret` and check `.sha`.
   - Remember preview health may report a GitHub PR merge ref SHA (`refs/pull/<n>/merge`) whose parents include `origin/main` + the PR head, not the raw PR head SHA.
   - For API smoke without browser cookies, the legacy internal bypass can be used only as a diagnostic: send the CF Access service-token headers plus `Authorization: Basic notifly-internal-request` and `X-Forwarded-For: 127.0.0.1`. Do not use this as a customer-path/auth signoff.
3. Confirm the relevant Redis key directly without printing secrets:
   - check `GET`/`HGETALL` and `TTL` for the exact rate-limit/session/monitor key.
   - if app says quota is exhausted or realtime monitor is unavailable but the key exists and has sane fields, suspect preview runtime Redis connectivity before assuming application data state.
4. Inspect the Worker bindings and container wrapper, not only app code:
   - Cloudflare Worker `vars` can contain `REDIS_HOST=127.0.0.1` while the container only reaches Redis if `entrypoint.sh` actually starts `cloudflared access tcp`.
   - For proxy-mode previews, verify all three layers separately:
     1. Worker binding includes `REDIS_PROXY_HOST=127.0.0.1`.
     2. `worker/index.ts` passes `REDIS_PROXY_HOST` through `envVars` to the container.
     3. `entrypoint.sh` opens `cloudflared access tcp` to the proxy hostname (for Notifly, currently `cache-proxy-prod-internal.notifly.tech`) on the same local port the app uses.
   - If Worker bindings show `REDIS_PROXY_HOST=127.0.0.1` and a local EC2 probe through the proxy hostname succeeds, but the preview app still returns `status: unavailable`, do **not** conclude “the proxy host did not get configured.” The remaining suspects are container runtime: the Redis tunnel process is not running/healthy inside the container, or the Node process did not receive/apply `REDIS_PROXY_HOST` and is still using the cluster client against `127.0.0.1`.
   - If the wrapper gates tunnel startup on an env var such as `CLOUDFLARE_APPLICATION_ID`, verify that variable is present in Worker/container bindings or injected by the runtime before blaming Redis data.
5. Reproduce locally at the same abstraction level as the failing code, not just with raw Redis probes:
   - start a local TCP forwarder that listens where the app expects Redis and forwards to the Redis Cluster config endpoint/tunnel.
   - run the actual repository/service method that fails (for Notifly AI Agent this was `RateLimitRepository.getRemainingLimit()` and `incrementUsage()`; for campaign delivery monitor this is `readCampaignDeliveryMonitor()` / the `/api/projects/<projectId>/campaigns/<campaignId>/delivery` route), with production-mode error handling so development fallback does not mask errors.
   - expected failure shape for this class: `getRemainingLimit()` conservatively returns `0`, `readCampaignDeliveryMonitor()` returns `kind: 'unavailable'`, or `incrementUsage()` throws a Redis `MOVED <slot> <node>` error. These map directly to UI quota=0, realtime monitor unavailable, or create-session 500.
6. Test cluster behavior against the tunnel/config endpoint:
   - run repeated `GET`/`HGETALL`/`INCR` for multiple scratch keys, not only one key. Redis Cluster slot distribution can make one key look healthy by luck.
   - look specifically for `MOVED`/`ASK` responses.
   - inspect `CLUSTER SLOTS` to see slot owners.
   - if a standalone client succeeds for a few keys but fails for others, or a cluster client with all nodes NAT-mapped to one local port has partial success, treat that as proof the topology is unstable, not as intermittent Redis health.
7. Tail the Worker while triggering the failing POST so HTTP 500 or graceful-unavailable timing lines up with Redis-touching code.

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
- for Notifly web-console preview, also smoke the deployed preview API directly with Cloudflare Access headers plus the diagnostic internal-auth bypass. Expected fixed shape for a Redis-backed campaign monitor is `source: 'redis'`; `source: 'stats', status: 'unavailable'` means the container still cannot read Redis even if the DB/stat fallback is healthy.
- do not tail or quote generic container startup logs if they print full `envVars`; redact first or add a targeted diagnostic. Some web-console `onStart` logs include secret-bearing env values.
- do not over-trust an EC2/local Hermes probe: the same `cloudflared access tcp` + Redis proxy/single-client probe can succeed from EC2 while the Cloudflare Container still fails because the process/env/tunnel inside the container is different. Treat app endpoint behavior from the preview container as the deciding signal.

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
