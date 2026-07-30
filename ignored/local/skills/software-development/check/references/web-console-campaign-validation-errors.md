# Web-Console Campaign Validation Error (False Positive)

**Alarms**: `/aws/ecs/notifly-services-prod/web-console console error` (direct ECS log metric filter `%ERROR|Exception%`) **and** `/aws/ecs/notifly-services-prod/web-console/sentry alert` (Sentry email-alert proxy pipeline, see `sentry-email-alert-pipeline-false-positives.md`). The same underlying application error can trip either alarm depending on whether it's caught by the local console log filter or forwarded to Sentry → SES → `ops-email-receiver`. Always check both possible log groups when tracing one of these signatures.

Three handled validation patterns currently trigger these alarms during campaign upsert or test-send:

1. **`Error: 템플릿 링크 검증 실패:`** — Kakao brand message mobile web link validation failure
2. **`Error: SMS Body length must be under 255.`** — SMS message body exceeds provider limit
3. **`Error: Unacceptable characters in title and body.`** — message title/body contains characters rejected by the channel-specific validator (exact character set not found in `notifly-event` source; the string only exists in compiled `.next` chunks, e.g. `chunks/71260.js`)

## What it is

Both originate from the same code path: `CampaignService.upsertCampaign` → `MessageTransformer.transform` → channel-specific validation. These are **handled business rejections** of client-provided campaign template content.

### Kakao brand message link validation

- Triggered during `POST /api/projects/{projectId}/test_send/kakao_brand_message` or campaign save
- Stack frame: `.next/server/pages/api/projects/[projectId]/test_send/kakao_brand_message.js` or `.next/server/chunks/71260.js` (`transform` → `inline`)
- The API returns HTTP 500 to the web-console client; the UI displays the validation message to the user
- No message is actually sent to recipients

### SMS body length validation

- Triggered during campaign upsert for SMS channel
- Stack frame: `.next/server/chunks/17968.js` (`C.upsert` → `y.messageNodeDetails` → `g.transform` → `m` → `d`)
- Same behavior: HTTP 500 response to client, message not sent

### Unacceptable characters in title/body

- Triggered during `PUT /api/projects/{projectId}/campaigns` (campaign save)
- Stack frame: `.next/server/chunks/71260.js` (`CampaignService.upsertCampaign` → `MessageTransformer.transform`, frames named `u`/`d`/`m`/`g.failoverTextMessage`/`T.inline` in the minified bundle) — same transform pipeline as the other two patterns, different validator branch
- Sentry issue observed: a single recurring issue ID (e.g. `7545407593`) re-fires as "New issue"/"Ongoing issue" over weeks — this is the SAME underlying bug recurring, not a new one each time. Do not treat repeat firings of the same Sentry issue ID as escalating severity.
- Same behavior: HTTP 500 to console client, message not sent, no data loss
- When this alarm arrives via the `.../web-console/sentry alert` alarm (not the direct console alarm), the exact `projectId` is recoverable from `tags.api.route` or `request.url` in the Sentry JSON payload (e.g. `"api.route":"/api/projects/b2b4a8f879a75673b755bff42fc1deb6/campaigns"`) — no need for access-log Referer correlation in this case, the Sentry payload already carries the full path.

## Scope

Exception log lines do not contain structured `project_id` or `campaign_id`. Use one of:

1. **Access log correlation**: Search the same alarm window for `POST /api/projects/<project_id>/test_send/kakao_brand_message` (Kakao) or `PUT /api/projects/<project_id>/campaigns` (SMS). Extract `<project_id>` from the URL path and map via DynamoDB `project`.
2. **Stack frame hint**: For Kakao link errors, the stack frame `kakao_brand_message.js` combined with access logs is definitive. For SMS errors, the `chunks/17968.js` frame with `CampaignService.upsert` is definitive.
3. **Referer header**: Access logs on the same Fargate task may include `Referer: https://console.notifly.tech/console/products/<productId>/campaign/create`. Map `<productId>` via DynamoDB `project` GSI `product_id-project_id-index`.

**Pitfall — log stream split**: The web-console runs multiple Fargate tasks. The ERROR log and the matching 500 access log may land on different log streams. Search across all active streams in the alarm window.

## Volume

- **Kakao link validation**: typically 1–5 events per 30 days, sporadic
- **SMS body length**: typically 1–10 events per 30 days, sporadic
- Combined with other web-console handled rejections, total `ConsoleErrors` 30-day volume is typically 300–500
- Individual days may see 0–20 transitions depending on user activity

## Triage

When the current trigger context shows either pattern:

```sql
fields @timestamp, @message
| filter @message like '템플릿 링크 검증 실패'
   or @message like 'SMS Body length must be under'
| stats count() as cnt
| limit 1
```

Run against `/aws/ecs/notifly-services-prod/web-console` for the current alarm window and 7d. If these are the dominant or sole ERROR patterns and no other ERROR patterns exist, classify as `no_action`.

For the Sentry-proxy variant (`.../web-console/sentry alert`), when Logs Insights returns empty `current_trigger_contexts` (common — see `sentry-email-alert-pipeline-false-positives.md` ingestion-lag pitfall), go straight to `filter_log_events` on `/aws/ecs/notifly-services-prod/web-console/sentry` bounded to the alarm's `stateReasonData` minute; the Sentry JSON payload is self-contained (issue id, transaction, message, tags.api.route, project.name) and does not need Logs Insights at all for a single-event alarm (`Threshold: 1.0`, `EvaluationPeriods: 1`).

Confirm absence from codebase:

```bash
grep -r -E "템플릿 링크 검증 실패|SMS Body length must be under" /home/ubuntu/.hermes/workspace/notifly-event/src/ || echo "not found"
```

These strings exist in compiled chunks, not in source-level code paths we can directly patch; the validation is deep in the channel-specific transform pipeline.

## Remediation direction

- Downgrade the log level from `ERROR` to `WARN` for handled validation rejections in `CampaignService.upsertCampaign` or the channel-specific `transform` layer, or
- Pre-validate the constraints client-side so the invalid state never reaches the server ERROR path.

## Fourth pattern: dangling `csv` segment `uploaded_filename` (MCP/API-created campaign, no S3 existence check)

**Alarm**: same `.../web-console/sentry alert` proxy. Sentry issue title `NoSuchKey`, `transaction: "POST /api/s3/get_segment_data"`.

Distinct from the three handled-rejection patterns above — this is a genuine dangling reference, not a benign business rejection:

- `campaign.segment.details.uploadedFilename` (Postgres `campaigns_<project_id>.ui_state_json` / `view_state`, `segment.mode = "csv"`) points at an S3 key `csv-segment/<project_id>/<uploadedFilename>` that does not exist.
- Web-console's own upload flow (`/api/s3/upload_segment_data`, `multerS3`) always writes `${projectId}/${uuidv4()}.csv` and returns that generated name — so a console-originated campaign can never have a dangling filename.
- The public API/MCP `create_campaign` contract (`CsvSegmentDetailsSchema` in `lib/types/public-api-schemas.js`, `uploaded_filename: z.string().min(1)`) only checks the string is non-empty. It does **not** verify the S3 object exists before persisting the campaign. So an MCP/API-created csv-segment campaign whose caller supplied an arbitrary/typo'd/never-uploaded filename saves successfully, then 500s with `NoSuchKey` every time a human opens it in web-console (`mode=edit` or `mode=clone`) because `readSegmentCsvFileFromS3` → `GetObjectCommand` fails.
- Confirm via access logs on the alarm window: repeated `POST /api/s3/get_segment_data` 500s with `Referer: .../console/products/<productId>/campaign/create?...&id=<campaignId>&mode=edit` from the affected customer, while other concurrent `get_segment_data` calls for other campaigns return 200 — proves it's one specific campaign/file, not a service-wide S3 problem.
- Map `productId` → project via DynamoDB `project` GSI `product_id-project_id-index`; read `campaigns_<project_id>` row by the URL's `id` for `creator`/`ui_state_json`/`view_state.segment.details.uploadedFilename`; confirm absence with `aws s3api list-objects-v2 --bucket csv-segment --prefix '<project_id>/'` (no lifecycle expiry configured on this bucket, so absence means never-uploaded/wrong-name, not expired).

**Customer impact**: real, not benign — the customer cannot open or edit that campaign at all; every attempt 500s. Treat as `needs_fix` (tracked, non-urgent unless the customer reports being blocked urgently), not `no_action`, and not `urgent` unless it's blocking an imminent scheduled send.

**Fix direction**: add an S3 existence check (`HeadObjectCommand`) for `csv-segment/<projectId>/<uploadedFilename>` in the `csv` branch of segment-mode validation in `services/server/api-service/lib/api/v1/projects/services/campaignService.js` (near the `SEGMENT_MODE_MATRIX` validation block), returning a 400 `INVALID_ARGUMENT` at creation/replace time instead of letting web-console 500 later. Do not patch only the console call site — the dangling data can still exist for already-created campaigns.
