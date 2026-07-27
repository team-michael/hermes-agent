# user-csv-mailer: Early DynamoDB Lookup Failure (Unregistered projectId)

## Alert Pattern

Alarm: `user-csv-mailer lambda error`  
Metric filter: `%ERROR|Status: timeout%`  
Actual error: `ERROR Invoke Error {"errorMessage":"No such project"}`  
**NOT a true timeout** — Lambda exits in ~30–50 ms with ERROR log

## Root Cause

`user-csv-mailer` Lambda queries DynamoDB `user_property_fields` table at the **start of every invocation** to fetch custom user attribute field names. If the SQS message contains a `projectId` that does not exist in the `user_property_fields` table, the `GetItem` returns null and Lambda immediately throws "No such project" error.

### Code Path

```typescript
// lib/ddb.ts:8–17
export async function getUserPropertyHeaders(projectId: string) {
    const command = new GetItemCommand({
        TableName: 'user_property_fields',
        Key: marshall({ project_id: projectId }),
    });
    const response = await ddbClient.send(command);
    if (!response.Item) throw new Error('No such project');  // ← ERROR
}
```

Called from all four user-list service classes (`UserListService`, `CampaignMetricUserListService`, `UserJourneyMetricUserListService`, `UserJourneyVariantUserListService`) **before any Athena query, DB read, or S3 upload**.

## Scenarios

### Scenario A: Test/Demo Project Data Mixed into Production Queue

**Evidence:**
- SQS message contains `projectId: "tourlive"` or other demo/internal slug
- `user_property_fields` DynamoDB table confirmed to lack that projectId entry:
  ```bash
  aws dynamodb get-item --table-name user_property_fields \
    --key '{"project_id":{"S":"tourlive"}}' --region ap-northeast-2
  # Result: empty/null
  ```
- Web-console or admin tool enqueued CSV export request for a non-existent project

**Root cause:**
- Web-console CSV export form lacks projectId validation before SQS enqueue
- Manual SQS message creation, test harness, or Slack bot command used invalid projectId
- SQS message routing misconfiguration sends test queue to production Lambda

**Scope recovery:**
- Extract `projectId`, `projectName` from SQS `Received event:` JSON in Lambda logs
- Confirm projectId is not in `user_property_fields` table
- If also not in `project` table → purely internal test data; scope is "internal test"
- If in `project` table but missing from `user_property_fields` → initialization gap; scope is the real project

### Scenario B: Project Soft-Delete Without Queue Cleanup

**Evidence:**
- SQS message contains a known production projectId
- `user_property_fields` entry was deleted (project lifecycle management)
- Queue message was not purged during deletion
- Rare; no automated queue cleanup on project delete

**Root cause:**
- Project onboarding/teardown process is incomplete
- `user_property_fields` cleanup triggered but SQS messages not drained

**Scope recovery:**
- Check `project` table to confirm projectId exists and inspect its status (soft-deleted or hard-deleted)
- Look for related campaign/user journey records in Postgres to establish timeline
- Determine if projectId was deleted within last N hours via audit logs or source control

## Triage Checklist

### Step 1: Confirm It's NOT a True Timeout

```bash
# Check Lambda Duration metric — should be < 1000 ms, not 900000 ms
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Duration \
  --dimensions Name=FunctionName,Value=user-csv-mailer \
  --start-time '<alarm-window-start>' \
  --end-time '<alarm-window-end>' \
  --period 60 \
  --statistics Maximum \
  --region ap-northeast-2
# Expected: 30–100 ms (not 900000 ms)

# Check Lambda Errors metric
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=user-csv-mailer \
  --start-time '<alarm-window-start>' \
  --end-time '<alarm-window-end>' \
  --period 60 \
  --statistics Sum \
  --region ap-northeast-2
# Expected: 0 (Lambda caught the exception)
```

**If Duration < 1000 ms and Errors = 0:** This is an **early lookup failure**, not a timeout. Continue with Step 2.  
**If Duration ≈ 900000 ms and Errors > 0:** This is a true timeout crash. See other timeout patterns in `lambda-timeout-patterns` skill.

### Step 2: Extract the DynamoDB Lookup Error

```bash
# Find the earliest ERROR in the invocation
aws logs get-log-events \
  --log-group-name /aws/lambda/user-csv-mailer \
  --log-stream-name '<stream-name-from-alarm>' \
  --region ap-northeast-2 \
  --start-from-head \
  --query 'events[1:5].[timestamp, message]'
# Expected: First log after START should be ERROR with "No such project"
```

### Step 3: Extract SQS Message Scope

```bash
# Get the Received event log from the same invocation
aws logs get-log-events \
  --log-group-name /aws/lambda/user-csv-mailer \
  --log-stream-name '<stream-name-from-alarm>' \
  --region ap-northeast-2 \
  --query 'events[?contains(message, `Received event`)].[message]' \
  --output text | head -c 1000

# Parse the JSON manually or with jq:
# - projectId: the unregistered ID
# - projectName: human-readable name (e.g., "TOURLIVE")
# - type: export type (ALL_USER_LIST, CAMPAIGN_METRIC_USER_LIST, etc.)
```

### Step 4: Verify DynamoDB State

```bash
# Confirm projectId is NOT in user_property_fields
aws dynamodb get-item \
  --table-name user_property_fields \
  --key '{"project_id":{"S":"<projectId>"}}' \
  --region ap-northeast-2 \
  --output json
# Expected: empty {} (no Item field)

# Check if projectId exists in project table
aws dynamodb get-item \
  --table-name project \
  --key '{"id":{"S":"<projectId>"}}' \
  --region ap-northeast-2 \
  --output json
# If non-empty: project exists but user_property_fields is missing (init gap)
# If empty: projectId never existed (test data)
```

### Step 5: Assess Recurrence

```bash
# Count "No such project" errors in last 7 days
aws logs filter-log-events \
  --log-group-name /aws/lambda/user-csv-mailer \
  --start-time $(($(date -d '7 days ago' +%s) * 1000)) \
  --filter-pattern 'No such project' \
  --region ap-northeast-2 \
  --query 'events | length(@)'

# Group by day
aws logs filter-log-events \
  --log-group-name /aws/lambda/user-csv-mailer \
  --start-time $(($(date -d '7 days ago' +%s) * 1000)) \
  --filter-pattern 'No such project' \
  --region ap-northeast-2 \
  --output json \
  | jq -r '.events[].message' \
  | cut -d'T' -f1 | sort | uniq -c
```

**1–2 occurrences total:** isolated test-data request → `no_action`  
**3+ per day for 3+ days:** systematic enqueue validation gap → `needs_fix`  
**Daily spike at same time (e.g., 02:00 KST):** scheduled batch job using wrong projectId → `needs_fix`

## Classification

- **Single request with test projectId:** `no_action`
  - User manually initiated CSV export for demo project
  - Lambda rejected cleanly; no customer data loss
  - DLQ entry (from `maxReceiveCount=1`) is one message; no cascade

- **Multiple requests, same projectId, same day:** `no_action` (if ≤2 total) or `needs_fix` (if ≥3 or recurring daily)
  - Sporadic test data or misconfigured export script
  - If recurring daily at the same time → automated batch using wrong config

- **Multiple projectIds, high volume per day:** `needs_fix`
  - Web-console enqueue validation is broken
  - Source: form input, API endpoint, or external system sending unvalidated projectIds
  - Fix: add pre-enqueue check in web-console or enqueue endpoint

## Remediation

### Immediate (Block Unregistered Projects)

Update web-console CSV export endpoint to validate projectId before SQS enqueue:

```typescript
// src/api/projects/{projectId}/csv-export (or similar)
import { DynamoDB } from '@aws-sdk/client-dynamodb';

const ddb = new DynamoDB({ region: 'ap-northeast-2' });

export async function validateProjectForCsvExport(projectId: string) {
    const result = await ddb.getItem({
        TableName: 'user_property_fields',
        Key: { project_id: { S: projectId } },
    });
    
    if (!result.Item) {
        throw new BadRequestError(
            `Project ${projectId} is not registered for CSV export`
        );
    }
}

export async function handleCsvExportRequest(projectId, payload) {
    // Validate BEFORE enqueuing
    await validateProjectForCsvExport(projectId);
    
    // Safe to enqueue
    await sqs.sendMessage({
        QueueUrl: csvMailerQueueUrl,
        MessageBody: JSON.stringify({ projectId, ...payload }),
    });
    
    return { status: 'queued' };
}
```

### Medium-term (Improve Observability)

Update `lib/ddb.ts` to log projectId in the error for faster RCA:

```typescript
export async function getUserPropertyHeaders(projectId: string) {
    const command = new GetItemCommand({
        TableName: 'user_property_fields',
        Key: marshall({ project_id: projectId }),
    });
    const response = await ddbClient.send(command);
    if (!response.Item) {
        console.error(
            `[DynamoDB] user_property_fields missing for projectId: ${projectId}`
        );
        throw new Error(`No such project: ${projectId}`);
    }
    const { field_names } = unmarshall(response.Item);
    if (!field_names) throw new Error('Malformed project');
    return field_names as string[];
}
```

With this change, CloudWatch Logs and the helper script can auto-extract projectId from the ERROR line without manual SQS payload parsing.

### Long-term (Project Initialization)

Ensure `user_property_fields` is auto-created during project onboarding:

1. **Project creation endpoint** → call Lambda to initialize `user_property_fields` entry:
   ```
   PUT /api/projects/{projectId}
   → (success) → invoke Lambda initialize-user-property-fields
   → writes user_property_fields entry with default fields
   ```

2. **Document the entry point** in AGENTS.md or project onboarding runbook so new projects don't skip initialization.

3. **Add startup check** in web-console and other clients:
   ```typescript
   // Verify project is ready for CSV export
   async function ensureProjectReady(projectId) {
       const userProps = await getProjectUserProperties(projectId);
       if (!userProps) {
           // Try to initialize
           await initializeProjectForExport(projectId);
       }
   }
   ```

## Related References

- `lambda-timeout-patterns` skill § "Pattern: Early DynamoDB/External Dependency Lookup Failure" — generalized pattern for all Lambdas
- `user-csv-mailer-timeout-s3-multipart.md` — S3 multipart upload timeout scenario (different root cause, same alarm)
- Lambda architecture: all four user-list service classes call `getUserPropertyHeaders()` immediately
