# Notifly preview Redis diagnostics cleanup

Use after a Cloudflare preview/container Redis incident has been diagnosed with temporary endpoints or broad logging. The goal is to leave the PR with only product/runtime behavior, not investigation scaffolding.

## What to remove

- Worker-only diagnostic routes such as `/__diagnostics/worker`.
- Next/API diagnostic routes such as `/api/diagnostics/redis-delivery-monitor`.
- Diagnostic auth/token headers used only by those routes.
- Safe-env-summary helpers and binding dumps, even if redacted.
- Entry-point logs that print env presence, tunnel PIDs, tunnel health probes, or per-attempt readiness details.
- Redis client configuration/status diagnostic exports such as `RedisManagerDiagnostics` / `getDiagnostics()` when not part of the production contract.
- Temporary fallback logs whose only purpose was to prove the failing branch, e.g. “monitor unavailable; using stats fallback”.

## What can remain as functional code

- A minimal tunnel readiness wait in `entrypoint.sh` if the app genuinely must not start before local `cloudflared access tcp` listeners exist.
- The broadened Cloudflare-container detection condition when it is the runtime fix, e.g. `CLOUDFLARE_APPLICATION_ID || CF_ACCESS_CLIENT_ID`.
- Redis proxy/client behavior needed by the app, such as direct/fresh standalone `ioredis` reads through `REDIS_PROXY_HOST`, bounded timeouts, readiness checks, and stale-client retry.
- Existing operational warnings already part of write/update failure handling.

## Verification checklist

1. Search for diagnostic leftovers in changed files:
   - `diagnostic`, `diagnostics`, `__diagnostics`
   - `getDiagnostics`, `RedisManagerDiagnostics`
   - debug strings such as `client configuration`, `env presence`, `retrying command`, `retrying readiness`
2. Confirm the diagnostic files are removed from the PR diff, not merely returning 404 by auth.
3. Run the normal changed-file gates: shell syntax for `entrypoint.sh`, Prettier, focused Jest, package builds, web-console typecheck/eslint.
4. Push and wait for the Cloudflare preview deploy to complete.
5. Smoke with Access service-token headers:
   - `/health` returns expected JSON/SHA.
   - removed Worker diagnostic route returns `404`.
   - removed Next/API diagnostic route returns `404`.
6. Report CI as pass/pending/fail buckets. Long-running unrelated web-console install/test jobs can remain pending, but do not call them green.

## Pitfalls

- Do not keep redacted env summaries “because they are safe”; they are still debug surface area.
- Do not remove the functional Redis/tunnel fix while deleting the diagnostics. Separate “proved the hypothesis” code from “implements the product behavior” code.
- Do not trust unauthenticated preview curls when Cloudflare Access is enabled; `302` to Access only proves the gate, not the app route. Use service-token headers for health/404 checks.
