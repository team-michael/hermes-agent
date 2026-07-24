# npm/pnpm Module Path False-Positive project_id Extraction

## Problem

The `check` helper's text detectors may extract hexadecimal-looking strings from npm/pnpm content-addressable store paths in stack trace frames and treat them as `project_id` values.

## Concrete example

In a `web-console` console error stack trace, the Sentry OpenTelemetry module path includes a pnpm hash:

```
/app/node_modules/.pnpm/@sentry+opentelemetry@10.39.0_@opentelemetry+api@1.9.0_@opentelemetry+context-async-hoo_27208c619616c79fc8e9d194fe0c9965/node_modules/@sentry/opentelemetry/build/cjs/index.js:992:15
```

The string `27208c619616c79fc8e9d194fe0c9965` matches the 32-character hexadecimal form of a Notifly `project.id`, but it is actually part of the pnpm store installation path, not a project identifier.

## Why it happens

pnpm uses content-addressable storage where the installation directory name includes a hash of the package's contents and peer dependencies. These hashes can coincidentally look like Notifly project IDs (MD5-like 32-char hex strings).

## Impact

- `detected.project_ids` includes a false positive
- `scope_attribution.projects[].mapping_status` becomes `not_found` when DynamoDB lookup fails
- The real `project_id` is missed unless recovered from other sources (e.g., access logs)

## How to detect during triage

When `scope_attribution.project_mapping_failures[]` shows:
- `status: "not_found"`
- `reason: "DynamoDB project table item not found"`
and the `project_id` string appears inside a node_modules path in the error stack trace, treat it as a false positive.

## How to recover the real scope

When the error log stack trace shows a parameterized Next.js API route (e.g., `/api/projects/[projectId]/...`), the actual resolved `project_id` is typically **not** in the error log. It must be recovered from the HTTP access log:

```
POST /api/projects/<actual_project_id>/test_send/kakao_brand_message HTTP/1.1
```

Also extract the `Referer` header for `productId` and map via DynamoDB `project` table GSI.

See `references/web-console-scope-attribution-via-access-logs.md` for full access log recovery commands and the multi-stream Fargate pitfall.

## Mitigation in the helper

The helper's `detect.py` or `scope.py` could be hardened to:
1. Skip strings that appear only inside `node_modules/.pnpm/` paths
2. Prioritize path-parameter matches from access logs over error-log stack frame substrings
3. Weight project_ids by confidence: explicit structured fields > URL path parameters > heuristic text extraction

For now, manual verification of `project_id` via DynamoDB and cross-reference with access logs is the reliable workaround.
