# web-console: NHN Cloud MMS attachment format validation (false positive)

## Signature
Current alarm trigger (`/aws/ecs/notifly-services-prod/web-console console error`, metric filter `%ERROR|Exception%`):

```
Image format is not jpg
Error: Image format is not jpg
    at u (.../71260.js:1:1071)
    at async g (.../71260.js:1:2840)
    at async g.uploadFileAndGetId (.../71260.js:2:13138)
    at async g.uploadAttachmentsAndGetFileIds (.../71260.js:2:12876)
    at async g.transformForTest (.../71260.js:2:11610)
    at async Array.q (.../pages/api/projects/[projectId]/test_send/text_message.js:1:6284)
```

Sibling signature: `Error: Attach file required jpg or jpeg.` — same code path, same root cause family.

## Root cause
Neither string exists in the `notifly-event` codebase. Both are NHN Cloud SMS/MMS API's own
`header.resultMessage` values, re-thrown verbatim by the shared `request()` helper:

`services/server/web-console/src/pages/api/lib/text_message/nhncloud.ts:27-28`
```js
if (!response?.data?.header?.isSuccessful) {
    throw new Error(response?.data?.header?.resultMessage ?? 'Unknown Error');
}
```

Call chain: `TextMessageTransformer.uploadFileAndGetId()` (`.../transformers/TextMessageTransformer.ts:236`)
→ `uploadImage()` (`nhncloud.ts:195`, `POST .../attachfile/binaryUpload`) → `uploadAttachmentsAndGetFileIds()`
→ `TextMessageTransformer.transform()`/`transformForTest()`, triggered from
`POST /api/projects/{projectId}/test_send/text_message` when a console user test-sends an MMS
message with a non-jpg/jpeg attachment.

This is a handled client-input rejection — NHN Cloud rejects unsupported image formats for MMS
attachments. The API responds `400` (not 500); no crash, no data loss, no delivery attempted.

## Scope recovery
The error log itself carries no `project_id`. Recover from the immediately-following access log
line in the same log stream:
```
POST /api/projects/<project_id>/test_send/text_message HTTP/1.1" 400 ... "https://console.notifly.tech/console/products/<product_slug>/campaign/create?...&id=<campaign_id>&mode=edit"
```
Map `<project_id>` via DynamoDB `project` table to confirm product slug.

## Classification
`no_action` — same family as the already-catalogued Kakao image-upload/NHN SMS template
validation false positives (`web-console-kakao-image-upload-validation-error.md`,
`web-console-nhncloud-sms-template-character-validation.md`). The underlying
`/aws/ecs/notifly-services-prod/web-console console error` alarm has threshold=1/min and fires
on any of a dozen distinct handled-rejection strings, so daily count and rapid recurrence
(multiple ALARM/OK flips within 10-30 min) alone are not evidence of a real incident — check the
`current_top_signatures`/`current_trigger_contexts` for the *specific* concrete string first.

Escalate to `needs_fix` only if this exact signature (not the alarm as a whole) spikes sharply
and consistently across many distinct projects, suggesting a missing client-side pre-validation
(the console should reject non-jpg files in the browser before the round-trip to NHN Cloud).

## Example (2026-07-28)
- Trigger at 2026-07-28T06:18:55Z, alarm datapoint 06:18:00Z.
- Matching access log: `POST /api/projects/91a042a79e4c5c4fa3af7c3d3b5aaf53/test_send/text_message HTTP/1.1" 400` at 06:18:55.344Z, referer `.../console/products/doctornow/campaign/create?...&id=g2BVZR&mode=edit`.
- Scope: `doctornow/g2BVZR` (test_send action on a campaign, not a user journey).
- Alarm history that day: 11 ALARM transitions, mixed with unrelated top signatures (S3 SDK errors, "user not found", "Required query param is missing") on the same noisy alarm — none of which correlate with each other; each is an independent handled rejection.
- Classified `no_action`.
