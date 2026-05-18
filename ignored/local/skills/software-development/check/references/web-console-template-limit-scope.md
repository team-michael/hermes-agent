# web-console "maximum number of registered templates" triage

## Pattern

**Alarm**: `/aws/ecs/notifly-services-prod/web-console console error`  
**Metric filter**: `%ERROR|Exception%`  
**Trigger log**: `Error: The maximum number of registered templates.`  
**Code path**: `upsertCampaign` → `upsertStandardCampaign` → `transform` (`chunks/71260.js`)

## Critical pitfall: do not assume AWS SES

The error message is **provider-agnostic**. AWS SES is only one of several template providers used by Notifly. Live verification is required before assigning root cause.

**Fast verification**:
```bash
python - <<'PY'
import boto3, os
session = boto3.Session(
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    region_name='ap-northeast-2'
)
ses = session.client('ses')
count = 0
next_token = None
while True:
    resp = ses.list_templates(MaxItems=10000, **({'NextToken': next_token} if next_token else {}))
    count += len(resp.get('TemplatesMetadata', []))
    next_token = resp.get('NextToken')
    if not next_token:
        break
print(f"SES templates: {count} / limit 10,000")
PY
```

If SES count is well under 10,000, the error is from **another provider** (NHN Cloud Kakao Bizmessage, Firebase, or internal soft-limit).

## Scope extraction from logs

The triggering API call is usually:
```
PUT /api/projects/{project_id}/campaigns HTTP/1.1" 500 55
```

Extract `project_id` from the URL path, then map via DynamoDB `project` table.

## Known instance

- **project**: `7c13e762845d59a28d26e93245c8796f` → `lifezip`
- **HTTP status**: 500 (not 4xx — server-side failure, not client input)
- **Action**: campaign create/save via web-console UI
- **Recurrence**: 30d 100회, 7d 22회 — structural issue, not transient

## Root cause narrowing

1. Check SES count (see above)
2. If SES is not the limit, inspect NHN Cloud template API responses in the same log stream (`filter @message like /template/ and @message like /maximum/`)
3. Check if the project uses Kakao Bizmessage channel — if yes, NHN Cloud template limit is the likely candidate
4. Look for `sender_info` or `request_body` fields in error context to identify the exact provider endpoint

## Recurrence classification

- **First occurrence or very low frequency** (single digit per week): `no_action` — alert is a handled provider rejection; track for log-level downgrade.
- **Recurring with customer impact** (weekly or daily, campaign/user-journey save fails): `needs_fix` — the provider quota is a structural constraint that repeatedly blocks user workflows. The fix is provider-side cleanup, not code.
- After fix: if the same project fires again within the same month, escalate to `needs_fix` and recommend a permanent quota increase or automated cleanup from the provider side.

## Post-incident analysis

When the user asks "when did it start / when was it resolved / where exactly":

1. **First occurrence**: Run a CloudWatch Logs Insights query on `/aws/ecs/notifly-services-prod/web-console`:
   ```sql
   fields @timestamp, @message
   | filter @message like "maximum number of registered templates"
   | sort @timestamp asc
   | limit 5
   ```
   This returns the earliest retained error line.

2. **Daily occurrence counts**:
   ```sql
   fields @timestamp, @message
   | filter @message like "maximum number of registered templates"
   | stats count(*) as cnt by bin(1d)
   | sort @timestamp asc
   ```

3. **Scope**: Extract `project_id` from the `PUT /api/projects/{project_id}/campaigns` or `PUT /api/projects/{project_id}/user_journeys/{id}` access log line that precedes the stack trace by 1–2 lines.

4. **Resolution check**: If the daily count drops to zero after a specific date, correlate that date with the `cleanup-nhncloud-unused-templates.yml` workflow run history (GitHub Actions → workflow runs).

## Resolution: GitHub workflow

When this pattern is confirmed (SES count well under 10,000 and log shows `upsertCampaign` → `transform` failure), the resolution is **not** a code fix. A GitHub Actions workflow exists for manual NHN Cloud unused template cleanup:

- **Workflow**: `cleanup-nhncloud-unused-templates.yml`
- **Action**: Human operator runs the workflow, then manually deletes unused templates from the NHN Cloud Console.
- **Historical success**: This exact pattern was previously resolved successfully via this workflow.

**Next-session guidance**: When the current trigger log is `Error: The maximum number of registered templates.` and SES verification shows headroom, skip prolonged investigation and guide directly to the `cleanup-nhncloud-unused-templates.yml` workflow. Mention the historical resolution in the response.

## Distinguishing from metric-filter noise

If the only ERROR logs are access logs with `templateName=service_error` in referrer, this is a **false positive** matching the `%ERROR%` substring. Always confirm the actual `500` response line exists before treating as a real incident. See `references/ecs-console-error-false-positive-patterns.md` for the access-log false-positive class.
