# web-console: NHN Cloud SMS/LMS template "Unacceptable characters in title and body" false positive

## Signature
Current alarm trigger (`/aws/ecs/notifly-services-prod/web-console console error`, metric filter `%ERROR|Exception%`):

```
Error: Unacceptable characters in title and body.
    at u (.../71260.js:1:1071)
    at async d (.../71260.js:1:2043)
    at async m (.../71260.js:1:1560)
    at async g.failoverTextMessage (.../71260.js:2:10940)
    at async T.inline (.../71260.js:2:985)
    at async u (.../21885.js:9:2075)
    at async N.upsertStandardCampaign (.../21885.js:3:9726)
    at async N.upsertCampaign (.../21885.js:3:9013)
    at async Array._ (.../pages/api/projects/[projectId]/campaigns.js:1:7797)
```

## Root cause
The string is **not** in the `notifly-event` codebase. It is the literal `resultMessage` returned
by NHN Cloud's SMS template-registration API when a template's title/body contains characters
outside NHN Cloud's allowed set for SMS/LMS (commonly certain emoji/symbols).

Code path (minified stack maps to):
- `services/server/web-console/src/domains/message/transformers/TextMessageTransformer.ts:81` —
  `TextMessageTransformer.failoverTextMessage()` calls `createTemplate(...)` to register the
  Kakao-failover SMS/LMS text with NHN Cloud before saving the campaign.
- `services/server/web-console/src/pages/api/lib/text_message/nhncloud.ts:37` — `createTemplate()`
  → internal `request()` helper does:
  ```js
  if (!response?.data?.header?.isSuccessful) {
      throw new Error(response?.data?.header?.resultMessage ?? 'Unknown Error');
  }
  ```
  which re-throws the NHN Cloud API's own rejection message verbatim.
- Call site: `services/server/web-console/src/services/CampaignService.ts` `upsertStandardCampaign` →
  `upsertCampaign` → `PUT /api/projects/{projectId}/campaigns`.

This is a handled business/input-validation rejection at campaign-save time, not a service bug.
The console user's failover text (SMS/LMS fallback for a Kakao Alimtalk/Friendtalk/brand message)
has content NHN Cloud's template validator rejects. No message is sent; no data loss. The user
sees a 500 on save and must edit the failover text content.

## Scope recovery
The structured error log itself carries no `project_id`. Recover scope from the sibling access-log
line for the same request in the **same log stream**, matched by timestamp:

```bash
aws logs filter-log-events --region ap-northeast-2 \
  --log-group-name /aws/ecs/notifly-services-prod/web-console \
  --log-stream-names '<stream-from-current_error_details>' \
  --start-time <alarm_datapoint_ms - 120000> --end-time <alarm_datapoint_ms + 30000> \
  --output json
```

Look for the `PUT /api/projects/<project_id>/campaigns ... 500` line at (or just after) the
`Error: Unacceptable characters...` block. The `Referer` header carries the product slug:
`https://console.notifly.tech/console/products/<product_slug>/campaign/create?...&id=<campaign_id>&mode=edit`.

Map `<project_id>` via DynamoDB `project` table (`id`, `product_id`, `name` projection) to confirm
the product slug and get the campaign scope as `<product_slug>/<campaign_id>`.

## Classification
- `no_action` when isolated / matches the recurring daily baseline (this alarm fires ~1-10x/day,
  93 times over 30d as of 2026-07, mixed with other `%ERROR|Exception%` causes on this log group —
  see `ecs-console-error-false-positive-patterns.md` for the sibling false-positive family).
- Escalate to `needs_fix` only if this specific signature spikes sharply and consistently across
  many distinct projects — that would suggest a missing client-side pre-validation regression
  (i.e., the web-console campaign editor should validate failover SMS/LMS title/body against
  NHN Cloud's allowed character set *before* the round-trip, not surface the raw provider error
  as an unhandled 500).

## Example (2026-07-09)
- Trigger at 2026-07-09T10:13:11Z, alarm datapoint 10:12:00Z.
- Matching access log: `PUT /api/projects/b2b4a8f879a75673b755bff42fc1deb6/campaigns HTTP/1.1" 500`
  at 10:13:11.687Z, referer `.../console/products/class101/campaign/create?...&id=hrh0H4&mode=edit`.
- DynamoDB `project` lookup: `id=b2b4a8f879a75673b755bff42fc1deb6`, `product_id=class101`,
  `name=class101`.
- Scope: `class101/hrh0H4`. Classified `no_action` (30d count 93, isolated single-project incident,
  known recurring alarm family on this log group).
