# user-csv-mailer Lambda Timeout: S3 Multipart Upload Bottleneck

## Alert Pattern

Alarm: `user-csv-mailer lambda error`
Metric filter: `%ERROR|Status: timeout%`
Lambda timeout: 900 seconds (15 minutes)
Memory: 10240 MB

## Root Cause

`user-csv-mailer` Lambda generates CSV exports of user lists for campaigns/experiments/user journeys and uploads to S3 via multipart upload. When the CSV row count exceeds ~50,000–100,000 rows (depending on column width and network latency), the final multipart upload chunks take longer than the 900-second timeout to complete.

### Typical Flow

1. Receive SQS message with project/campaign/user journey metadata
2. Query PostgreSQL for matching users → `Retrieved 8900+ users` logs
3. Build CSV in memory → batch into 10,000-row chunks
4. For each chunk: upload to S3 via multipart upload (`Uploaded part N`)
5. **⚠️ Bottleneck**: Final part upload or CompleteMultipartUpload call hangs/delays beyond timeout

### Evidence Signature

```
INFO Retrieved 8904 users from the database.
INFO ====Uploaded part 1====
INFO ====Uploaded part 2====
...
INFO ====Uploaded part 49====
(no END/complete log → timeout at 900s)
REPORT RequestId: <uuid> Duration: 900000.00 ms Status: timeout
```

## Scope Attribution

Project/campaign scope is **not** directly extractable from the ERROR or REPORT lines. Use:

1. **SQS message payload** (if available in logs before error):
   - Look for `Received event:` line containing full `Records` array
   - Parse JSON to extract `projectId`, `campaignId` from message body
   - Pattern: `{ "Records": [ { "body": "{...\"projectId\":\"<id>\"...}" } ] }`

2. **S3 object metadata** (if multipart upload succeeded partway):
   - Check S3 bucket for partially uploaded objects matching request timestamp
   - Object key often contains project/campaign slugs or IDs

3. **Historical pattern matching**:
   - If multiple timeouts span 7+ days with same time-of-day (e.g. always ~02:00 KST), they likely share project scope
   - Check web-console logs for export request at matching timestamp to backtrack project

## Known Scenarios

### Scenario A: "No such project" (DynamoDB lookup failure)

**Trigger log:**
```
ERROR Invoke Error {"errorType":"Error","errorMessage":"No such project","stack":[...,"at getUserPropertyHeaders (/var/task/lib/ddb.js:18:15)",...]}
```

**Root cause**: DynamoDB `project` table lookup in `ddb.ts:getUserPropertyHeaders()` failed for the incoming `projectId`. This can mean:
- Project ID from SQS message is invalid/typo'd (e.g., test data)
- Project was soft-deleted but queue message was not cleaned
- DynamoDB query timeout (rare)

**Scope recovery**:
- Extract `projectId` from the SQS `Received event` log in the same invocation
- Attempt DynamoDB lookup directly: `aws dynamodb get-item --table-name project --key '{"id":{"S":"<projectId>"}}'`
- If not found → project is actually unknown/non-existent; scope should be marked "Unknown project"

**Classification**: Usually `no_action` (malformed request) unless recurrence spike suggests poisoned queue messages.

### Scenario B: S3 multipart upload timeout (15min elapsed)

**Trigger log:**
```
INFO Processing batch of size 10000.
...
INFO ====Uploaded part 49====
(>13min elapsed since "Retrieved users")
REPORT RequestId: <uuid> Duration: 900000.00 ms Status: timeout
```

**Root cause**: Large CSV generation + slow multipart upload. Typical row counts: 50K–200K+ users. Each part is ~5MB or more; network latency + S3 backpressure causes final chunks to exceed timeout window.

**Scope recovery**:
- Extract `projectId` from earliest `Received event` log
- Extract row count from `Retrieved X users` log → use as data volume proxy
- Check SQS message body for `campaignId`/`userJourneyId` if available
- Map `projectId` via DynamoDB `project` table

**Classification**: `needs_fix` (recurring data volume/throughput issue) unless isolated single spike.

## Triage Checklist

### Step 1: Identify current trigger

```bash
# Extract exact log line that crossed threshold
aws logs filter-log-events \
  --log-group-name /aws/lambda/user-csv-mailer \
  --start-time <alarm_transition_epoch_ms> \
  --end-time <alarm_transition_epoch_ms + 60000> \
  --filter-pattern 'REPORT' \
  --region ap-northeast-2
```

### Step 2: Determine error type

| Pattern | Type | Action |
|---------|------|--------|
| `ERROR Invoke Error ... "No such project"` | DynamoDB lookup failure | Extract projectId from SQS; verify exists |
| `REPORT ... Duration: 900000.00 ... Status: timeout` | Upload bottleneck | Extract row count + project from logs; analyze throughput |

### Step 3: Extract scope

```bash
# Read full SQS event from logs
aws logs filter-log-events \
  --log-group-name /aws/lambda/user-csv-mailer \
  --start-time <window_start> \
  --end-time <window_end> \
  --filter-pattern 'Received event' \
  --region ap-northeast-2
```

Parse the `Records[].body` JSON to extract:
- `projectId` → map via DynamoDB
- `campaignId` (if CAMPAIGN_METRIC_USER_LIST type)
- `userJourneyId` (if USER_JOURNEY_* type)

### Step 4: Assess recurrence

```bash
# Check last 30 days for same error pattern
aws cloudwatch describe-alarm-history \
  --alarm-name 'user-csv-mailer lambda error' \
  --start-date '2026-05-16' \
  --end-date '2026-06-16' \
  --region ap-northeast-2 \
  --query 'AlarmHistoryItems[?StateUpdateTime>`2026-05-16T00:00:00`].[Timestamp, StateUpdateTime]'
```

Daily counts from alarm history:
- If 1–2 occurrences spanning 30 days → isolated spike → `no_action` if recovered
- If 3+ occurrences in 7 days → recurring data volume issue → `needs_fix`
- If time-of-day pattern (always ~02:00 KST) → scheduled batch trigger → investigate batch size/concurrency

## Remediation

### Short-term (threshold-only)

Increase Lambda timeout from 900s → 1200s (20min) in Terraform:

```hcl
# infra/terraform/prod/ap-northeast-2/lambda/functions.tf

"user_csv_mailer" = {
  ...
  "timeout"      = 1200  # Increased from 900
  ...
}
```

### Medium-term (throughput optimization)

1. **Batch size tuning** (`index.ts` → `Promise.all(promises)`):
   - Current: one SQS record = one full user list
   - Option: chunk the user list query into smaller batches, upload separately
   - Measure: S3 upload throughput per part (current ~2–5 sec per part for large batches)

2. **Connection pooling** (`lib/ddb.ts`, `lib/db.ts`):
   - Verify read-only DB connection reuse is not exhausted
   - Check concurrent chunk processing vs. connection limits

3. **S3 configuration**:
   - Confirm S3 bucket region matches Lambda region (ap-northeast-2)
   - Check if bucket has any lifecycle policies slowing uploads

### Long-term (data volume management)

1. **Segment large exports**:
   - Detect >100K row estimates before processing
   - Split into multiple SQS messages (e.g., split by user attribute hash range)
   - Recombine at client side (web-console) or provide per-segment download

2. **Stream instead of batch**:
   - Consider Kinesis Firehose or S3 Select for large-scale exports
   - Avoid in-memory CSV buffering for >150K rows

## Related References

- `references/lambda-timeout-empty-log-gap.md` — Generic Lambda timeout diagnosis
- `references/scheduled-batch-delivery-dbinsert-json-serialization-bug.md` — DB write patterns in batch Lambdas
- `check/scripts/collect_notifly_alert_context.py` — Helper that extracts SQS payloads and scope

## Testing

**Local reproduction** (requires prod credentials):

```bash
# 1. Create test SQS message with large user list request
PAYLOAD='{"Records":[{"messageId":"test-1","body":"{\"type\":\"ALL_USER_LIST\",\"projectId\":\"<real_project>\",\"projectName\":\"<name>\",\"recipient\":\"test@example.com\"}"}]}'

# 2. Invoke Lambda locally (will attempt real DB + S3)
AWS_REGION=ap-northeast-2 \
  serverless invoke local --data "$PAYLOAD"

# 3. Monitor CloudWatch Logs for part upload times
aws logs tail /aws/lambda/user-csv-mailer --follow
```

**Expected result**: Should complete within timeout (or new timeout if adjusted); check Uploaded part timestamps for latency spikes.
