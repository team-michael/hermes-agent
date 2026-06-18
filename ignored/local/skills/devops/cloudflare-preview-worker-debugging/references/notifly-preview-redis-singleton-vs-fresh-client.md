# Notifly preview Redis proxy runtime triage: singleton vs fresh client

Use when a Cloudflare preview web-console route returns Redis-backed status as `unavailable` even though Cloudflare deploy/health is green.

## Split the failure boundary

Check these independently:

1. **Deploy freshness** — Worker deployment/version, container rollout, ECR image tag/digest, `/health` SHA.
2. **Worker binding** — `REDIS_HOST` / `REDIS_PROXY_HOST` present in Worker version and forwarded in `worker/index.ts` `envVars`.
3. **Container tunnel** — `cloudflared access tcp` started and local `127.0.0.1:6379` listener becomes reachable before Node starts using it.
4. **Fresh Redis client** — short-lived standalone `ioredis({ host: REDIS_PROXY_HOST, port: 6379, lazyConnect: true, enableOfflineQueue: false })` can `PING` and `HGETALL` the exact monitor key.
5. **Application Redis wrapper** — existing singleton/client-manager read path can still be stale even when (1)-(4) pass.

## High-confidence diagnosis

If fresh standalone `ioredis` succeeds inside the same runtime but the app wrapper returns fallback/unavailable, the cause is not Cloudflare binding or tunnel reachability. It is the app Redis client lifecycle: a long-lived singleton can be stuck in `connecting`/`reconnecting` after tunnel startup/reconnect timing.

## Fix pattern

- Add a bounded tunnel readiness wait in the entrypoint instead of a blind fixed sleep.
- For operational Redis reads behind a Cloudflare Access TCP proxy, consider a short-lived standalone client for that read path to avoid stale singleton state.
- Keep `connectTimeout`, `commandTimeout`, `maxRetriesPerRequest`, and `enableOfflineQueue: false` bounded.
- If changing a shared Redis manager, add stale-client reconnect/retry tests; but avoid permanent verbose lifecycle logging.

## Temporary diagnostics cleanup

Diagnostic endpoints/logs are useful to prove the boundary, but they should not survive final PR cleanup unless explicitly productized.

Before final handoff:

- Remove worker/container diagnostic endpoints.
- Remove env-presence and secret-shape logging.
- Remove Redis lifecycle debug logs added only for investigation.
- Verify diagnostic URLs return 404 after preview deploy.

## UI/product note

If Redis is unavailable or the monitor hash is missing/expired, prefer hiding a real-time monitor card and relying on final stats fallback unless the product explicitly wants an outage banner. Avoid showing a scary “실시간 조회 불가” card for a best-effort Redis monitor.
