# Notifly CF Container Redis proxy: singleton client vs fresh proxy client

Use when a Cloudflare preview web-console/container can reach Redis through `cloudflared access tcp`, but app-level Redis-backed UI/API still returns `unavailable`.

## High-confidence split

Check the layers separately:

1. Worker binding / container env passthrough: `REDIS_HOST`, `REDIS_PROXY_HOST`, `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET` are present without printing values. In Notifly web-console previews, `REDIS_PROXY_HOST=127.0.0.1` is set by `cf_deploy.yml`/wrangler vars and forwarded by `worker/index.ts`; `entrypoint.sh` does not set it.
2. Entrypoint tunnel readiness: `cloudflared access tcp --hostname cache-proxy-prod-internal.notifly.tech --url 127.0.0.1:6379` is listening before Node starts. `wait_for_tunnel_listener` proves only local TCP accept, not Cloudflare Access/upstream proxy nor Redis protocol readiness.
3. Fresh standalone Redis probe from inside the Node/container context: `new Redis({ host: REDIS_PROXY_HOST, port: 6379, lazyConnect: true, enableOfflineQueue: false, maxRetriesPerRequest: 1, connectTimeout/commandTimeout ~1500 }).connect(); ping(); hgetall(key)`.
4. App path using shared Redis manager/singleton.

If (1)-(3) pass but (4) fails, the problem is usually not Cloudflare binding or Access. It is a client lifecycle boundary: a long-lived `ioredis`/RedisManager instance may have initialized before the tunnel was ready or become stuck in `connecting`/`reconnecting` after tunnel startup.

## Remediation pattern

- Prefer fixing the shared Redis boundary (`@notifly/redis` / `RedisManager`) over adding package-local fresh `ioredis` fallbacks. Keep Redis access ownership centralized unless the fresh client is only a temporary diagnostic probe.
- When `REDIS_PROXY_HOST` is set, treat that value as the standalone proxy/tunnel endpoint. Do not infer proxy mode from `REDIS_HOST=127.0.0.1` alone; Notifly Cloudflare preview currently passes both `REDIS_HOST=127.0.0.1` and `REDIS_PROXY_HOST=127.0.0.1` via `cf_deploy.yml`/wrangler vars.
- Use ioredis-native controls at the manager boundary: `lazyConnect: true`, explicit `connect()`, `enableReadyCheck: true`, `enableOfflineQueue: false`, `autoResendUnfulfilledCommands: false`, bounded `connectTimeout`/`commandTimeout`, short jittered `retryStrategy`, and `maxRetriesPerRequest: 1`.
- Add manager-level readiness/reset policy around those ioredis primitives, but split warmup from actual command paths:
  - `initialize()` / module-load warmup may do a longer ready wait and one reset+retry to improve cold-start connection quality.
  - actual best-effort command paths should use a short command-ready timeout, reset stale clients on failure, and return fallback without retrying the same command; otherwise Redis instability can add `readyTimeout * 2` latency to delivery/Lambda completion paths.
- Keep the existing cluster path for non-proxy environments. Lambda delivery paths intentionally use `REDIS_HOST`/cluster, not `REDIS_PROXY_HOST`; do not treat proxy-mode fixes as Lambda slot-refresh remediation unless Lambda env actually includes `REDIS_PROXY_HOST`.
- Add readiness wait in `entrypoint.sh` before starting Node so the local tunnel listener exists before app code warms Redis clients, but remember this only proves local TCP listener readiness, not end-to-end Redis command readiness.

  - `enableOfflineQueue: false` so pre-ready commands fail instead of hiding behind an offline queue;
  - bounded `connectTimeout` and `commandTimeout` (about 1500ms for the Notifly CF Redis proxy path);
  - `maxRetriesPerRequest: 1` and short `retryStrategy` for transient socket reconnects;
  - inspect `status`/`ready`/`error`/`end`; if the singleton remains `connecting`/`reconnecting`/`end` or times out, disconnect/reset and create a new manager-owned client before one bounded retry.
- Prefer `REDIS_PROXY_HOST` as the explicit signal for standalone proxy mode. Do not claim loopback `REDIS_HOST` alone means proxy unless the deploy workflow/env contract proves it.
- Avoid blanket command replay for non-idempotent Redis operations such as increments; connection establishment can be retried, but command-level retry after ambiguous send may duplicate effects.

## UI behavior lesson

Do not show real-time delivery UI when Redis is missing or unavailable. Treat only a Redis snapshot (`source='redis'`) as the real-time source. Redis missing, Redis failure, or final stats fallback (`source='stats'`) should hide list/detail real-time UI and keep persisted/statistical UI as the source of truth.

## Cleanup rule

Diagnostic endpoints and verbose env/tunnel logging are temporary. After proving the hypothesis:

- remove diagnostic API routes such as `/api/diagnostics/...`,
- remove Worker diagnostic routes such as `/__diagnostics/...`,
- remove env-presence and tunnel PID logs,
- keep only functional readiness waits and production-safe error handling,
- verify diagnostic routes return 404 after deploy.
