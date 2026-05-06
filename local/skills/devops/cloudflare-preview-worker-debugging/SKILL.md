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

## 9. High-confidence diagnosis rules

Use these rules:

### Case 1: Deploy step success + container healthy + direct health 200 + plain curl DNS failure
**Diagnosis:** custom-domain DNS propagation/resolution issue.

### Case 2: Deploy step success + plain curl gets 302 to Access + auth curl gets 200
**Diagnosis:** workflow health check is missing/incorrect Access auth, or route is protected differently than expected.

### Case 3: Deploy step success + auth curl reaches worker but gets 5xx / wrong SHA
**Diagnosis:** app/container readiness or routing issue.

### Case 4: Deploy step fails before health check
**Diagnosis:** inspect credentials, wrangler config, or Cloudflare API errors first.

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

## Minimal reusable summary

When Cloudflare preview deploy fails after `wrangler deploy` success, first test whether the hostname resolves from the runner. If not, the likely culprit is DNS/custom-domain propagation, not credentials and not the container runtime.
