# Notifly chained Cloudflare preview + MCP smoke pattern

Use this when a PR deploys multiple Notifly services to Cloudflare preview endpoints and the web-console must point at the preview internal-api, which points at the preview api-service.

## Deployment chain

For PR preview branches, verify the chain in this order:

1. `api-service`
2. `internal-api-service` configured to use the deployed preview api-service endpoint
3. `web-console` configured to use the deployed preview internal-api endpoint

Do not mark the chain done from GitHub job success alone. Also hit each deployed `/health` endpoint and check the service name/SHA shape is expected.

Example endpoints from the `infra/cf-deploy` style branch naming:

- `https://<branch>-api.notifly.tech/health`
- `https://<branch>-internal-api.notifly.tech/health`
- `https://<branch>-console.notifly.tech/health`

## Env parity before force-push/deploy

Before triggering the preview deploy after a rebase, compare each service's Cloudflare workflow env against its ECS task-definition env. For web-console, pay special attention to values that affect the preview chain and AI features:

- `INTERNAL_API_SERVICE_URL`
- `AI_PROVIDER`
- `AI_MODEL`
- `GEMINI_API_KEY`
- Slack ops bot/report channel envs, if AI agent tooling/reporting uses them
- Sentry DSNs and public DSNs
- Cloudflare account/token envs for CF-bound code paths

If a value is required but not available in the current environment, ask the user for the value instead of inventing it.

## MCP smoke against preview api-service

After api-service preview is deployed, verify MCP at the preview API endpoint rather than only production/stage.

Minimum useful smoke:

1. unauthenticated `/mcp` returns 401
2. `WWW-Authenticate` includes `resource_metadata="<preview-api>/.well-known/oauth-protected-resource/mcp"`
3. protected resource metadata loads
4. authorization server metadata loads
5. authenticated JSON-RPC `initialize` succeeds
6. authenticated JSON-RPC `tools/list` succeeds

This catches route wiring, OAuth metadata, scope/auth plumbing, and MCP handler availability without depending on a full browser session.

## Web-console AI agent smoke prep

The web-console AI Agent path is cookie-authenticated, so API smoke is not a replacement for browser smoke. Before driving the browser, map the code path:

- standalone page: `/console/products/[productId]/ai-agent`
- product slug such as `michael` is resolved server-side to the actual project id
- browser API proxy: `/api/internal/...`
- upstream env: `INTERNAL_API_SERVICE_URL`
- chat route: `/api/ai-agent/chat` → internal-api `/ai-agent/projects/{projectId}/sessions/{sessionId}/chat`

For final signoff, actually log in and send a small AI Agent message in the Michael product. The earlier health/MCP checks only prove the service chain and MCP surface, not the authenticated UI stream.

## Web-console → internal-api Cloudflare Access header pitfall

When web-console calls a Cloudflare Access-protected preview internal-api, do not model the upstream credential as only an `Authorization` value.

Durable pattern:

- `INTERNAL_API_UPSTREAM_AUTHORIZATION` may be a JSON object containing multiple upstream headers, e.g. Cloudflare Access service-token headers.
- The web-console proxy must parse object-shaped auth config into actual request headers.
- Only string-shaped auth config should become `Authorization: <value>`.
- In browser automation, apply Cloudflare Access service-token headers only to the preview console host. If those headers are applied globally, same-origin console requests can work while upstream/third-party navigation or auth flows become misleading.

Useful local verification after changing this path:

- targeted unit spec for `upstream-auth.ts`
- targeted ESLint on the changed proxy/auth files
- real browser login to `/console/products/<slug>/ai-agent`
- direct internal-api GET and POST probes to distinguish proxy/auth failure from service runtime failure

## AI Agent session-creation failure triage

If the browser reaches the AI Agent page and session list GET succeeds, but new session creation fails with 500:

1. Compare browser proxy POST (`/api/internal/ai-agent/projects/{projectId}/sessions`) with direct internal-api POST (`/ai-agent/projects/{projectId}/sessions`).
2. If both fail but direct GET succeeds, stop debugging web-console login/cookies first; the likely fault is inside internal-api create-session runtime.
3. Inspect the internal-api path around:
   - auth middleware
   - `AiAgentSessionService.createSession`
   - `RateLimitRepository.incrementUsage`
   - DB session repository
   - global error handler
4. Check whether `dailySessionsRemaining` is unexpectedly `0` while GET still returns 200. In Notifly this can indicate Redis/rate-limit fallback behavior rather than a DB table problem.
5. For Cloudflare Container deployments using local `cloudflared access tcp` tunnels, verify that Redis client mode matches the tunnel. A `REDIS_HOST=127.0.0.1` tunnel plus a Redis Cluster client can fail differently from ECS/prod DNS-based Redis access.

Interpretation shortcut:

- GET sessions 200 + POST create-session 500 + remaining limit 0 → high suspicion on Redis/rate-limit path before DB/session insert.
- GET sessions 500 too → broader auth/DB/connectivity issue.
- Proxy POST 500 but direct internal-api POST 200 → web-console proxy/upstream auth issue.
