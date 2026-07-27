# AI-agent/API-created campaign breaks web-console: `customizedMessageData` array-vs-object mismatch

## Pattern

A `web-console/sentry` proxy alert (or any web-console `console error` alarm)
surfaces a client-side `TypeError` while a user opens a campaign create/edit
screen, e.g.:

```
TypeError: t.customizedMessageData?.forEach is not a function
  at services/server/web-console/src/utils/campaign/variables.ts:197
```

Do not assume this is a `web-console` code bug on first read. `variables.ts:197`
(`pushNotificationMessage.customizedMessageData?.forEach(({ value }) => ...)`)
is *correct* against the console's own internal contract:

- `models/Message.ts:14` — `export type Params = { key: string; value: string }[]`
  (array of `{key, value}` pairs)
- `schemas/common/message/notifications.ts` — `customizedMessageData:
  createParamsSchema(t).nullish()` (zod schema validating that array shape)
- Test fixtures (`MessageTransformer.pushNotification.spec.ts`) construct
  `customizedMessageData` as an array of `{key, value}` objects.

The actual root cause is upstream: the campaign's stored `customizedMessageData`
is a **plain JSON object** (`{"coupon": "SUMMER"}`) instead of the array shape
the console expects, so `.forEach` doesn't exist on it.

## Where objects can leak in instead of arrays

`api-service`'s public REST/MCP campaign-create contract validates
`customized_message_data` as `JsonObjectSchema = z.record(JsonValueSchema)`
(`lib/types/public-api-schemas.js:361` for push, similar for web-push) — i.e.
it happily accepts an arbitrary `{key: value}` object, not the array shape.

`toBuilderMessage()` (`lib/types/public-api-schemas.js:1462-1493`) then maps
`customized_message_data → customizedMessageData` by **field name only** — no
shape/format conversion — so whatever shape the caller sent (object or array)
passes straight through into the stored campaign the console later renders.

This means any external caller of the REST/MCP campaign create API — most
commonly an AI agent or automation script constructing the payload from a
"key/value map" mental model — can write a campaign with an object-shaped
`customizedMessageData` that `web-console` cannot open.

## Triage checklist for this alarm family

1. Get the exact triggering `TypeError`/stack frame from the Sentry payload
   (see `references/sentry-email-alert-pipeline-false-positives.md` for how
   to extract `sentryAlert.issue`, `request.url`, `tags.handled`).
2. Map `request.url` productId slug → `project.id` via DynamoDB `project`
   table GSI `product_id-project_id-index` (see that same reference for the
   query pattern).
3. Grep the crashing file (`variables.ts`, `MessageTransformer.ts`, or
   equivalent per-channel transformer) for the field's *console-side* type
   — check both the TS model (`models/*.ts` / `models/campaign/view/*`) and
   the zod schema under `schemas/common/message/*.ts`. Console-side truth
   wins over any single call site.
4. Cross-check the same field's *API-side* schema in
   `services/server/api-service/lib/types/public-api-schemas.js` and its
   `toBuilder*` mapper. If the API schema is looser (e.g. `z.record(...)`
   accepting any object) than the console's schema (array-of-pairs, or vice
   versa), that's the structural root cause — not a console code defect.
5. Report the exact field name and both schema shapes in `원인:` per the
   `check` skill's DB/API field-fingerprint requirement — do not just say
   "schema mismatch," name the field and both shapes.

## Fix options (rank by blast radius)

- **Preferred**: normalize shape at the API schema boundary. Either make
  `toBuilderMessage()` convert `Object.entries(customized_message_data).map
  (([key, value]) => ({key, value}))` when the console expects an array, or
  tighten the zod schema (`JsonObjectSchema` → an array-of-`{key,value}`
  schema) so malformed payloads are rejected at write time with a clear 400
  instead of silently corrupting stored campaign data.
- **Avoid**: patching the console call site alone (e.g. defensively checking
  `Array.isArray(customizedMessageData)` before `.forEach`) — this only masks
  the symptom; the stored data shape is still wrong and other consumers
  (e.g. `kds-consumer/lib/send_messages/push_notification_utils.ts:82`, which
  expects `Record<string, string>` and does `Object.entries(...)`) may have
  the opposite expectation, so the inconsistency needs to be resolved at the
  schema boundary, not scattered across call sites.

## Related

- `references/sentry-email-alert-pipeline-false-positives.md` — how to parse
  the Sentry email-proxy JSON payload and do scope attribution via
  `request.url` → productId → DynamoDB project GSI.
- `references/web-console-scope-attribution-via-access-logs.md` — companion
  pattern for scope attribution when the console error itself lacks
  `project_id` but access logs / Referer carry the productId.
