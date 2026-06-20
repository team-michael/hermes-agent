# web-console MODULE_NOT_FOUND: workspace package transitive external dep missing at runtime

## Pattern

`Error: Cannot find module '<package>'` in web-console ECS logs where `<package>` is **not** a direct dependency of `services/server/web-console/package.json` but is a **dependency of a workspace `link:` package** that web-console depends on.

Observed instance: `Error: Cannot find module 'google-spreadsheet'`
- Trigger: `iplusn-cost-savings` API route calling `PriceTagRepository` from `@notifly/pricing`
- `packages/pricing/package.json` → `"google-spreadsheet": "^4.1.1"` (proper `dependencies`)
- `services/server/web-console/package.json` → no direct `google-spreadsheet` entry
- First error: 2026-06-19 17:44 KST (11 days after the route was added in PR #3741, because the route was never called until then)

## Root Cause Mechanism

```
Next.js webpack (builder stage)
  → bundles @notifly/pricing source inline into .next/server/pages/api/.../route.js
    (workspace link: packages are bundled by default in Next.js 14 Pages Router)
  → google-spreadsheet left as external require() in the bundled chunk

Runtime (runner stage)
  → .next chunk does require('google-spreadsheet')
  → Node.js traverses up to /app/node_modules
  → google-spreadsheet NOT present ← MODULE_NOT_FOUND

Why missing from node_modules:
  → turbo prune --scope=web-console --docker generates pruned pnpm-lock.yaml
  → turbo MAY omit transitive external deps of workspace link: packages
    (known turbo prune limitation with pnpm workspaces)
  → pnpm install --frozen-lockfile in builder stage skips google-spreadsheet
  → runner COPY /app/node_modules → google-spreadsheet absent
```

## Diagnosis Checklist

1. `services/server/web-console/package.json` — is the missing package listed directly? If NO, continue.
2. Which workspace `@notifly/*` package imports it:
   ```bash
   grep -r "missing-pkg" packages/*/package.json
   grep -r "require.*missing-pkg" packages/*/dist/index.js
   ```
3. Is the workspace package in `next.config.js` `serverExternalPackages`? If NO → it gets bundled by webpack; its external deps must be in web-console's own node_modules.
4. Route existed for days/weeks without error → confirms nobody called it until today; no CI signal.
5. Check other routes using same repository class (e.g. `products/[productId]/payment/register/contract.ts` also uses `PriceTagRepository`) — same risk even if not yet triggered.

## Fix

**Short-term (immediate deploy):** Add missing package directly to `services/server/web-console/package.json`:
```bash
cd services/server/web-console
pnpm add google-spreadsheet@^4.1.1
# commits pnpm-lock.yaml → redeploy
```
Guarantees turbo prune includes the package in the web-console scope.

**Mid-term (structural):** Add `@notifly/pricing` to `serverExternalPackages` in `next.config.js`:
```js
// next.config.js
experimental: {
  serverComponentsExternalPackages: ['@notifly/pricing', 'google-spreadsheet'],
}
```
Prevents Next.js inlining workspace packages → runtime dep graph becomes explicit → no dep duplication needed.

## Scope Attribution

`project_id` is typically absent from trigger context — route throws before any project-scoped logic runs.
Final Korean scope: `프로젝트 특정 불가, web-console 서비스 전체`.

## Classification

- Alarm: `web-console console error`
- Status: `needs_fix`
- Pattern class: turbo prune + pnpm workspace transitive dep gap + Next.js Pages Router API route bundling

## Related Code Paths

- `packages/pricing/src/repository/PriceTagRepository.ts` — imports `google-spreadsheet`
- `services/server/web-console/src/pages/api/projects/[projectId]/campaigns/[campaignId]/iplusn-cost-savings.ts` — triggering route (PR #3741, 2026-06-08)
- `services/server/web-console/src/pages/api/products/[productId]/payment/register/contract.ts` — also uses `PriceTagRepository`; same latent risk
