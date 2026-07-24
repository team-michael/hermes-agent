# kds-consumer Kakao Sender Info Validation Error

## Pattern

```
ERROR kakao sender info is not provided for project <project_id>
WARN Invalid sender info for campaign. projectID: <project_id>
```

Lambda completes normally (`Errors=0`, `Throttles=0`, normal Duration), but logs trigger `ConsoleErrors` metric filter.

## Root Cause

**Source**: `services/lambda/kds-consumer/lib/utils.ts:40` and `lib/message.ts:138-139`

The validation flow:
1. kds-consumer processes Kinesis records (Kakao Alimtalk, Friendtalk, or Brand Message campaigns)
2. `isValidSenderInfoForCampaign()` checks if `projectMetadata.kakaoSenderInfo` exists
3. If missing → `console.error("kakao sender info is not provided for project ${projectID}")`
4. If validation fails → `console.warn("Invalid sender info for campaign. projectID: ${projectId}")`
5. Lambda skips the message (returns early) but ERROR log already fired

## Why This Happens

**Two preconditions must be true**:

1. **Campaign exists in Postgres** with `channel = 'kakao-alimtalk' | 'kakao-friendtalk' | 'kakao-brand-message'` and `status = 1` (active)
2. **DynamoDB project table has null/missing `kakaoSenderInfo`** (not configured in web console or via API)

If campaign is in Kinesis but sender info is not in DynamoDB, the error fires.

## Investigation Recipe

### Step 1: Verify campaign existence

```bash
# Replace <project_id> with actual ID
PROJECT_ID="95db6690110b55609aa86bbf442ef1b7"
TABLE="campaigns_${PROJECT_ID}"

aws rds-data execute-statement \
  --resource-arn "arn:aws:rds:ap-northeast-2:702197142747:cluster:notifly-db-prod-cluster" \
  --secret-arn "arn:aws:secretsmanager:ap-northeast-2:702197142747:secret:..." \
  --database "notifly_db" \
  --sql "SELECT id, channel, status, created_at FROM ${TABLE} WHERE channel LIKE 'kakao%' ORDER BY updated_at DESC LIMIT 10"
```

Or via Python:
```python
import psycopg2
conn = psycopg2.connect(host=os.environ['POSTGRES_HOST'], ...)
cur = conn.cursor()
cur.execute(f"SELECT id, channel, status FROM campaigns_{project_id} WHERE channel LIKE 'kakao%'")
print(cur.fetchall())
```

**Expected output if error is real**: At least one row with `channel = 'kakao-alimtalk' | 'kakao-friendtalk' | 'kakao-brand-message'` and `status = 1`.

### Step 2: Check DynamoDB project configuration

```bash
PROJECT_ID="95db6690110b55609aa86bbf442ef1b7"

aws dynamodb get-item \
  --table-name project \
  --key "id={S,${PROJECT_ID}}" \
  --region ap-northeast-2 \
  --query 'Item.kakaoSenderInfo'
```

**Expected**:
- `null` → error is real (sender info not configured)
- Populated object → sender info is configured, error may be transient or campaign mismatch

### Step 3: Scope the campaign trigger

Extract `project_id` from log lines and check DynamoDB `project` table mapping:

```python
import boto3
dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-2')
project_table = dynamodb.Table('project')

response = project_table.get_item(Key={'id': project_id})
item = response.get('Item', {})
print(f"Project: {item.get('name')} (product_id: {item.get('product_id')})")
print(f"kakaoSenderInfo: {item.get('kakaoSenderInfo')}")
```

## Classification

**`no_action`** if:
- Campaign is test/staging only (project name suggests internal use, e.g., `michael`, `notifly-test`)
- Sender info is intentionally not configured (project does not use Kakao)
- Error volume is < 5/day and stable

**`needs_fix`** if:
- Campaign is production and active (`status = 1`) but sender info is missing
- Error spike correlates with new campaign creation
- Error volume is increasing day-over-day

**Remediation**:
1. Web console: Navigate to project settings → Kakao integration → add API keys (sender_key, app_key, secret_key)
2. Or: Deactivate the campaign (`UPDATE campaigns_<project_id> SET status = 0 WHERE id = '<campaign_id>'`)
3. Or: Delete the campaign if no longer needed

## Common Scenarios

### Scenario A: New campaign created but keys not yet configured

- User creates Kakao Alimtalk campaign in web console
- Saves campaign without filling in Kakao API keys
- Campaign immediately enters Kinesis event stream
- kds-consumer processes it and logs ERROR
- User gets alerted before they finish setup

**Fix**: User completes Kakao integration setup in web console.

### Scenario B: Kakao keys revoked or expired

- Project previously had valid `kakaoSenderInfo`
- External Kakao account was deleted or keys rotated
- DynamoDB still has stale/empty keys
- New campaigns inherit the invalid config

**Fix**: Re-authenticate with Kakao in web console or update DynamoDB `kakaoSenderInfo` field.

### Scenario C: Campaign left in draft or test state

- Campaign was created for testing but never deleted
- Status remains `1` in Postgres
- No one intends to send via Kakao

**Fix**: Delete the campaign or set `status = 0`.

## Code Locations

- Validation logic: `services/lambda/kds-consumer/lib/utils.ts:13-79` (function `isValidSenderInfoForCampaign`)
- Error logging: `services/lambda/kds-consumer/lib/message.ts:137-140`
- Kakao channel types: `packages/types/src/campaign.ts` (ChannelType enum)
- Test cases: `services/lambda/kds-consumer/test/lib/utils.spec.ts:200-205`

## Pitfall: Helper Logs Are Sanitized

The `check` helper returns `current_trigger_contexts` with sanitized project IDs and campaign IDs (shown as `<project_id>`, `<campaign_id>`). When the helper output suggests "project unknown", **always run a live DynamoDB + Postgres check** to confirm:

1. Whether the campaign actually exists
2. Whether `kakaoSenderInfo` is truly null or just not shown in the sanitized output

This pattern caught the storepick case: sanitized logs hid the actual campaign details, requiring direct DB inspection to reveal the real issue.
