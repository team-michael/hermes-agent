# CloudWatch Logs Insights `%pattern%` vs `filter-log-events` Syntax Mismatch

## Problem

CloudWatch Logs API offers two distinct query/filter interfaces with **incompatible pattern syntaxes**:

### Logs Insights (Query Language)
- Uses `%pattern%` for **substring matching** (case-insensitive)
- Example: `%[Ee][Rr][Rr][Oo][Rr]%` matches any case variation of "error"
- Used in:
  - Logs Insights query statements (via `logs.start_query()`)
  - CloudWatch metric filter definitions (via `put_metric_filter()`)
  - Terraform `aws_cloudwatch_log_metric_filter` `filter_pattern` field

### `filter-log-events` API
- Does NOT accept `%pattern%` syntax
- Uses either:
  - **Bare term**: `filterPattern='ERROR'` (word boundary match)
  - **Term list**: `filterPattern='[ERROR or WARN]'` (boolean OR/AND)
  - **Space-separated**: `filterPattern='[ERROR, ...error-related patterns...]'`
- Used in:
  - boto3 `logs.filter_log_events(filterPattern=...)`
  - AWS CLI `aws logs filter-log-events --filter-pattern`
- Matching is **stricter than substring**: bare `ERROR` requires word boundaries and does not match JSON substrings like `"title":"Error"` or `"level":"error"` in the same fuzzy way

## When This Breaks

**Real example from this session:**

1. Metric filter on log group `/aws/ecs/notifly-services-prod/web-console/sentry`:
   ```
   Pattern: %[Ee][Rr][Rr][Oo][Rr]%
   ```
   This catches every JSON payload containing `"title":"Error"`, `"level":"error"`, etc.

2. Investigation attempts to use the same pattern in `filter-log-events`:
   ```python
   logs.filter_log_events(
       logGroupName=log_group,
       startTime=start_time,
       endTime=end_time,
       filterPattern='%[Ee][Rr][Rr][Oo][Rr]%'  # ❌ WRONG
   )
   ```

3. Result: `InvalidParameterException: Invalid filter pattern`

## Remediation

### Option 1: Use Logs Insights (Recommended)

Logs Insights supports the same substring syntax and integrates seamlessly with JSON parsing:

```python
import boto3
import time

logs = boto3.client('logs', region_name='ap-northeast-2')

resp = logs.start_query(
    logGroupName='/aws/ecs/notifly-services-prod/web-console/sentry',
    startTime=int((datetime.utcnow() - timedelta(hours=1)).timestamp()),
    endTime=int(datetime.utcnow().timestamp()),
    queryString="""
    fields @timestamp, sentryAlert.issue.title, sentryAlert.issue.message
    | filter @message like /[Ee][Rr][Rr][Oo][Rr]/
    | stats count() as total by sentryAlert.issue.title
    """
)

query_id = resp['queryId']

# Wait for query completion
while True:
    result = logs.get_query_results(queryId=query_id)
    if result['status'] in ['Complete', 'Failed']:
        break
    time.sleep(0.5)

for record in result['results']:
    print(record)
```

### Option 2: Use Unfiltered `filter-log-events`

Omit `filterPattern` entirely and parse manually:

```python
events = logs.filter_log_events(
    logGroupName=log_group,
    startTime=start_ms,
    endTime=end_ms
    # No filterPattern - returns ALL events
)

for event in events['events']:
    msg = event['message']
    # Manual check for ERROR pattern
    if 'Error' in msg or 'error' in msg or 'ERROR' in msg:
        # Process
        pass
```

### Option 3: Use Simplified Bare-Term Pattern

Use a simpler `filterPattern` but accept false positives/negatives:

```python
events = logs.filter_log_events(
    logGroupName=log_group,
    startTime=start_ms,
    endTime=end_ms,
    filterPattern='ERROR'  # Bare term - less precise than %pattern%
)
```

**Note**: This may match fewer events than the metric filter because term matching is stricter. JSON substrings like `"level":"error"` within a sentence may not match a bare `ERROR` term.

## Best Practice for Alert Investigations

When the metric filter uses `%pattern%` syntax (common in Terraform-generated alarms):

1. **Prefer Logs Insights** for:
   - JSON payload parsing and field extraction
   - Aggregate counts and grouping
   - Complex filters and boolean logic
   - Structured analysis before final report

2. Use `filter-log-events` **only for**:
   - Real-time log streaming (Logs Insights has latency)
   - Single-event inspection in small time windows
   - When you need raw `nextToken` pagination control

3. **Never copy the metric filter pattern directly** to `filter-log-events` — always translate to Logs Insights or use an unfiltered call.

## References in This Skill

- `references/sentry-email-alert-pipeline-false-positives.md` — Sentry alarm investigation includes Logs Insights query examples and the specific pitfall of `%[Ee][Rr][Rr][Oo][Rr]%` metric filters.
- `references/ecs-log-manual-trace.md` — Generic ECS console error triage; includes both Logs Insights and `filter-log-events` recipes with proper syntax.
