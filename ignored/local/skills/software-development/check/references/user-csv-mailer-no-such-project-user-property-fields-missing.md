# user-csv-mailer "No such project" — Missing user_property_fields

## Pattern

`user-csv-mailer` Lambda throws `Error: No such project` from `getUserPropertyHeaders()` (`lib/ddb.ts:17`) when the `user_property_fields` DynamoDB table has no item for the message's `projectId`. The error message is misleading — the project **does** exist in the `project` table; only the `user_property_fields` entry is missing.

## Alarm shape

- Alarm: `user-csv-mailer lambda error`
- Namespace: `ConsoleErrors`
- Metric filter: `%ERROR|Status: timeout%`
- The `ERROR Invoke Error` line matches the `%ERROR%` portion of the filter.
- `AWS/Lambda` `Errors` metric is **non-zero** (this is a real thrown exception, not a ConsoleErrors false positive).
- `Throttles` = 0, `Duration` is short (~70–80 ms) — the function fails immediately.

## Root cause

```
SQS message (CAMPAIGN_METRIC_USER_LIST)
  → handler → CampaignMetricUserListService.generateAndSendUserList
    → getUserPropertyHeaders(projectId)
      → DynamoDB GetItem on "user_property_fields" with key {project_id: projectId}
      → response.Item is null
      → throw new Error('No such project')
```

The `user_property_fields` table is populated during project setup. If the project was created without this step (or the entry was deleted), all `CAMPAIGN_METRIC_USER_LIST` and `USER_JOURNEY_METRIC_USER_LIST` messages for that project will fail with this error.

## Triage steps

1. Run the helper with `--alarm-name 'user-csv-mailer lambda error'`.
2. If `current_trigger_contexts` is empty (common for 1-minute alarm windows), run `filter-log-events` with `--filter-pattern 'ERROR'` bounded to the alarm datapoint window (`StateReasonData.startDate`).
3. Read the full log stream (no filter) to get the `Received event:` line — the SQS body JSON contains `projectId`, `projectName`, `campaignId` or `userJourneyId`, and `recipient`.
4. Verify the project exists in DynamoDB `project` table (it will — the error is not about the `project` table).
5. Check `user_property_fields` table for the same `project_id`:
   ```bash
   aws dynamodb get-item --region ap-northeast-2 \
     --table-name user_property_fields \
     --key '{"project_id":{"S":"<projectId>"}}' \
     --projection-expression 'project_id'
   ```
   If empty → confirmed root cause.
6. Check DLQ (`user-csv-mailer-queue-dlq`) depth and peek messages for scope. The queue uses `maxReceiveCount=1`, so every failure goes straight to DLQ.
7. Check `AWS/Lambda` `Errors` metric by day — non-zero values confirm real exceptions, not metric-filter noise.

## Scope extraction

- `projectId` from the `Received event:` SQS body or DLQ message body.
- `campaignId` (for `CAMPAIGN_METRIC_USER_LIST`) or `userJourneyId` (for `USER_JOURNEY_METRIC_USER_LIST`).
- Map `projectId` via DynamoDB `project` table for product/name.

## Classification

- **Status**: `needs_fix` when the `user_property_fields` entry is missing for a production project and the alarm is recurring. The missing entry is a data/setup gap that should be resolved by creating the `user_property_fields` item or adding graceful fallback in `CampaignMetricUserListService`.
- **Status**: `no_action` when the project is a known internal/test project and the alarm is sporadic with no customer-facing impact.

## Frequency pattern

This alarm tends to recur on days when the affected project's campaign metric reports are triggered. The same `projectId`/`campaignId` combination produces identical errors. 30-day counts are typically 8–13 occurrences across 5–7 days.

## Remediation

1. **Immediate**: Create the missing `user_property_fields` DynamoDB item for the affected project(s). The item should have `project_id` and `field_names` (array of user property field names).
2. **Code-level**: Add graceful fallback in `CampaignMetricUserListService.generateAndSendUserList` (`lib/services/CampaignMetricUserListService.js:64`) when `getUserPropertyHeaders` throws — skip the export with a WARN log instead of crashing the invocation.
3. **Structural**: Consider raising `maxReceiveCount` from 1 to 3 on `user-csv-mailer-queue` (`infra/terraform/prod/ap-northeast-2/sqs/queues.tf` line ~940) to allow retry for transient errors. Note: this will NOT fix deterministic failures like missing `user_property_fields`, but it helps transient cases.

## Key distinction from user-csv-mailer timeout

| Aspect | Timeout (`user-csv-mailer-lambda-timeout.md`) | No such project (this reference) |
|--------|-------|-------|
| Error type | `REPORT ... Status: timeout` | `ERROR Invoke Error {"errorMessage":"No such project"}` |
| Duration | ~900,000 ms (timeout limit) | ~70–80 ms (immediate failure) |
| AWS/Lambda Errors | May be 0 (timeout is not an Error metric) | Non-zero (real exception) |
| Root cause | Large CSV export exceeding 900s | Missing `user_property_fields` DynamoDB item |
| Fix | Timeout/range guard | Create DynamoDB item or add fallback |

## Real example (2026-06-25)

- Project: `daa553e36a4257ada5524fe2c878d90b` (notifly-kokomo, prod, `dev=false`)
- Campaign: `ZGQ2Dm` (CAMPAIGN_METRIC_USER_LIST)
- Recipients: internal accounts (`hyukjun@greyboxhq.com`, `canic322@gmail.com`)
- Both `notifly-kokomo` projects (dev=true `4e619f9e...` and dev=false `daa553e3...`) were missing `user_property_fields` entries.
- 30-day error count: 8 across 6 days (05-28, 06-12, 06-15, 06-16, 06-17, 06-24, 06-25).
- DLQ had 2 messages, both with the same projectId/campaignId.

## Variant — `ALL_USER_LIST` message type (2026-07-10)

The same `getUserPropertyHeaders` → `No such project` bug also fires for the
`ALL_USER_LIST` message type, not only `CAMPAIGN_METRIC_USER_LIST` /
`USER_JOURNEY_METRIC_USER_LIST`. Stack shape differs slightly:

```
Error: No such project
    at getUserPropertyHeaders (/var/task/lib/ddb.js:18:15)
    at process.processTicksAndRejections (node:internal/process/task_queues:103:5)
    at async UserListService.generateAndSendUserList (/var/task/lib/services/UserListService.js:47:37)
    at async Promise.all (index 0)
    at async Runtime.handler (/var/task/index.js:42:5)
```

Note the service class is `UserListService` (not `CampaignMetricUserListService`)
and the SQS body has `"type":"ALL_USER_LIST"` with no `campaignId`/`userJourneyId`
field — it's a full-user-list CSV export request, not a campaign/journey metric
export. Same root cause (missing `user_property_fields` DDB item), same fix path.

- Example project: `13181e6f13f054f28a55719599a8c792` → DynamoDB name/product_id
  `notifly-alwayz-demo` (internal Notifly demo project, per project-naming
  convention in main SKILL.md). 30d/7d/1d/10m: 15/2/1/1, sporadic, no worsening
  trend → classified `no_action` (internal demo project, no customer impact).
- Duration was 87.48 ms, `Init Duration` 1383.81 ms (cold start) — consistent
  with the immediate-failure timing signature in the table above.

## Pitfall — recovering the real `projectId` when helper/filter output is sanitized

The `check` helper sanitizes `current_trigger_contexts` sample lines, so the
`"Received event:"` SQS body shows `\"projectId\\\":\\\"<project_id>\\\"` as a
masked placeholder instead of the real value, and `detected_scope_ids` /
`scope_attribution` may come back empty/`unknown` even though the real ID is
sitting in the raw log stream. Likewise, a targeted
`filter-log-events --filter-pattern ERROR` only returns the `ERROR Invoke Error`
line itself, not the preceding `Received event:` INFO line that carries the ID.

To recover the actual `projectId`/`projectName`:
1. From the sanitized trigger context or a scoped `filter-log-events` call, get
   the exact `logStreamName` (e.g. `2026/07/10/[$LATEST]<request-id>`).
2. Pull the **full, unfiltered** stream with `get-log-events --start-from-head`
   on that exact stream (not `filter-log-events`, which only returns matched
   lines):
   ```bash
   aws logs get-log-events --region ap-northeast-2 \
     --log-group-name '/aws/lambda/user-csv-mailer' \
     --log-stream-name '<log_stream_name>' \
     --start-from-head --output json
   ```
3. Regex the `"Received event:"` INFO line for `projectId` and `projectName`
   directly (the raw stream is not sanitized like helper output):
   ```python
   import re
   m = re.search(r'projectId[\\"]*:\s*[\\"]*([a-zA-Z0-9_-]+)', message)
   n = re.search(r'projectName[\\"]*:\s*[\\"]*([A-Za-z0-9_-]+)', message)
   ```
4. Map the recovered `project_id` via DynamoDB `project` table as usual.

This same technique applies to any `user-csv-mailer`/SQS-consumer Lambda alarm
where the helper's scope aggregator reports unknown scope despite the ID being
present but masked in the sanitized sample.
