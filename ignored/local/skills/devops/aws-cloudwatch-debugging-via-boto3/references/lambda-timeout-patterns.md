# Lambda Timeout Patterns

Use this skill when investigating CloudWatch alarms for Lambda timeouts, particularly in the `ConsoleErrors` namespace with `%ERROR|Status: timeout%` metric filters, or when a Lambda invocation reports `REPORT ... Duration: 900000.00 ms Status: timeout`.

## Quick Diagnosis

Three common Lambda timeout roots:

1. **SQS batch + maxReceiveCount=1 → DLQ amplification**: Entire batch routed to DLQ on first timeout, no retries
2. **S3 multipart upload bottleneck**: Large file uploads stall in final chunks
3. **Database query timeout**: Read-heavy or write-heavy operations exceed statement_timeout

## Pattern: SQS Batch Timeout → DLQ Amplification

### Root Cause

When a Lambda with `EventSourceMapping.BatchSize > 1` times out and the SQS queue has `maxReceiveCount: 1`:
- All messages in that batch are immediately routed to DLQ with zero retries
- Single timeout affects `BatchSize × RecipientCount` (or messages) at once
- Example: 10-message batch, 50 recipients each = ~500 undelivered items from one 900s timeout

### Evidence Signature

```
INFO Processing batch [part 1 / part 2 / ...]
[10+ minutes of normal work logs]
REPORT RequestId: <uuid> Duration: 900000.00 ms Billed Duration: 901000 ms Status: timeout
```

Verify with SQS metrics:
- DLQ `ApproximateNumberOfMessagesVisible` increases by ~`BatchSize` within 60s
- Main queue `NumberOfMessagesDeleted` drops to zero during timeout window

### Triage Steps

**Step 1: Get EventSourceMapping config**
```bash
aws lambda list-event-source-mappings \
  --function-name <lambda-name> \
  --region ap-northeast-2 \
  --query 'EventSourceMappings[0].[BatchSize,MaximumConcurrency,State]'
```

**Step 2: Get queue redrive policy**
```bash
aws sqs get-queue-attributes \
  --queue-url '<queue-url>' \
  --attribute-names All \
  --region ap-northeast-2 \
  --query 'Attributes.RedrivePolicy'
```
If `maxReceiveCount: 1` → zero retries on failure.

**Step 3: Extract scope from DLQ message bodies**
```bash
aws sqs receive-message \
  --queue-url '<dlq-url>' \
  --region ap-northeast-2 \
  --max-number-of-messages 10 \
  --query 'Messages[].Body' \
  --output text | jq -r '. | fromjson? | {projectId, campaignId, type}'
```

**Step 4: Check Lambda runtime metrics during window**
```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=<lambda-name> \
  --start-time '<alarm-window-start>' \
  --end-time '<alarm-window-end>' \
  --period 60 \
  --statistics Sum
```
If `Errors > 0`, Lambda crashed (code bug). If `Errors = 0`, timeout was graceful (hit wall, not exception).

### Classification

- **Transient spike, already recovered:** `no_action`
  - Single timeout, metrics normal before/after
  - `maxReceiveCount=1` means no silent loss (we know it went to DLQ)
  - DLQ can be manually re-driven if needed

- **Sustained or recurring:** `needs_fix`
  - Multiple timeouts within 10 minutes
  - Pattern suggests consistent load or provider latency issue
  - Needs either: longer timeout, lower `BatchSize`, higher `MaximumConcurrency`, or provider-specific tuning

### Remediation

**Immediate (threshold-only):**
```hcl
# infra/terraform/<region>/lambda/functions.tf
"<lambda_name>" = {
  timeout = 1200  # Increase from 900 to 1200 seconds
}
```

**Medium-term (reduce per-invocation load):**
- Lower `BatchSize` in EventSourceMapping (reduces messages per invocation)
- Increase `MaximumConcurrency` (more concurrent invocations, less backpressure)

**Long-term (structural safety):**
```hcl
# Increase maxReceiveCount to 2–3 so transient failures retry
redrive_policy = {
  max_receive_count = 3  # Was 1
}
```
With `maxReceiveCount=1`, ANY transient failure (provider timeout, network blip) causes unrecoverable data loss. With `maxReceiveCount=3`, transient failures retry; only persistent failures hit DLQ.

## Pattern: S3 Multipart Upload Bottleneck

### Root Cause

Large file exports (CSV, JSON, bulk data) use S3 multipart upload. When row count exceeds ~50K–100K and each part is 5MB+:
- Individual `UploadPart` calls take 2–10 seconds
- `CompleteMultipartUpload` on final part may hang
- Network latency or S3 throttling in final chunks → exceeds remaining timeout window

### Evidence Signature

```
INFO Retrieved 50000+ users from the database.
INFO Processing batch of size 10000.
INFO Processing batch of size 10000.
...
INFO ====Uploaded part 1====
INFO ====Uploaded part 2====
...
INFO ====Uploaded part 45====
(>14 min elapsed)
REPORT RequestId: <uuid> Duration: 900000.00 ms Status: timeout
```

Uploading part N takes time proportional to part size and network latency. If each part takes ~12s and you have 50 parts = 600s + overhead → timeout.

### Triage Steps

**Step 1: Extract row count from logs**
```bash
aws logs filter-log-events \
  --log-group-name /aws/lambda/<lambda-name> \
  --start-time <alarm-start-ms> \
  --end-time <alarm-end-ms> \
  --filter-pattern 'Retrieved * users' \
  --region ap-northeast-2 \
  --query 'events[0].message'
```

**Step 2: Extract batch/part timestamps**
```bash
aws logs filter-log-events \
  --log-group-name /aws/lambda/<lambda-name> \
  --start-time <alarm-start-ms> \
  --end-time <alarm-end-ms> \
  --filter-pattern 'Uploaded part' \
  --region ap-northeast-2 \
  --query 'events[].message' | jq -r '. | match("Uploaded part \\d+"; "g").string' | wc -l
```
Count final uploaded parts to estimate throughput.

**Step 3: Check S3 bucket region**
```bash
aws s3api head-bucket \
  --bucket <bucket-name> \
  --region ap-northeast-2
```
Must match Lambda region. Cross-region uploads add 50+ ms per request.

### Classification

- **Isolated spike, < 100K rows:** `no_action`
  - Single occurrence, not part of recurring load pattern
  - Export completed or failed gracefully (DLQ or dead letter path)

- **Recurring large exports:** `needs_fix`
  - Pattern suggests predictable data volume
  - Needs either: increase timeout, optimize batch serialization, or split large exports into multiple parts

### Remediation

**Immediate:**
```hcl
"<lambda_name>" = {
  timeout = 1200  # 20 min instead of 15 min
}
```

**Medium-term (optimize I/O):**
- Reduce CSV column count (project only necessary fields)
- Batch write to S3 in streaming fashion instead of buffering all rows
- Use S3 Select or Kinesis Firehose for massive exports instead of multipart

**Long-term:**
- Detect large exports before processing (~100K row threshold)
- Split into multiple SQS messages (hash-range segmentation)
- Recombine at client side (web-console) or provide per-segment downloads

## Pattern: Early DynamoDB/External Dependency Lookup Failure

### Root Cause

Lambda invocation fails in initialization before any work is queued or batched. DynamoDB `GetItem` call returns null, external API returns 404, or environment variable is missing. Because failure is immediate (~ms), Lambda catches it, logs ERROR, then exits normally (`Errors=0` in AWS/Lambda namespace). The `%ERROR|Status: timeout%` metric filter catches the ERROR text but Lambda never actually times out — the alarm fires due to ERROR log volume, not timeout. Example: `user-csv-mailer` queries `user_property_fields` table before processing — if projectId is unregistered, DynamoDB returns null and "No such project" error fires immediately.

### Evidence Signature

```
START RequestId: <uuid> Version: $LATEST
<timestamp> <uuid> INFO Received event: { "Records": [ { "body": "{...\"projectId\":\"tourlive\"...}" } ] }
<timestamp> <uuid> ERROR Invoke Error {"errorType":"Error","errorMessage":"No such project","stack":[...,"/var/task/lib/ddb.js:18:15",...]}
END RequestId: <uuid>
REPORT RequestId: <uuid> Duration: 38.29 ms Billed Duration: 39 ms Memory Size: 10240 MB Max Memory Used: 3633 MB
```

**Key difference from true timeout:**
- `Duration: 38.29 ms` (not 900000.00 ms)
- `Errors: 0` in AWS/Lambda metrics (Lambda caught the exception)
- ERROR log is early in invocation (within first few ms of parsing/init)

### Triage Steps

**Step 1: Check Lambda runtime metrics**
```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Duration \
  --dimensions Name=FunctionName,Value=<lambda-name> \
  --start-time '<alarm-window-start>' \
  --end-time '<alarm-window-end>' \
  --period 60 \
  --statistics Maximum \
  --region ap-northeast-2
```
If `Maximum: <1000 ms`, alarm is not a true timeout — it's high ERROR volume on fast exits.

**Step 2: Examine actual ERROR logs**
```bash
aws logs filter-log-events \
  --log-group-name /aws/lambda/<lambda-name> \
  --start-time <alarm-window-start-ms> \
  --end-time <alarm-window-end-ms> \
  --filter-pattern 'ERROR' \
  --region ap-northeast-2 \
  --query 'events[0:3].message'
```
Look for patterns like:
- `\"errorMessage\":\"No such project\"` → unregistered projectId
- `\"errorMessage\":\"ENOENT: no such file\"` → missing config/env
- `404 Not Found` → external API lookup failed
- `ECONNREFUSED` → dependency unreachable

**Step 3: Extract root cause from SQS payload**
If the error indicates unregistered scope (projectId, campaignId, etc.):
```bash
# Read the Received event log
aws logs filter-log-events \
  --log-group-name /aws/lambda/<lambda-name> \
  --log-stream-name '<stream_from_error>' \
  --filter-pattern 'Received event' \
  --region ap-northeast-2 \
  --query 'events[0].message'

# Parse to extract projectId, campaignId, etc.
```

### Classification

- **Malformed/test data once or twice:** `no_action`
  - Single CSV export request with unregistered projectId (test data)
  - No customer impact; request was rejected before any work
  - DLQ entry (if maxReceiveCount=1) is a single message, not a cascade

- **High spike of malformed requests:** `needs_fix`
  - 10+ malformed requests per hour
  - Suggests SQS message enqueue validation is broken
  - Source: web console, batch script, or external API sending bad data
  - Fix: validate scope before enqueuing SQS message (e.g., check `user_property_fields` table for projectId)

- **Systematic external dependency failure:** `needs_fix`
  - External API (e.g., Auth service, Config service) returns 404 or timeout for all/most calls
  - Lambda cannot proceed → high ERROR volume with fast exits
  - Fix: check dependency health, credentials, or configuration

### Remediation

**For unregistered scope (projectId, campaignId, etc.):**

Update the enqueue endpoint (e.g., web-console CSV export form) to validate scope before SQS enqueue:

```typescript
// Before enqueueing message
const userProps = await dynamodb.getItem({
    TableName: 'user_property_fields',
    Key: { project_id: projectId },
});
if (!userProps.Item) {
    throw new BadRequestError(
        `Project ${projectId} not registered for CSV export`
    );
}
```

**For external dependency failures:**

1. Check external service status / health endpoint
2. Verify credentials (e.g., API key, OAuth token) in Lambda environment
3. Review recent config changes in dependency (e.g., breaking API change, route removal)
4. Consider circuit-breaker pattern if external service is unstable (fail fast, re-queue after delay)

## Pattern: Database Read/Write Timeout

### Root Cause

Lambda queries PostgreSQL (especially sharded tables like `users_<project_id>`, `event_intermediate_counts_<project_id>`) with high concurrency or under Aurora recovery. Queries exceed `statement_timeout` (typically 240–300s).

**Read timeout sources:**
- Large full-table scans (missing index)
- Aurora reader replica recovery conflict (`canceling statement due to conflict with recovery`)
- High concurrent load from batch processing

**Write timeout sources:**
- `delivery_result_<project_id>` INSERT batch size too large
- DB connection pool exhausted
- Long-running transaction block

### Evidence Signature

```
ERROR Query read timeout after 240000ms for <sql-query>
ERROR canceling statement due to conflict with recovery
(logs from pg client retry loop)
[no ERROR lines from handler → exception caught]
REPORT RequestId: <uuid> Duration: 600000.00 ms Status: timeout
```

Note: Lambda timeout (900s) ≠ DB timeout (240s). If Lambda `Duration` is near a multiple of statement_timeout (240, 480, 720), the DB hit the wall first and Lambda's retry loop consumed the rest.

### Triage Steps

**Step 1: Check Lambda error metrics**
```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=<lambda-name> \
  --start-time '<window-start>' \
  --end-time '<window-end>' \
  --period 60 \
  --statistics Sum \
  --region ap-northeast-2
```
If `Errors > 0`, invocation crashed (timeout was runtime error, not graceful). If `Errors = 0`, Lambda caught the DB timeout and retried until timeout.

**Step 2: Extract DB query from logs**
```bash
aws logs filter-log-events \
  --log-group-name /aws/lambda/<lambda-name> \
  --start-time <window-start-ms> \
  --end-time <window-end-ms> \
  --filter-pattern 'timeout' \
  --region ap-northeast-2 \
  --query 'events[].message' | jq -r '. | select(contains("SELECT") or contains("INSERT"))' | head -1
```
Identify table suffix (`_<project_id>`) for scope attribution.

**Step 3: Check RDS performance metrics**
```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/RDS \
  --metric-name DatabaseConnections \
  --dimensions Name=DBInstanceIdentifier,Value=<instance-name> \
  --start-time '<window-start>' \
  --end-time '<window-end>' \
  --period 60 \
  --statistics Average \
  --region ap-northeast-2
```

### Classification

- **Replica recovery conflict, transient:** `no_action`
  - Aurora reader recovering from failover
  - Queries get canceled once, retry succeeds
  - Pattern resolves within 5–10 minutes

- **Missing index on hot query:** `needs_fix`
  - Same query times out repeatedly
  - Run `EXPLAIN ANALYZE` on the query to identify missing index

- **High concurrent batch load:** `needs_fix`
  - Multiple Lambdas hitting same table simultaneously
  - May need DB scaling (larger instance) or application-level rate limiting

## Reference Implementations

### user-csv-mailer: Early DynamoDB Lookup Failure (Unregistered projectId)
See `references/lambda-timeout-patterns-user-csv-mailer-early-ddb-lookup-failure.md` in this skill.
- Alarm `user-csv-mailer lambda error` fires from early `"No such project"` errors, NOT timeouts
- Duration is ~30–50 ms, not 900s; Lambda catches exception and exits cleanly
- Root cause: unregistered projectId in SQS message (test/demo data or web-console validation gap)
- Triage: check if projectId exists in `user_property_fields` table; if not, validate at enqueue time

### user-csv-mailer (S3 multipart + large exports)
See `references/user-csv-mailer-timeout-s3-multipart.md` in the `check` skill.
- ~8900+ user CSV exports frequently hit 900s timeout
- Root cause: S3 multipart upload on final parts takes 10+ seconds each
- Mitigation: increase timeout to 1200s; medium-term: stream/batch optimization

### email-delivery, scheduled-batch-delivery (SQS batch + provider latency)
See `references/scheduled-batch-delivery-fcm-latency.md` in the `check` skill.
- FCM send batches timeout under high provider latency
- `maxReceiveCount=1` causes entire batch to DLQ on first timeout
- Mitigation: increase timeout; long-term: increase `maxReceiveCount` to 3

### kds-consumer (DB read timeout from replica conflict)
See `references/rds-aurora-replica-recovery-conflict.md` in the `check` skill.
- Reader replica WAL conflicts cancel queries
- Transient pattern, usually recovers within 5 min

## Key Takeaways

1. **Always check EventSourceMapping + queue redrive policy** before assuming code bug. Structural misconfiguration (BatchSize too large, maxReceiveCount=1) is the root cause ~40% of the time.

2. **Timeout is not always a code bug**. Provider latency, network congestion, or infrastructure contention can cause graceful timeouts that retry cleanly.

3. **maxReceiveCount=1 is dangerous for batch Lambdas**. It guarantees unrecoverable loss on any transient failure. Strongly prefer `maxReceiveCount=2–3`.

4. **Current duration metrics must be inspected**. Log the final part timestamp or use Lambda `Duration` p99 metrics to diagnose whether timeout is load-driven (needs scaling) or infrastructure-driven (needs tuning).
