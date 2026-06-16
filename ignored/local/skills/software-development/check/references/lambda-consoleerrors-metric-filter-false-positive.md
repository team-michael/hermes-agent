# Lambda ConsoleErrors Metric Filter False Positives

## Pattern: Metric Incremented Despite All INFO Logs and Successful Invocations

### Observed Signature

Alarm: `<lambda-name> lambda error` (namespace `ConsoleErrors`)
Metric filter pattern: `%ERROR|Status: timeout%`
Current alarm window logs: all INFO level, all invocations complete successfully with normal Duration
Alarm datapoint: 1.0 (single increment)

**Expected behavior**: metric does not increment if no ERROR or timeout text exists in logs.
**Actual behavior**: metric increments to 1.0 anyway.

### Root Causes

1. **Log ingestion lag on metric filter evaluation**: CloudWatch Logs metric filters run asynchronously and may index/match logs after the Lambda invocation completes. If a prior deployment left ERROR log lines in the stream (e.g., a crashed invocation from an earlier version), the metric filter may match those retroactively and increment during a fresh OK→ALARM datapoint window even when current invocations are INFO-only.

2. **Metric filter pattern overly broad**: A filter like `%ERROR%` will match literal `"ERROR"` strings embedded in JSON payloads, HTTP access logs, or concatenated text, even when the semantic "error condition" did not occur (e.g., `"status":"ERROR_RETRY"`, `"templateName":"service_error"`). Combined with log-level downgrade (e.g., WARN was changed to INFO recently), old INFO lines may match and old ERROR lines may linger.

3. **Concurrent log stream race**: Multiple Lambda invocations run in parallel. One stream may still be writing old-format logs while another emits new-format INFO logs. The metric filter sees both, increments on the old logs, and the alarm fires even though the current invocation is clean.

4. **Metric filter config drift**: The filter pattern in `describe_metric_filters` may have been updated (e.g., corrected from `%ERROR%` to a more specific pattern), but the old metric `ConsoleErrors: <name>` continues to receive data from the filter before the config change took effect in indexing.

### Triage Steps

#### Step 1: Verify Lambda runtime health
```bash
aws lambda get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=<function> \
  --start-time 2026-06-15T23:44:00Z \
  --end-time 2026-06-15T23:54:00Z \
  --period 300 \
  --statistics Sum \
  --region ap-northeast-2
```
If `Sum == 0`, the Lambda did not crash. The ERROR log line did not come from an unhandled exception.

#### Step 2: Verify Lambda timeout/duration
```bash
aws lambda get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Duration \
  --dimensions Name=FunctionName,Value=<function> \
  --start-time 2026-06-15T23:44:00Z \
  --end-time 2026-06-15T23:54:00Z \
  --period 300 \
  --statistics Maximum \
  --region ap-northeast-2
```
If `Maximum < Timeout`, no timeout occurred. The `Status: timeout` pattern did not fire.

#### Step 3: Inspect actual log content in alarm window
```bash
aws logs get-log-events \
  --log-group-name /aws/lambda/<function> \
  --log-stream-name '<stream>' \
  --start-time 1781567400000 \
  --end-time 1781567700000 \
  --start-from-head
```
Search output for literal `ERROR` or `timeout` strings. If none exist, metric filter matched old logs from a prior stream or a different invocation batch.

#### Step 4: Check log levels and recent deployment
```bash
git log --oneline -20 -- packages/lambda/<name>/
git show <commit>:packages/lambda/<name>/index.ts | grep console.error | head -5
```
Did a recent commit add `console.error` calls, or downgrade a log level from INFO to WARN and leave old ERROR lines behind?

#### Step 5: Compare 7d/30d trend
```bash
aws cloudwatch get-metric-statistics \
  --namespace ConsoleErrors \
  --metric-name '<alarm>' \
  --start-time $(date -u -d '30 days ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 86400 \
  --statistics Sum
```
If `Sum` is 0 on most days and only 1–2 spikes occur, and those spikes do not correlate with known deployments or traffic patterns, the alarm is likely benign noise driven by log-indexing lag or metric-filter transience.

### Classification

**Classify as `no_action` when all of the following hold**:
1. AWS/Lambda `Errors` metric = 0 in the alarm window
2. AWS/Lambda `Duration` < `Timeout` in the alarm window
3. Actual log stream content shows no ERROR or timeout text
4. 7d/30d trend is sparse (< 2 increments/week) with no correlation to deployments
5. SQS DLQ (if applicable) shows zero messages or messages from prior invocation batches

**Classify as `needs_fix` if**:
- ErrorMetric > 0 despite INFO-only logs (indicates Lambda is crashing but logs are not captured correctly)
- Duration spikes to near Timeout but `%Status: timeout%` never appears (indicates `Status: timeout` was not logged, or the log format changed)
- 7d trend shows worsening recurrence (growing frequency or magnitude)
- Deployment correlates with alarm onset and ERROR lines are new

### Session Example: scheduled-batch-kakao-alimtalk-delivery

**Observation**: Alarm fired 2026-06-15 23:54 UTC (KST 06-16 08:54), metric = 1.0.

**Triage**:
1. AWS/Lambda Errors = 0 for the hour ✓
2. AWS/Lambda Duration = 40–100 ms, Timeout = 900 s ✓
3. Actual logs in window: all INFO, all show "Received event from SQS: {project_id: ..., campaign_id: ..., ...}" ✓
4. 7d trend: 2 days with 1 spike each (6/10, 6/14), today 1 spike → very sparse ✓
5. No SQS DLQ (Lambda consumes SQS batch successfully) ✓

**Result**: False positive. Metric filter matched old logs from prior stream or indexing lag. No action needed.

### Prevention

1. **Downgrade log level before removing log line**: When you want to stop logging something at ERROR, downgrade to INFO/DEBUG first and let the old ERROR logs age out (retention period, typically 7d). Then remove the log statement in the next deployment.
2. **Use structured log levels**: Avoid `console.error()` for expected failures. Use `console.warn()` for handled business logic that fails gracefully, `console.error()` only for unhandled exceptions or infrastructure failures.
3. **Make metric filter pattern specific**: Avoid bare `%ERROR%`. Use `%"ERROR"|"error"|"ERROR_"% || %"Status: timeout"%` or log structured JSON with explicit `level: "error"` fields.
4. **Monitor metric-filter config drift**: After updating a filter pattern, verify the old metric is no longer incremented by checking a few hours of data post-deployment. If the old metric continues to increment, CloudWatch may not have propagated the change — escalate to AWS support or recreate the filter.

## See Also

- `scheduled-batch-delivery-dbinsert-json-serialization-bug.md` (real ERROR in logs vs false positive)
- `lambda-consoleerrors-handled-business-rejection.md` (comprehensive index of safe-to-ignore ERROR patterns)
- `segment-publisher-slow-eic-query-noise.md` (metric filter overly broad, multiple patterns caught)
