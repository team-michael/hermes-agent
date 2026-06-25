---
name: cloudflare-preview-worker-debugging
description: Debug Cloudflare preview Worker/Containers deploy failures by separating credential, deploy, DNS/custom-domain, Access, and container-runtime causes using wrangler plus Cloudflare/GitHub APIs.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [Cloudflare, Workers, Containers, GitHub-Actions, DNS, Debugging]
---

# Cloudflare Preview Worker Debugging

Use when a GitHub Actions preview deploy for a Cloudflare Worker/Container fails, especially if the workflow ends in a vague health-check timeout.

## Why this skill exists

A common failure mode is **not** bad Cloudflare credentials and **not** a broken container. The deploy can succeed while the workflow still fails because:
- the custom preview domain has not propagated yet,
- the GitHub runner cannot resolve the hostname,
- Cloudflare Access returns a redirect/login flow,
- the workflow uses `curl -s ... || true` and hides the real error.

This skill is for separating those layers cleanly.

## Prerequisites

- Cloudflare credentials available via env:
  - `CLOUDFLARE_API_TOKEN`
  - `CLOUDFLARE_ACCOUNT_ID`
- GitHub token for Actions log inspection
- `wrangler` available, or run via `corepack pnpm dlx wrangler`

## Core workflow

### 1. Confirm the failure stage from GitHub Actions first

Do **not** guess from the workflow name.

Inspect the failed job and identify whether failure happened in:
- credential/setup,
- `wrangler deploy`,
- post-deploy health check.

For GitHub REST:
- `GET /repos/{owner}/{repo}/actions/jobs/{job_id}`
- `GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs`

What to look for:
- If `Deploy to Cloudflare` succeeded and `Health check` failed, credentials are probably fine.
- If the logs show repeated empty responses like:
  - `Not ready yet (response: ). Retrying in 60s...`
  then suspect DNS resolution or stderr being swallowed.

## 2. Verify Cloudflare credentials are actually present

Check local env without printing secrets. Only confirm presence/length/masked value.

Then confirm CI also received them by looking for masked env lines in the job logs:
- `CLOUDFLARE_API_TOKEN: ***`
- `CLOUDFLARE_ACCOUNT_ID: ***`

If `wrangler deploy` succeeded, this is further evidence credentials are not the root cause.

## 3. Inspect the Worker service and container application separately

Useful commands:

```bash
corepack pnpm dlx wrangler whoami
corepack pnpm dlx wrangler deployments list --name <worker-name> --json
corepack pnpm dlx wrangler versions list --name <worker-name>
corepack pnpm dlx wrangler versions view <version-id> --name <worker-name> --json
corepack pnpm dlx wrangler containers list
corepack pnpm dlx wrangler containers info <container-app-id>
corepack pnpm dlx wrangler containers instances <container-app-id>
```

Interpretation:
- Worker deployment exists + latest version matches expected SHA -> worker deploy worked.
- Container app `state=ready`, healthy instances > 0, failed instances = 0 -> container is not the primary failure.
- `containers instances` may still say no running instances if nothing is currently active; do not over-interpret that alone.

### Verify Cloudflare Containers are actually on the new image

When the question is “did the preview really deploy the newly built image?”, collect all four pieces of evidence and reconcile the SHAs:

1. **GitHub Actions build log / ECR**
   - Build job should push both branch tag and revision tag, e.g. `web-console-stage-<sanitized-branch>` and `web-console-stage-<revision>`.
   - Confirm ECR tag exists and note digest/pushed time:
     ```bash
     aws ecr describe-images \
       --repository-name <repo> \
       --image-ids imageTag=<tag> \
       --query 'imageDetails[0].{Tags:imageTags,Digest:imageDigest,PushedAt:imagePushedAt,Size:imageSizeInBytes}' \
       --output json
     ```
2. **Cloudflare Worker deployment/version**
   - `GET /accounts/$ACCOUNT_ID/workers/scripts/<script>/deployments`
   - latest deployment should route `100%` to the expected version id.
   - `GET /accounts/$ACCOUNT_ID/workers/scripts/<script>/versions/<version-id>` should show expected bindings like `DEPLOY_SHA`, but redact all secrets: Worker version APIs can return secret-like plain-text bindings.
3. **Cloudflare Container app + rollout**
   - `GET /accounts/$ACCOUNT_ID/containers/applications/<app-id>` should show `configuration.image` with the new tag.
   - `GET /accounts/$ACCOUNT_ID/containers/applications/<app-id>/rollouts` should show latest rollout `completed`, target image/version, target instances at 100%, and no health errors.
   - Container rollout is asynchronous after `wrangler deploy`; a GitHub job can succeed before the rollout has fully converged. Re-check rollouts after a short delay before diagnosing stale image.
4. **Runtime health**
   - Authenticated `/health` should return the expected `sha`.

Important SHA nuance for GitHub PR previews: the image/deploy revision may be the GitHub `pull_request` merge ref SHA, not the raw PR head SHA. If `/health` reports the merge SHA while the PR head is different, verify it via the Actions deploy input/log before calling it stale.

## 4. Check custom-domain binding via Cloudflare API

The worker may be deployed even if the custom domain is not yet usable from the runner.

Helpful API endpoints:

- `GET /accounts/{account_id}/workers/services/{service}`
- `GET /accounts/{account_id}/workers/scripts/{script}/domains`
- `GET /accounts/{account_id}/workers/domains/records/{domain_record_id}`
- `GET /zones/{zone_id}/dns_records?name=<hostname>`

Important pattern:
- Cloudflare may show a worker domain binding exists and a DNS record such as `AAAA 100::` with `proxied=true`.
- That **does not guarantee** the GitHub runner can resolve the hostname immediately.

## 5. Distinguish DNS failure vs Access failure vs app failure

### A. Plain hostname curl

```bash
curl -sS https://preview-host.example.com/health
```

Possible outcomes:
- `curl: (6) Could not resolve host` -> DNS / propagation issue
- `302` to Cloudflare Access login -> Access gate is working, but request lacks auth
- `200` with expected JSON -> route is healthy
- `5xx` / timeout -> app or network issue

### B. If DNS is flaky, force resolution to a known Cloudflare anycast IP

This is a powerful diagnostic.

```bash
curl --resolve preview-host.example.com:443:104.18.8.21 \
  https://preview-host.example.com/health
```

If this works while plain hostname fails, the root cause is **custom-domain DNS propagation/resolution**, not the worker/container.

### C. If Access is enabled, send service-token headers

You can extract `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET` from Worker settings/version bindings and test directly:

```bash
curl --resolve preview-host.example.com:443:104.18.8.21 \
  -H "CF-Access-Client-Id: ..." \
  -H "CF-Access-Client-Secret: ..." \
  https://preview-host.example.com/health
```

Interpretation:
- `302` without headers, `200` with headers -> Access was expected and functioning.
- `200` with headers + expected SHA -> worker/container is healthy.

## 6. Tail live Worker logs to confirm runtime behavior

Run:

```bash
corepack pnpm dlx wrangler tail <worker-name> --format json
```

Then generate a request.

What to look for:
- top-level request to `/health` returning `200`
- durable object/container logs such as:
  - `Error checking 80: The container is not listening in the TCP address 10.0.0.1:80`

This specific message can appear during early container startup and may be transient. If the final response is `200`, it is **not** the root cause of the workflow failure.

## 7. Compare runtime env parity across ECS, Worker bindings, and container passthrough

For Notifly-style Cloudflare Container deployments, do **not** stop at "the worker has env bindings". There are three separate layers that can drift:

1. app/runtime contract (`src/utils/env.ts`, direct `process.env.*` reads)
2. Cloudflare deploy workflow (`cf_deploy.yml` generated `vars`)
3. Worker-to-container passthrough (`worker/index.ts` `envVars`, plus `worker/env.d.ts`)
4. optional baseline comparison: ECS task definitions

A real failure mode is:
- value exists in ECS task defs,
- value exists in `cf_deploy.yml`,
- but it is **not forwarded** in `worker/index.ts envVars`,
- so the container process never receives it.

### What to diff

Check these files together:
- `services/server/web-console/src/utils/env.ts`
- direct `process.env.*` usages under the service
- `.github/workflows/cf_deploy.yml`
- `services/server/web-console/worker/index.ts`
- `services/server/web-console/worker/env.d.ts`
- `services/server/web-console/task-definitions-*.json`

### Important interpretation

- Missing in `cf_deploy.yml` -> Worker never receives it.
- Present in `cf_deploy.yml` but missing in `worker/index.ts envVars` -> Worker has it, container does not.
- Present in ECS task defs but absent in Cloudflare path -> Cloudflare preview is not parity-tested against production runtime.

### Concrete Notifly findings worth remembering

In `web-console`, Cloudflare preview env drift included these categories:

- **Missing from Cloudflare deploy vs ECS/runtime**:
  - `APPLICATION_NAME`
  - `INTERNAL_API_SERVICE_URL`
  - `SLACK_NOTIFLY_OPS_BOT_TOKEN`
  - `SLACK_NOTIFLY_OPS_JOB_REPORT_CHANNEL_ID`

- **Present in `cf_deploy.yml` but missing from worker-to-container passthrough**:
  - `KAKAO_BZM_CENTER_API_URL`
  - `KAKAO_BZM_CENTER_UPLOAD_API_URL`
  - `KAKAO_BZM_CENTER_PARTNER_KEY`

This kind of drift is a real bug, even when it is not the direct cause of the immediate health-check failure.

### Caveat about `APPLICATION_NAME`

If the app only uses it for DB `application_name` tagging via `resolvePgApplicationName`, its absence may degrade observability without crashing startup. Distinguish:
- missing env causing startup failure
- missing env causing silent runtime parity/observability regression

## 8. Interpret container startup logs carefully

A transient log such as:

```text
Error checking 80: The container is not listening in the TCP address 10.0.0.1:80
```

can happen during cold start before the app begins listening.

If the same request later returns `200`, treat this as **transient readiness delay**, not proof of a crash loop.

For the Notifly `web-console` container, startup is not instantaneous because `entrypoint.sh` first launches multiple `cloudflared access tcp` processes, waits briefly, and only then starts `node server.js`.

## 9. Notifly web-console Cloudflare domain derivation

When answering “after web-console build + cloudflare-deploy, which CF domain is deployed?”, derive it from workflow code before guessing from environment names.

In `team-michael/notifly-event`:
- `.github/workflows/ecs_build.yml` sets `branch_name` from `github.head_ref || github.ref_name`, sanitized with `sed 's/[^a-zA-Z0-9-]/-/g' | tr '[:upper:]' '[:lower:]'`.
- `cloudflare-deploy` then calls `.github/workflows/cf_deploy.yml` with that `branch_name` and `revision: github.sha`.
- `cf_deploy.yml` sets:
  - deployment URL: `https://<sanitized-branch>-console.notifly.tech/auth/login`
  - health URL: `https://<sanitized-branch>-console.notifly.tech/health`
  - worker name: `notifly-web-console-<sanitized-branch>`
  - route/custom domain: `<sanitized-branch>-console.notifly.tech`

Important pitfall: for this workflow, `environment` (`stage`/`prod`) affects build/runtime env and image tag prefix, but **does not appear in the Cloudflare custom domain**. For example, branch `feat/ai-agent-ui-migration` deploys to `https://feat-ai-agent-ui-migration-console.notifly.tech/auth/login`; branch `main` deploys to `https://main-console.notifly.tech/auth/login`.

If the user asks about a currently running deployment, optionally query the GitHub run/job to confirm the actual `head_branch` and whether the `cloudflare-deploy` job has started; but the domain formula is still branch-derived.

## 10. Chained Notifly Cloudflare previews

Some Notifly previews deploy multiple services that must point at each other, not just one Worker/Container. For these, validate the chain explicitly:

1. `api-service` preview is deployed and healthy.
2. `internal-api-service` preview is deployed with its upstream pointing at the preview api-service endpoint.
3. `web-console` preview is deployed with `INTERNAL_API_SERVICE_URL` pointing at the preview internal-api endpoint.
4. Each service `/health` returns the expected service identity/SHA.
5. If the API exposes MCP, smoke the preview `/mcp` endpoint directly: unauthenticated 401 + `WWW-Authenticate` protected-resource metadata, metadata discovery, authenticated `initialize`, and authenticated `tools/list`.
6. For web-console AI Agent signoff, do not stop at API/MCP smoke: log into the preview console, open the target product, and send a small AI Agent message to verify cookie auth + product→project resolution + streaming UI.
7. If web-console calls an Access-protected preview internal-api, verify upstream auth values that are JSON objects are forwarded as multiple headers, not collapsed into one `Authorization` header.
8. If AI Agent session list GET succeeds but create-session POST returns 500, split proxy/auth from service runtime by comparing web-console proxy POST with direct internal-api POST; if both fail, inspect internal-api create-session rate-limit/Redis before continuing UI debugging.
9. If the failing internal-api path touches Redis and the app runs behind `cloudflared access tcp`, explicitly test Redis Cluster redirect behavior. A single local TCP tunnel to a cluster config endpoint can surface `MOVED`/`ASK` or unstable shard hits; this can look like quota exhaustion or generic POST 500 even when the Redis key is absent.
10. If app code should remain unchanged, consider a container-wrapper RESP proxy that listens where the app expects Redis and follows one-hop cluster redirects behind Cloudflare Access tunnels.

See `references/notifly-chained-preview-and-mcp-smoke.md` for the compact Notifly-specific checklist, upstream Access header pitfall, and AI Agent session-creation triage pattern.
See `references/redis-cluster-through-cloudflared.md` for the Redis Cluster + Cloudflare Access TCP tunnel failure mode and wrapper/proxy remediation pattern.
See `references/cloudflare-container-redis-cluster-options.md` for the production-shaped options matrix: AWS-side Envoy Redis proxy, node-specific tunnels with NAT mapping, preview-only single Redis, and why Workers VPC is not a simple drop-in for Container `ioredis` Cluster mode.
See `references/notifly-envoy-redis-proxy-stack.md` for the Notifly Terraform/PR pattern for an AWS-side Envoy Redis proxy, including stacked remote-state sequencing, Cloudflare tunnel adoption, naming constraints, and Envoy bootstrap pitfalls.
See `references/aws-envoy-redis-proxy-cloudflare-tunnel.md` for the implementation pattern when adding an AWS-side Envoy Redis proxy in ECS/Fargate plus Cloudflare Tunnel DNS/ingress, including stacked Terraform PR sequencing and Envoy config pitfalls.
See `references/envoy-redis-proxy-cloudflare-tunnel.md` when planning the AWS-side Envoy Redis proxy itself: internal NLB + ECS/Fargate proxy + separate Cloudflare Access hostname + no app cutover in the initial infra PR.
See `references/notifly-preview-redis-proxy-runtime-triage.md` when a web-console Cloudflare preview has Redis-backed UI/API reads returning `unavailable` even though local Cloudflare Access TCP proxy smoke tests pass; it covers the Worker binding → container passthrough → entrypoint tunnel → Node runtime split and delayed `cloudflared` watch-notification pitfall.
See `references/notifly-cf-container-redis-manager-stale-client.md` when fresh standalone `ioredis` succeeds through the CF Redis proxy but the app's shared RedisManager/singleton path fails or gets stuck in `connecting`/`reconnecting`; it also captures the cleanup rule for removing temporary diagnostic endpoints/logging after proof.
See `references/notifly-preview-redis-singleton-vs-fresh-client.md` when Worker bindings and the Redis tunnel are healthy but the app still returns Redis `unavailable`; it captures the stale RedisManager singleton vs fresh standalone `ioredis` split, bounded tunnel readiness fix, and cleanup requirement for temporary diagnostic endpoints/logs.
See `references/notifly-preview-redis-diagnostics-cleanup.md` after such an investigation: remove temporary Worker/Next diagnostic endpoints, redacted env summaries, tunnel PID/health logs, and Redis diagnostics exports while preserving the functional Redis/tunnel readiness fix; verify removed routes return 404 with Access service-token headers.

## 10. High-confidence diagnosis rules

Use these rules:

### Case 1: Deploy step success + container healthy + direct health 200 + plain curl DNS failure
**Diagnosis:** custom-domain DNS propagation/resolution issue.

### Case 2: Deploy step success + plain curl gets 302 to Access + auth curl gets 200
**Diagnosis:** workflow health check is missing/incorrect Access auth, or route is protected differently than expected.

### Case 3: Deploy step success + auth curl reaches worker but gets 5xx / wrong SHA
**Diagnosis:** app/container readiness or routing issue.

### Case 4: Deploy step fails before health check
**Diagnosis:** inspect credentials, wrangler config, or Cloudflare API errors first.

If the failure is immediately after `wrangler deploy` reports `Uploaded ...` and the API error is `The requested Worker version could not be found ... [code: 100146]`, treat it as a Cloudflare Worker version propagation race rather than an app/container failure. Confirm by querying the Worker deployments API: the failed version id can already appear as a 100% automatic deployment a few seconds later. The durable workflow fix is a bounded retry around `wrangler deploy` only for `Worker version could not be found|code: 100146`, then let the existing `/health` SHA check prove the deployed revision.

## Pitfalls

- `curl -s ... || true` hides the real error. An empty response in logs may actually be DNS failure.
- Do not conclude “container failed” from a health-check timeout alone.
- Do not conclude “credentials failed” if `wrangler deploy` completed successfully.
- Cloudflare API domain records and GitHub runner DNS visibility are related but not identical.
- `workers.dev` hostname behavior may differ from custom domain behavior; use it as an extra signal, not the only truth.

## Recommended remediation after diagnosis

If root cause is DNS/custom-domain propagation:
1. Change workflow logging to surface `curl` stderr (`-Ssv` or equivalent).
2. Split readiness checks:
   - first check worker/container readiness,
   - then check custom domain separately.
3. Consider fallback health validation using direct worker route / forced resolve for debugging.
4. Avoid treating a custom-domain propagation delay as a hard deploy failure unless that is explicitly desired.
5. If Cloudflare support confirms a platform-side DNS bug, **re-run the same preview deploy after the vendor fix before changing app/workflow code again**.

### Vendor-side DNS bug pattern worth remembering

A real Cloudflare failure mode is:
- Worker Custom Domain object exists
- proxied DNS record exists in Cloudflare control plane
- public authoritative DNS still returns `NXDOMAIN`

In one confirmed case, Cloudflare support traced this to **an internal service that propagates DNS changes to authoritative nameservers incorrectly skipping an update for the zone**. After Cloudflare deployed their fix:
- `dig <preview-host>` returned normal A records
- the exact same preview deploy, re-run without config changes, succeeded end-to-end

So when all of these are simultaneously true:
- `wrangler deploy` succeeds
- Cloudflare API shows the custom domain and DNS record exist
- public DNS returns `NXDOMAIN`
- worker/container health looks otherwise normal

then keep platform/vendor DNS propagation bug high on the hypothesis list. The correct next step may be **support escalation + later deploy retry**, not more application changes.

## Stronger workflow pattern: workers.dev-first, custom-domain-second

For Cloudflare preview deployments that expose both a `workers.dev` hostname and a branded custom domain, a better production workflow is:

1. `wrangler deploy`
2. enable the Worker `workers.dev` subdomain explicitly via Cloudflare API
3. block on authenticated `workers.dev/health` until the expected SHA is serving
4. after readiness, verify unauthenticated `workers.dev/health` is still challenged by Access
5. verify the custom-domain DNS record exists in Cloudflare control plane
6. check the custom domain separately
   - if it **resolves publicly** but never serves the expected SHA -> fail the deploy
   - if it **never resolves at all** during a short bounded window -> treat specifically as DNS propagation delay
7. if the deploy fails after enabling `workers.dev`, disable that subdomain again as cleanup

### Important nuance

Do **not** let the workflow go green just because `workers.dev` is healthy while the real preview domain is publicly resolvable but broken.

The only safe tolerance case is:
- custom-domain DNS record exists in Cloudflare control plane,
- but public DNS still does not resolve the hostname during the short verification window.

That distinguishes:
- **likely propagation delay** -> tolerable if the team accepts it
from
- **route/domain/access misconfiguration after public resolution** -> should fail

### Access verification pitfall

A weak check like "response did not include `.sha`" is not enough. The unauthenticated `workers.dev` probe should explicitly expect an Access-style challenge, e.g. one of:
- HTTP `302`
- HTTP `401`
- HTTP `403`
- body markers such as `Cloudflare Access`

Otherwise a public HTML page, redirect loop, or other non-health response can falsely look "protected".

### Cleanup pitfall

If you enable `workers.dev` only for CI diagnostics, add a failure cleanup step that disables it again. Otherwise a failed deployment may leave an unnecessary public alternate hostname behind.

## Finding prior Cloudflare issue context

When the user asks for a previous “Cloudflare issue/ticket/session”, first disambiguate by failure class instead of broad-searching only for `Cloudflare issue` (that query is noisy because many skills mention Cloudflare):

1. **Vendor DNS/custom-domain propagation bug** — search this skill for `authoritative DNS`, `NXDOMAIN`, `custom domain object exists`, or `internal service that propagates DNS changes`. This is the prior support-escalation pattern where Cloudflare control plane had the Worker Custom Domain/DNS record but authoritative DNS still returned NXDOMAIN.
2. **Workers AI / Hermes profile model switch** — use `hermes-gateway-profile-operations` references for `@cf/zai-org/glm-5.2`, `@cf/moonshotai/kimi-*`, and `reasoning_effort: "none"`.
3. **Cloudflare Container + Redis Cluster** — use this skill’s Redis/Envoy references (`redis-cluster-through-cloudflared`, `cloudflare-container-redis-cluster-options`, `notifly-envoy-redis-proxy-stack`) and session-search terms like `ElastiCache Cluster`, `Envoy Redis proxy`, `Workers VPC`.
4. **AI Agent stream cut / Cloudflare-ALB edge** — use `notifly-web-console-frontend-bugfix` references such as `ai-agent-stream-edge-timeout-lock` and `ai-agent-stream-abort-autostop-owner-lock`.

If session search is needed, use exact mechanism phrases (`"Worker Custom Domain" "NXDOMAIN"`, `"authoritative DNS"`, `"Cloudflare support" "DNS"`, `"ElastiCache Cluster" "Cloudflare"`) rather than generic `Cloudflare issue`.

## Minimal reusable summary

When Cloudflare preview deploy fails after `wrangler deploy` success, first test whether the hostname resolves from the runner. If not, the likely culprit is DNS/custom-domain propagation, not credentials and not the container runtime.
