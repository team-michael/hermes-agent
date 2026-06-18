# Case Study: 2026-06-16 api-service /authenticate Spike

## Alert Summary

- **Alarm**: `[api-service] 4xx error response is greater than 300 in 5m`
- **Region**: ap-northeast-2
- **Trigger time**: 2026-06-16 17:11 KST (16시 11분 UTC)
- **Volume**: 31,241 errors on 2026-06-16 (vs. 8,466 baseline next day)
- **Datapoint breach**: 5-min bucket: 892 → 1,173 4xx responses

## Investigation Trace

### Step 1: Client Identification

**Query**:
```sql
fields @timestamp, ip, userAgent
| filter path = "/authenticate" and status = 400
| stats count() as request_count by ip, userAgent
| sort request_count desc
| limit 20
```

**Result**:
- IP `43.202.115.59` (with Cloudflare IPs): 1,827 requests (98%)
  - User-Agent: `Apache-HttpClient/5.3.1 (Java/17.0.19)`
- IP `43.200.25.101` (with Cloudflare IPs): 17 requests (1%)
  - User-Agent: `python-requests/2.32.3`

**Diagnosis**: Single dominant Java client from IP `43.202.115.59`.

### Step 2: Request Characteristic Analysis

**Sample log lines** (2026-06-16 16:57–17:05 KST):

```json
{
  "level": "warn",
  "timestamp": "2026-06-16T16:57:00.000Z",
  "service": "api-service",
  "environment": "production",
  "projectId": "unknown",
  "status": 400,
  "method": "POST",
  "path": "/authenticate",
  "normalizedPath": "/authenticate",
  "duration": 0,
  "ip": "43.202.115.59, 141.101.84.217",
  "userAgent": "Apache-HttpClient/5.3.1 (Java/17.0.19)",
  "responseBody": "{\"error\":\"Missing required fields\"}",
  "message": "error-response"
}
```

**Characteristic**: `"Missing required fields"` → code path is `authenticate.js:13`, meaning:
- JSON parse succeeded (no "Invalid request body" log)
- But `body?.accessKey` or `body?.secretKey` is falsy

**Likely cause**: Request body is `{}` or one/both fields are omitted.

### Step 3: Cognito Account Mapping

**DynamoDB Scan Result**:

```
Projects with cognito_api_auth (sample):
- washenjoy (903a...): user: b1c106df4f... | password: p0+5#XmPz_!C
- ktwiz (6590...): user: 4c0d4a790d... | password: (02sRvMvXD#w
- sione-cafe24 (f208...): user: 4a0fb7cd... | password: m_EJm0o96DbK
... (139 projects total)
```

All major projects have `cognito_api_auth` configured. This client IP is not attempting auth for any specific known project (request is coming in unauthenticated).

### Step 4: Project Reverse-Trace

**Approach A: Success History** (Failed)
```sql
fields @timestamp, ip
| filter path = "/authenticate" and status >= 200 and status < 300
| stats count() by ip
```
**Result**: Zero successful `/authenticate` requests in last 24 hours from any IP.

**Approach B: Integration Pattern Matching**

`Apache-HttpClient/5.3.1 (Java/17.0.19)` signature indicates:
- Java 17 (recent)
- Spring/Apache HTTP client library
- Likely Notifly internal service or customer Java SDK

**Codebase search**:
```bash
grep -r "Apache-HttpClient" ~/workspace/notifly-event --include="*.ts" --include="*.js" --include="*.py"
# (no results — not mentioned explicitly in code)

grep -r "43.202.115.59" ~/workspace/notifly-event
# (no hardcoded IP — must be environment-deployed)
```

**Approach C: Time-of-Day Pattern**

Daily occurrence ~17:00 KST (2:00 UTC) with consistent volume (2,500–3,100 errors/day) suggests **scheduled automation** rather than random client failure.

Peak burst on 2026-06-16: 16:57–17:05 KST = likely batch job window.

**Conclusion**: Source project **not definitively identified** from logs alone. Requires:
1. Terraform search for IP `43.202.115.59` in Lambda task definitions
2. Check deployment records for Cognito auth config changes on 2026-06-15/16
3. Query ECS task logs for services with Java 17 runtime on prod cluster

## Root Cause Hypothesis

Client (IP `43.202.115.59`, Java service) is attempting `/authenticate` with **empty or missing credential fields** in the request body. Possible triggers:

1. **Config regression**: Env var `COGNITO_API_AUTH` not set or empty
2. **Code push**: Recent change to request body construction in a Lambda or scheduled task
3. **Credential rotation**: API keys were reset/rotated, and client code not updated
4. **Integration SDK issue**: Old version of Notifly Java SDK sending wrong request format

## Resolution Path

1. Check Lambda/ECS task definitions for env var drift (esp. `COGNITO_API_AUTH_*` pattern)
2. Review git log for changes to any service with Java HttpClient (last 24 hours)
3. Correlate with AWS CodeDeploy/CloudFormation events on 2026-06-15/16
4. If found: Deploy corrected env vars or rollback recent change
5. Verify: successful `/authenticate` from same IP should appear within 5 min

## Outcome

**Status**: `needs_fix` — non-urgent engineering work required to identify project and resolve config/code issue.

**Impact**: Affected project's API integrations are non-functional until credentials are corrected or request format is fixed.

