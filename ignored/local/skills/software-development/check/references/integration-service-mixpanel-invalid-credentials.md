# Integration Service Mixpanel/Amplitude Invalid Credentials Diagnosis

## Pattern

Console ERROR logs from `/aws/ecs/notifly-services-prod/integration-service`:
```
[eventLoopGroupProxy-N-M] WARN ktor.application -- [POST /mixpanel/projects/{projectId}/cohorts] Failure: message=Invalid credentials
```

Alarm: `integration-service-prod console error` (ConsoleErrors metric filter `%ERROR%`)

## Root Cause Analysis

The `CallExtensions.authenticateProject()` function (line 23-46 of `CallExtensions.kt`) validates every request:

```kotlin
fun authenticateProject(project: Project?, request: ApplicationRequest) {
    val authorizationHeader: String? = request.headers["Authorization"]
    val cognitoApiAuthAccessKey = project?.cognitoApiAuth?.username
    val cognitoApiAuthSecretKey = project?.cognitoApiAuth?.password

    if (accessKey != cognitoApiAuthAccessKey || secretKey != cognitoApiAuthSecretKey) {
        throw ServerException(HttpStatusCode.Unauthorized, "Invalid credentials")
    }
}
```

**"Invalid credentials" = Authorization header mismatch with DynamoDB `project.cognitoApiAuth`**

### Two possible root causes:

1. **Client sends wrong credentials** (Mixpanel/Amplitude client configuration error)
2. **Server-side credentials are stale** (DynamoDB `cognitoApiAuth` was recently rotated but client not updated)

## Diagnostic Steps

### Step 1: Confirm the error is authentication-level, not downstream

```bash
# Check alarm window for exact error message pattern
aws logs filter-log-events \
  --log-group-name '/aws/ecs/notifly-services-prod/integration-service' \
  --start-time $(date -d '2026-06-16 05:20:00 UTC' +%s)000 \
  --end-time $(date -d '2026-06-16 05:40:00 UTC' +%s)000 \
  --filter-pattern 'Invalid credentials' \
  --region ap-northeast-2
```

Expected output: `ServerException: Invalid credentials` stack traces at the exact alarm-window time.

**If found → authentication is the root cause. Proceed to Step 2.**
**If not found → the error is elsewhere (check DB/Redis/dependency errors instead).**

### Step 2: Extract project ID and verify stored credentials

From the error log line, extract `projectId={projectId}`. Then query DynamoDB:

```bash
# Get stored credentials
python - <<'PY'
import boto3
dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-2')
project_table = dynamodb.Table('project')
resp = project_table.get_item(Key={'id': '<projectId>'})
item = resp.get('Item', {})
auth = item.get('cognito_api_auth', {})
print(f"Stored username: {auth.get('username')}")
print(f"Stored password: {auth.get('password')}")
PY
```

### Step 3: Identify which end has the wrong credential

**If DynamoDB has `cognito_api_auth`** (the stored credential exists):
- Ask the **client** (Mixpanel, Amplitude, or whoever is calling integration-service) to verify they are sending the exact username/password above in their Authorization Basic Auth header.
- Check whether the credential was recently rotated in DynamoDB — if so, the client config may not have been updated.

**If DynamoDB does NOT have `cognito_api_auth`** (null or missing):
- The error is `"Auth credentials not configured for this project"` (line 40), not `"Invalid credentials"` (line 44).
- If you see "Invalid credentials" + no DynamoDB credential, there is a code-level bug or deployment issue — investigate immediately.

### Step 4: Check alarm recurrence and scope

```bash
# Count alarms per day (7d window)
aws cloudwatch describe-alarm-history \
  --alarm-name 'integration-service-prod console error' \
  --history-item-type StateUpdate \
  --start-date 2026-06-09T00:00:00Z \
  --end-date 2026-06-16T23:59:59Z \
  --region ap-northeast-2 \
  --query 'AlarmHistoryItems[].Timestamp' \
  | jq -r '.[] | split("T")[0]' | sort | uniq -c
```

- **Daily recurrence at the same time** → scheduled integration job from client side (e.g., daily cohort sync), client credential config is stale
- **Sporadic/random** → likely a transient client-side network error or client app bug
- **Single spike** → possible credential rotation not propagated to client

## Common Scenarios

### Scenario A: class101 project, `add_members` action fails

**Evidence:**
- All ERROR logs contain `action=add_members, projectId=b2b4a8f879a75673b755bff42fc1deb6`
- 50+ errors in a 10-minute window
- Alarm fires once for that window

**Diagnosis:**
1. Check `project.cognito_api_auth` in DynamoDB — if present, credentials are stored.
2. Contact class101: ask them to verify their Mixpanel API client is configured with:
   ```
   Authorization: Basic base64(username:password)
   ```
   where `username` and `password` match the DynamoDB stored values.

**Remediation (client-side):**
- Update Mixpanel client to use correct credentials
- If credentials were recently rotated in Notifly, update the client config and retry

**Remediation (server-side, if credential rotation is the cause):**
- If intentionally rotating credentials, coordinate with client teams on update timing
- Consider adding a grace period that accepts both old and new credentials during rotation

### Scenario B: Multiple projects affected, or new project not configured

- Check whether `cognito_api_auth` exists for all projects that are calling integration-service
- For new projects, ensure onboarding process creates `cognito_api_auth` in DynamoDB before handing credentials to client

## Classification

- **Status**: `no_action` if the client has confirmed they will update their credential config and retry
- **Status**: `needs_fix` if credentials were intentionally rotated on the server and client teams were not notified, or if a new project was not properly onboarded
- **Status**: `urgent` only if the integration is critical and multiple projects are affected

## Code References

- **Authentication logic**: `services/server/integration-service/src/main/kotlin/tech/notifly/integration/routes/CallExtensions.kt` (lines 23-46)
- **Mixpanel route**: `services/server/integration-service/src/main/kotlin/tech/notifly/integration/routes/Mixpanel.kt` (line 62, calls `authenticateProject`)
- **Amplitude route**: `services/server/integration-service/src/main/kotlin/tech/notifly/integration/routes/Amplitude.kt` (line 33, calls `authenticateProject`)
- **Project model**: `services/server/integration-service/src/main/kotlin/tech/notifly/integration/models/Project.kt` (field `cognitoApiAuth`)
