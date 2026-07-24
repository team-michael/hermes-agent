# web-console `SyntaxError: "[object Object]" is not valid JSON` — double JSON.parse bug

## Signature

Sentry-proxied alert (`/aws/ecs/notifly-services-prod/web-console/sentry`) with:
- `sentryAlert.issue.title`: `SyntaxError`
- `sentryAlert.issue.message`: `"[object Object]" is not valid JSON`
- `sentryAlert.issue.transaction`: varies by route (confirmed so far: `POST /api/kakao/alimtalk/template`, `PUT /api/projects/[projectId]/campaigns`, `POST /api/kakao/alimtalk/templates` — the plural/list route, confirmed 2026-07-08)

## Root cause

This is a **real unhandled code bug**, not a handled business rejection like the
other Sentry-proxy pitfalls in this skill (Kakao image upload, LiquidJS abort,
template limit, etc.). The Next.js API route handler calls `JSON.parse(req.body)`
directly, but the framework's body-parsing middleware has already deserialized
`req.body` into a plain object before the handler runs. `JSON.parse` on a
non-string argument coerces it via `String(value)` first, which for a plain
object yields the literal string `"[object Object]"` — and that string is not
valid JSON, so `JSON.parse` throws.

Confirmed instances (as of 2026-07):
- `services/server/web-console/src/pages/api/kakao/alimtalk/template.ts:6`
  ```ts
  const { platform, template_id: templateId, platform_params } = JSON.parse(req.body);
  ```
- `services/server/web-console/src/pages/api/kakao/alimtalk/templates.ts:8`
  (note the intermediate variable, but same defect — `req.body` is assigned to
  `params` first, then re-parsed):
  ```ts
  Confirmed instance: `services/server/web-console/src/pages/api/kakao/alimtalk/template.ts:6`
  ```ts
  const { platform, template_id: templateId, platform_params } = JSON.parse(req.body);
  ```

  Confirmed second instance (2026-07-08), the plural/list route — same anti-pattern,
  no try/catch guarding the parse line itself so it is fully unhandled:
  `services/server/web-console/src/pages/api/kakao/alimtalk/templates.ts:8`
  ```ts
  export default wrap(
      getApiRoute().post(async (req, res) => {
          const params = req.body;
          const { platform, platform_params } = JSON.parse(params);   // <- throws here, before try
          try {
              const templateList = await getAllTemplates(platform, platform_params);
              ...
  ```
  This confirms the bug is a repeating class-level pattern across at least three
  routes (`template.ts`, `templates.ts`, campaign `PUT`), not a single incident.
  Any future occurrence of this exact `SyntaxError` on a new route should be
  treated as the same anti-pattern by default — check the route file for a
  `JSON.parse(req.body)` (or a renamed local var holding `req.body`) before doing
  any deeper investigation.

  The request fails with an unhandled 500; no data is lost, but that single
  request/action fails for the user (e.g. Kakao Alimtalk template lookup fails,
  or a campaign PUT fails).

  ## Confirming scope and recurrence
`JSON.parse(params)` (where `params = req.body`) in
`services/server/web-console/src/pages/api` turns up **~188 matches** across
the API route tree (`project_stats.ts`, `campaign/names.ts`,
`experiment/upsert.ts`, `crm/query.ts`, `variant/upsert.ts`,
`kakao/alimtalk/create_template.ts`, `kakao/alimtalk/delete_template.ts`,
`kakao/alimtalk/upload_template_img.ts`, `kakao/alimtalk/sender_profiles.ts`,
`ses/create_template.ts`, `project/payment/coupon/list.ts`, and many more).
Every one of these routes has the same latent defect and will throw the
identical `SyntaxError: "[object Object]" is not valid JSON` the moment a
request arrives where Next.js has already deserialized `req.body` into an
object (e.g. a specific `Content-Type` or Next.js API body-parser config).
Only 2-3 routes have actually been observed triggering it so far — the other
~185 are dormant instances of the same bug, not separate issues. This is why
the fix belongs at the shared `wrap`/`getApiRoute` middleware layer
(`src/pages/api/lib/middleware.ts`) rather than as a per-route patch: patching
one occurrence at a time will keep surfacing "new" alerts for the same root
cause indefinitely.

## Confirming scope and recurrence

Because the exact message text is stable and rare, a 30-day Logs Insights scan
on the same log group cheaply confirms whether this is a one-off or a repeating
class of bug across routes:

```bash
aws logs start-query --region ap-northeast-2 \
  --log-group-name '/aws/ecs/notifly-services-prod/web-console/sentry' \
  --start-time <now-30d epoch> --end-time <now epoch> \
  --query-string 'fields @timestamp, @message | filter @message like /is not valid JSON/ | sort @timestamp desc | limit 50'
# then: aws logs get-query-results --region ap-northeast-2 --query-id <id>
```

Parse each hit's `sentryAlert.issue.transaction` to see which routes are
affected. If more than one distinct route shows up (as of 2026-07 there are
two), treat it as a repeating code-pattern bug, not a single incident — search
the repo for other occurrences of the same anti-pattern before writing the
action item:

```bash
search_files(pattern="JSON.parse(req.body)", target="content", path="services/server/web-console/src/pages/api")
```

## Classification

- `needs_fix` when this signature appears (even at low volume like 2/30d)
  because it is a genuine unhandled-exception code defect with a concrete fix
  target, not routine alert noise. Do not downgrade to `no_action` just
  because frequency is low — the low frequency reflects how rarely the
  triggering request shape occurs, not that the bug is benign.
- Escalate toward `urgent` only if volume spikes sharply (e.g. a client library
  upgrade starts sending this request shape at high volume) or if the affected
  route is on a critical write path with no client-side retry.

## Fix pattern

Guard against re-parsing an already-parsed body:
```ts
const body = typeof req.body === 'string' ? JSON.parse(req.body) : req.body;
```
Prefer fixing at the shared middleware layer (`getApiRoute`/`wrap` in
`src/pages/api/lib/middleware.ts`) if multiple routes share the same
hand-rolled `JSON.parse(req.body)` pattern, rather than patching each route
individually — check whether Next.js API config already parses JSON bodies by
default before adding a second manual parse step anywhere in the codebase.

**Do not write the `액션 아이템:` as a single-route patch.** Every time this
signature is seen on a *new* route, it is tempting to name just that file as
the fix target. Don't — a `search_files(pattern="JSON.parse\\((req\\.body|params)\\)")`
scoped to `services/server/web-console/src/pages/api` reliably turns up ~188
matches (see "Scale of the anti-pattern" above). Name the shared
`wrap`/`getApiRoute` middleware in `src/pages/api/lib/middleware.ts` as the
primary action item, and mention the specific route only as the triggering
instance. This keeps `needs_fix` action items pointed at the actual fix
surface instead of generating a new ticket per route every time the bug
resurfaces on a different endpoint.
