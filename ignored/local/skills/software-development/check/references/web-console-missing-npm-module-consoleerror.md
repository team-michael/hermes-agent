# web-console Missing npm Module at Runtime (MODULE_NOT_FOUND)

## Pattern

`Error: Cannot find module '<package-name>'` with `code: 'MODULE_NOT_FOUND'` in
`/aws/ecs/notifly-services-prod/web-console` logs. The `.next/server/pages/api/...`
require stack confirms the error originates from a compiled API route referencing a package
absent from the production Docker image.

## Root Cause

A Next.js API route imports a package that is:
- Missing from `services/server/web-console/package.json` `dependencies`, **or**
- Present in `devDependencies` only (excluded from the production pnpm install layer), **or**
- Removed from `package.json` but the source file still references it.

Build succeeds (Next.js bundles available monorepo packages), but the `require()` at runtime
fails because the package is absent from the container image.

## Observed Instance (2026-06-19)

```
Error: Cannot find module 'google-spreadsheet'
Require stack:
- /app/services/server/web-console/.next/server/pages/api/projects/[projectId]/campaigns/[campaignId]/iplusn-cost-savings.js
...
code: 'MODULE_NOT_FOUND'
```

- Alarm: `/aws/ecs/notifly-services-prod/web-console console error`
- First seen: 2026-06-19 17:44 KST (1 occurrence in 7d — new issue)
- Impact: `iplusn-cost-savings` API route fully unavailable; console users receive 500
- Source file expected at: `src/pages/api/projects/[projectId]/campaigns/[campaignId]/iplusn-cost-savings.ts`
  (not present in local checkout at investigation time — possible source also missing or diverged from deployed bundle)

## Triage Steps

1. Confirm trigger: `Cannot find module '<package>'` + `code: 'MODULE_NOT_FOUND'` in current_trigger_contexts
2. Check `services/server/web-console/package.json` → `dependencies` (not just `devDependencies`)
3. Verify source file exists at `src/pages/api/projects/[projectId]/campaigns/[campaignId]/<route>.ts`
4. If source file missing: route deployed without source tracked — recover from git history
5. If source file exists but package missing: add to `dependencies` and redeploy
6. If package in devDeps only: move to `dependencies`

## Classification

- 1 occurrence in 7d (first occurrence) → `needs_fix`
- Recurring daily without fix → `needs_fix` (customer-visible 500 on that route)
- Not a false positive: the API route is fully broken for real console users

## Remediation

```bash
# In services/server/web-console/
pnpm add <missing-package>
# Then rebuild image and redeploy ECS web-console task
```

## Disambiguation

- npm path frames like `/node_modules/.pnpm/<hash>/...` appear in many ECS stack traces but
  are internal Next.js loader frames, not the trigger. The discriminator is the top-level
  `Cannot find module '<bare-package-name>'` line.
- Do not confuse with dynamic `require()` that intentionally falls back (those are caught
  and do not surface as unhandled errors).
