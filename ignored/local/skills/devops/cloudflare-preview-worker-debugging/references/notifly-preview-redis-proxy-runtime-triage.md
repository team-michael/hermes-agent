# Notifly Cloudflare preview Redis proxy runtime triage

Use this when a web-console Cloudflare preview shows Redis-backed features as unavailable even though the preview itself is serving and database-backed fallback paths still work.

## High-signal symptom

The preview API returns a fallback/unavailable shape for a Redis-backed monitor, e.g. realtime delivery monitor reads fail, while:

- the campaign/project exists,
- PostgreSQL/stat fallback paths still respond,
- direct local Cloudflare Access TCP tunnel to the Redis proxy endpoint can `PING`/`HGETALL`, and
- Worker bindings appear to contain `REDIS_HOST=127.0.0.1` and `REDIS_PROXY_HOST=127.0.0.1`.

Interpretation: do **not** stop at “the Worker has the env var” or “the proxy endpoint works locally”. The remaining failure is usually inside the container runtime path.

## Layer split

Check these layers separately:

1. **Worker binding**: `REDIS_HOST`, `REDIS_PROXY_HOST`, deploy SHA, and Access/client values exist in the Worker version/settings. Confirm presence only; never print secrets.
2. **Worker → container passthrough**: `worker/index.ts` forwards `REDIS_HOST` and `REDIS_PROXY_HOST` in `envVars`; `worker/env.d.ts` agrees.
3. **Container entrypoint**: `entrypoint.sh` starts `cloudflared access tcp --hostname cache-proxy-... --url 127.0.0.1:6379` before `node server.js`.
4. **Node runtime choice**: the app actually sees `process.env.REDIS_PROXY_HOST` and constructs a standalone/proxy Redis client, not a Cluster client pointed at `127.0.0.1`.
5. **Runtime tunnel liveness**: inside the container, the Redis `cloudflared` process is still alive and listening on the expected local port when the app reads Redis.

## Fast local proxy smoke

When credentials are present locally, open a tunnel on a non-conflicting local port and smoke it with the same client library used by web-console. Keep the tunnel command out of logs if it would expose token values.

Example pattern:

```bash
cloudflared access tcp \
  --hostname 'cache-proxy-prod-internal.notifly.tech' \
  --url 127.0.0.1:16380 \
  --id "$CF_ACCESS_CLIENT_ID" \
  --secret "$CF_ACCESS_CLIENT_SECRET"
```

Then from the repo, use the service dependency context rather than assuming global packages:

```bash
PATH=/home/ubuntu/.nvm/versions/node/v24.15.0/bin:$PATH \
  pnpm --filter web-console exec node -e '/* require("ioredis") and PING 127.0.0.1:16380 */'
```

Expected successful signal:

```json
{"ping":"PONG","status":"ready"}
```

If this succeeds locally, the proxy endpoint and Access route are healthy enough. The bug is more likely container startup/env/runtime behavior.

## Watch notification pitfall

Hermes background `watch_patterns` notifications can arrive after the process state has changed. Treat `Start Websocket listener` as “this line appeared at some point”, not proof that a listener still exists.

Before drawing conclusions, verify current state:

```bash
# Hermes process list if available
# OS listener check
ss -ltnp '( sport = :16380 )' || true

# sanitize secrets if listing cloudflared processes
pgrep -a cloudflared | sed -E 's/(--secret )[^ ]+/\1[REDACTED]/g; s/(--id )[^ ]+/\1[REDACTED]/g' || true
```

A common local pattern is a second `cloudflared` attempt matching the watch string, then exiting because the port is already occupied by an older listener. In that case, test or kill the older listener explicitly rather than treating the new process as the active tunnel.

## Safe container diagnostic to add if needed

Add a temporary/auth-protected diagnostic that returns only booleans and operation status, not env values:

- `hasRedisProxyHost: Boolean(process.env.REDIS_PROXY_HOST)`
- selected Redis mode: `standalone-proxy` vs `cluster`
- local tunnel connection result: `PING` ok/error class
- one `HGETALL` against a known monitor key, returning field names/counts or redacted counters only

Avoid tailing or logging full `envVars`; Cloudflare Access secrets and app secrets may be present.

## Log-source split pitfall

`wrangler tail <worker-name> --format json` is useful for Worker / Durable Object events and can show container lifecycle exceptions such as `Durable Object reset because its code was updated` or `Container error: Network connection lost`, but it may **not** include stdout/stderr emitted by the Node process inside the Container. Do not assume an empty `logs: []` on a successful request means the container code did not log.

For persisted Worker/Container observability logs, the Cloudflare Workers Observability Telemetry API may require extra token scope; a token that can read `containers/applications/<id>` can still get `403 Authentication error` from `/workers/observability/telemetry/*`. If that happens:

1. Record the 403 as a permission boundary, not as absence of logs.
2. Still verify the deployment via Containers API:
   - `GET /accounts/$ACCOUNT_ID/containers/applications/$APP_ID`
   - `GET /accounts/$ACCOUNT_ID/containers/applications/$APP_ID/rollouts`
3. Use `wrangler tail` for request outcome/wallTime and DO/container lifecycle exceptions.
4. Trigger the exact API path with an authenticated route if possible. For Notifly web-console internal-only probes, if using the existing `Authorization: Basic notifly-internal-request` path, remember `_authMiddleware` trusts `x-forwarded-for` before socket address; set it deliberately only for controlled diagnostics and never expose this as a public recipe.
5. Interpret a `status: unavailable` response plus Redis command timeout-shaped wall time as evidence that the app reached the Redis read path but failed at the container-local Redis client/tunnel boundary.

## Confirmed 2026-06 Notifly web-console failure shape

A useful all-in-one diagnostic split for campaign delivery monitor is:

- Worker bindings: `REDIS_HOST=127.0.0.1`, `REDIS_PROXY_HOST=127.0.0.1`, CF Access client values present.
- Container Node env: same values present; `CLOUDFLARE_APPLICATION_ID` present inside the container even if not present in Worker bindings.
- TCP probe to `127.0.0.1:6379`: ok.
- Fresh standalone `ioredis` client to `127.0.0.1:6379`: `PING=PONG`, `HGETALL` returns monitor fields.
- `RedisManager` singleton: `mode=standalone`, but status stuck in `connecting`/`connect`/`reconnecting`; `initialize()` returns false.
- `readCampaignDeliveryMonitor`: `kind: unavailable`.

This proves the tunnel and env are healthy; the failing layer is the long-lived RedisManager client lifecycle, not Cloudflare binding or the Redis proxy endpoint.

Fix shape that verified in preview:

1. For proxy-mode monitor reads, use a fresh short-lived standalone Redis client in `delivery-policy` (`REDIS_PROXY_HOST`, lazy connect, bounded timeout) for the read path, rather than the stale singleton.
2. Keep RedisManager diagnostics/recovery improvements (`lazyConnect`, readiness assertion, reconnect-on-stale client) for broader resilience, but verify the actual container endpoint because package/runtime bundling can make package-level fixes appear later than app-level changes.
3. Verify after deploy with the diagnostic route:
   - direct standalone ok,
   - manager ready or at least not blocking the read path,
   - `monitorRead.kind=snapshot`,
   - user-facing delivery endpoint no longer returns `status: unavailable`.

If final `campaign_statistics` already covers the published target, the user-facing delivery endpoint may correctly return `source: stats, status: completed`; use the diagnostic `monitorRead.kind=snapshot` as the Redis connectivity proof.
