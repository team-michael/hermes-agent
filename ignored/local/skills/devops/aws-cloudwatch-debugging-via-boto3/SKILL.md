---
name: aws-cloudwatch-debugging-via-boto3
description: Investigate AWS alarms and related CloudWatch Logs using Python+boto3 when AWS CLI is unavailable or credentials only exist in shell env.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [aws, cloudwatch, boto3, debugging, alarms, logs]
---

# AWS CloudWatch Debugging via boto3

Use this when a user asks to investigate an AWS alarm from the agent environment, especially if:
- `aws` CLI is not installed
- credentials exist only in shell env vars
- you need alarm state/history plus correlated log evidence

## Key finding

In this environment:
- `aws` CLI may be missing
- `execute_code` may not inherit `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
- `terminal` does see shell env vars

So prefer **Python via `terminal`** and explicitly construct a boto3 `Session` from env vars.

## Workflow

Reference for setting up least-privilege Clix CloudWatch access from an agent/GitHub-OIDC environment: `references/clix-cloudwatch-readonly-access.md`.
Reference for noisy p95/p99/p99.9 alarm tuning: `references/noisy-percentile-alarm-tuning.md`.
Reference for Aurora/RDS reader fleet right-sizing and 3→2 reduction reviews: `references/rds-reader-rightsizing.md`.
Reference for `AuroraOptimizedReadsCacheHitRatio` alarms after broad PostgreSQL index backfills: `references/aurora-optimized-reads-cache-ratio-after-index-backfill.md`.
Reference for Notifly partner/security-audit checks about log integrity, S3 Versioning/Object Lock, CloudTrail validation, and Lambda-based automatic verification: `references/notifly-log-integrity-control-verification.md`.
Reference for ECS log-derived `ErrorCount` alarms caused by malformed/empty JSON request bodies, including Ktor/Jackson `No content to map due to end-of-input` cases: `references/ecs-log-derived-errorcount-malformed-request.md`.
Reference for Notifly Redis/ElastiCache cluster-mode ↔ Lambda investigations, including how to separate residual Redis warnings from actual Lambda timeout/SQS impact: `references/notifly-redis-lambda-cloudwatch-probes.md`.

1. **Check environment first**
   - `aws --version`
   - `env | grep '^AWS_' | sort`
   - confirm boto3 exists

2. **Create explicit boto3 session in terminal**

```python
import boto3, os
session = boto3.Session(
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    region_name=os.environ.get('AWS_DEFAULT_REGION', 'ap-northeast-2'),
)
```

3. **Confirm identity**
   - call STS `get_caller_identity()`
   - report account and ARN

4. **Find the alarm**
   - use `cloudwatch.describe_alarms()` with keyword filtering on `AlarmName`
   - capture:
     - `AlarmName`
     - `StateValue`
     - `StateReason`
     - `StateUpdatedTimestamp`
     - metric namespace/name
     - threshold/evaluation config
   - if the alarm is driven by a log-derived custom metric, also inspect the source log group's metric filters with `logs.describe_metric_filters()`
     - verify the actual `filterPattern`
     - do not assume the alarm name matches what the filter really captures
     - generic text filters can accidentally match multiple classes of warnings and pollute the alarm signal

5. **Pull alarm history**
   - use `describe_alarm_history(HistoryItemType='StateUpdate')`
   - identify exact `OK -> ALARM` timestamp and datapoint value

6. **Correlate CloudWatch Logs**
   - query the relevant log group around the alarm window using:
     - `filter_log_events` for tight windows
     - `start_query` + `get_query_results` for broader error scans
   - search for stack traces, 5xx requests, and repeated application errors

7. **Validate with metric datapoints**
   - use `get_metric_statistics()` or `get_metric_data()` on the alarm metric
   - list the exact datapoints that crossed threshold
   - match alarm transitions to datapoints
   - if this is an RDS cluster metric, also pull per-instance CPU for writer/readers to identify which instance actually caused the cluster alarm
   - for longer lookbacks, check retention before assuming 1-minute metric replay is available; in practice, alarm history may cover the full 30-day window while high-resolution/1-minute metric queries only return the most recent ~15 days, so use:
     - `describe_alarm_history()` for month-scale counts, start-time clustering, and ALARM-state durations
     - `get_metric_data()` for detailed minute-level reconstruction only where the datapoints are still retained

8. **When the user asks "when did this start?" find the first seen log + correlate to git/PR history**
   - use Logs Insights with `sort @timestamp asc | limit N` on the exact error string to find the earliest retained occurrence
   - if the user pasted a `@ptr` / log record pointer, call `logs.get_log_record()` to recover the exact event metadata; this is often more reliable than trying to re-fetch the same event with a narrow `get_log_events` window
   - be aware that very old absolute windows can fail with retention/creation-time errors even when a broad Logs Insights search succeeds; in that case, trust the broad ascending query result and the pointer metadata
   - once you have the earliest timestamp, inspect git history for the touched files first:
     - `git log --follow -- <path>` for the logging/config file
     - `git log --since <t0> --until <t1> -- <service-or-package>` for nearby service changes
   - if `gh` is unavailable, use the GitHub REST API directly with `GITHUB_TOKEN` from `~/.hermes/.env` to inspect PR titles, merge times, bodies, and changed files
   - separate three concepts explicitly in the final answer:
     1. **first observed time** in logs
     2. **direct enabling change** (for example cluster mode or client config)
     3. **surfacing change** that started exercising that path more heavily (for example a new service or cache callsite)
   - this distinction matters because many production bugs are latent configuration mismatches that only become visible after a later traffic or code-path shift

9. **When the user says "it increased recently" validate that statistically before assuming a new regression**
   - compute daily counts for the exact error over at least 14–30 days using Logs Insights `stats count(*) by bin(1d)`
   - compare:
     - recent 7 days vs prior 7 days
     - any obvious step-change window around candidate deploys / PR merges
   - if the error involves Redis / ElastiCache, also pull CloudWatch daily metrics such as:
     - `GetTypeCmds`
     - `SetTypeCmds`
     - `NewConnections`
     - optionally `CurrConnections`
   - interpretation pattern for Redis cluster cross-slot errors:
     - error count jumps together with `GetTypeCmds`, while `SetTypeCmds` stays roughly flat
     - and a recent PR changed cache TTL / eviction / fallback behavior
     - ⇒ likely not a brand-new Redis bug, but an existing cluster-slot mismatch being surfaced more often because the application now misses memory cache more often and re-queries Redis
   - explicitly check for recent code changes in the exact callsites (`git log -- <cache file> <service path> <redis wrapper>`), and also verify whether an ECS deploy happened even if code did not change
   - do not overfit to the user's intuition; it is common that "last week increased" is false once you compare recent 7 days to the prior 7 days, while the real increase happened earlier as a step-up in baseline

8. **For RDS large DDL/index timing, choose a window from recent metrics**
   - For requests like “when should we trigger `CREATE INDEX CONCURRENTLY`?”, pull at least the last 72h for the writer instance and summarize by local/KST hour.
   - Use CloudWatch `AWS/RDS` metrics on the writer `DBInstanceIdentifier`:
     - `CPUUtilization`
     - `DBLoad`, `DBLoadCPU`, `DBLoadNonCPU`
     - `ReadIOPS`, `WriteIOPS`
     - `ReadLatency`, `WriteLatency`
     - `FreeableMemory`
   - Also inspect cluster-level metrics where relevant:
     - `VolumeReadIOPs`, `VolumeWriteIOPs`
     - replica lag metrics if available
   - Rank candidate windows by low p95 CPU, low p95 DBLoad, low p95 read/write IOPS, and stable latency. Prefer a start time before the absolute quietest window if the operation may run several hours and the quietest window is followed by a known spike.
   - For Notifly Aurora examples, KST `03:00–05:00` may be the lowest slot, but KST `01:30–02:00` can be a safer trigger time for 2–6h index builds so the job finishes before the KST `08:00–12:00` spike. Recompute this each time; do not reuse old windows blindly.
   - Report both “best observed window” and “recommended trigger time,” plus explicit avoid windows and abort thresholds.

9. **For RDS CPU alarms, correlate with Performance Insights**
   - call `rds.describe_db_clusters()` / `describe_db_instances()` to identify writer vs readers and collect `DbiResourceId`
   - use Performance Insights (`pi.get_resource_metrics`, `pi.describe_dimension_keys`) on the offending instance
   - inspect:
     - `db.load.avg`
     - `os.cpuUtilization.total.avg`
7. **Validate with metric datapoints**
   - use `get_metric_statistics()` / `get_metric_data()` on the alarm metric
   - list only datapoints that actually triggered the threshold
   - match alarm transitions to datapoints

8. **For RDS/Aurora instance alarms, pivot to the exact instance and query/load shape**
   - call `describe_db_clusters()` and `describe_db_instances()` first
   - identify whether the metric belongs to the writer or a reader
   - if `PerformanceInsightsEnabled=true`, use the PI client (`session.client('pi')`) against the instance `DbiResourceId`
   - for CPU / memory / throughput investigations, inspect:
     - `db.load.avg`
     - `os.cpuUtilization.total.avg`
     - `db.sampledload.avg` grouped by `db.wait_event_type`
     - `describe_dimension_keys(... GroupBy={'Group':'db.sql_tokenized'})`
     - optionally `GroupBy={'Group':'db.sql'}` to get concrete sampled statements + `db.sql.tokenized_id`
   - for short spikes, query minute windows separately (e.g. 09:31–09:32, 09:32–09:33) to see which SQL pattern dominated each minute
   - also pull CloudWatch instance metrics like `ReadIOPS`, `WriteIOPS`, `DatabaseConnections`, `ReadLatency`, `WriteLatency`, `SwapUsage`, and `DiskQueueDepth` to distinguish:
     - connection storm
     - CPU-bound query
     - write-heavy burst
     - IO/sync pressure
     - low-freeable-memory without real distress
   - Aurora/Postgres interpretation patterns:
     - high `WriteIOPS` + PI wait events dominated by `IO` / `IO:XactSync` / `IO:DataFileRead`
     - top `db.sql_tokenized` entries are `INSERT`/`UPSERT`
     - ⇒ likely write burst, not a single expensive read query
     - `FreeableMemory` low but `SwapUsage` roughly flat, CPU moderate, latencies still normal, error rate low
     - ⇒ likely cache/buffer pressure or normal memory utilization, not an urgent memory exhaustion event
   - For `FreeableMemory` alarms specifically:
     - compute the threshold as a fraction of total RAM using PI metric `os.memory.total.avg`
     - on large instances, a static threshold like 4 GB may be only ~3% of RAM and therefore operationally noisy
     - check whether `os.swap.in.avg` / `os.swap.out.avg` are actually ramping, not just whether swap is non-zero
     - compare the alarm window against the preceding window; if workload mix and latency are similar before/after, the alarm may just be tracking a steady-state hot writer
     - review alarm history duration/frequency and, if needed, simulate alternative thresholds (e.g. 3 GB vs 4 GB) against recent metric history before recommending tuning
     - a practical recommendation pattern is:
       - lower paging threshold (example: 4 GB -> 3 GB), or
       - keep current threshold as warning only, and page only when combined with swap growth / latency deterioration / sustained DB load
   - If top PI SQL references sharded tables like `users_<projectId>`, `campaigns_<projectId>`, `user_journey_sessions_<projectId>`:
     - treat the suffix as the application `ProjectId`
     - query app logs (for Notifly, `/aws/ecs/notifly-services-prod/api-service`) and aggregate by `ProjectId` + `NormalizedPath` in the alarm window
     - look for one endpoint dominating the minute, e.g. `/user-state/:projectId/:userId?`
     - if PI exposes a concrete `user_journey_id` / `campaign_id` in SQL (example: `where user_journey_id = 'UL1T00'`), search service logs for that ID
     - for Notifly specifically, `/aws/ecs/notifly-services-prod/segment-publisher` logs often map that ID to campaign name and publish batches via messages like:
       - `campaignId: UL1T00, 460068 recipients published. (batch index: 9)`
       - `Received event: {"<projectId>":{"user_journeys":[{"id":"UL1T00","name":"[만보기] 매일 적립 리마인드"...`}
     - this lets you answer not just "which SQL" but also "which project/campaign/feature" caused the DB spike

9. **When the user says alerts feel noisier, inspect alarm config drift vs. real flapping**
   - first read the live alarm with `describe_alarms()` and capture:
     - `Period`
     - `EvaluationPeriods`
     - `DatapointsToAlarm`
     - `Threshold`
     - `TreatMissingData`
     - `AlarmActions` / `OKActions`
   - then pull `describe_alarm_history()` for three history types:
     - `ConfigurationUpdate` -> when the alarm was created/changed
     - `StateUpdate` -> how often it flips `OK <-> ALARM`
     - `Action` -> how often notifications were actually published
   - practical interpretation:
     - many `StateUpdate` / `Action` entries with `Period=60`, `EvaluationPeriods=1`, `DatapointsToAlarm=1`
     - => this is true flapping from a very sensitive alarm, not necessarily a routing bug
   - for percentile/tail-latency alarms (p95/p99/p99.9), avoid reflexively raising the threshold when the metric definition is still meaningful. First ask whether the issue is **severity** or **persistence**:
     - if threshold represents a good SLO boundary (for example p99 > 3000ms), keep it and add persistence via `datapoints_to_alarm` / `evaluation_periods`
     - use `2/3` over 5-minute periods as a common balanced default for transient external-API jitter: filters isolated spikes, still pages on ~10 minutes of bad latency within 15 minutes
     - reserve threshold increases for cases where the threshold itself is below the normal tail distribution or no longer maps to user impact
   - when recommending new alarm values, compute both:
     - live alarm history count from `describe_alarm_history()` as the actual user-visible frequency
     - metric replay simulations from `get_metric_data()` for candidate configs, e.g. `threshold=3000 1/1`, `3500 1/1`, `4000 1/1`, `3000 2/2`, `3000 2/3`, `3000 3/3`
     - call out that CloudWatch percentile alarm history and replayed metric-data simulations may not match exactly, but the simulation is still useful for relative comparison
   - final rationale for noisy tail alarms should explicitly distinguish:
     - threshold = “what counts as bad latency”
     - datapoints/evaluation periods = “how long it must stay bad before waking a human”
   - if a log-derived metric is involved, also inspect CloudTrail for `PutMetricFilter` and `PutMetricAlarm`
     - metric filters often change during setup and can materially widen the match set (`%ERROR|Exception%` -> `%ERROR|Error%` -> `ERROR`)
     - use `lookup_events` with `EventName=PutMetricFilter` / `PutMetricAlarm` and filter the request payload for the exact filter/alarm name
   - inspect the notification fan-out path directly on SNS:
     - `sns.list_subscriptions_by_topic()` to enumerate current subscribers
     - compare live subscribers against Terraform / source control
     - if live count > IaC count, call out subscription drift explicitly
   - use CloudTrail `Subscribe`, `Unsubscribe`, `SetSubscriptionAttributes`, `ConfirmSubscription` to identify when extra endpoints were added
   - important pattern:
     - users may report "alerts increased recently"
     - the real cause can be a combination of:
       1. alarm newly created or made broader
       2. additional SNS subscriber added outside Terraform
       3. genuine alarm flapping due to 1-minute / 1-datapoint sensitivity
       4. single-datapoint p99/p99.9 spikes from external API tail latency
   - in the final answer, separate these clearly:
       1. **alarm definition changed or not**
       2. **metric filter changed or not**
       3. **notification routing / subscriber count changed or not**
       4. **actual ALARM publish frequency**
       5. **simulated frequency under candidate trigger conditions**

10. **State the root cause precisely**
   - distinguish:
     - infra/network issue
     - expected business conflict incorrectly surfaced as 500
     - input validation bug
     - third-party timeout
     - writer-side batch/write burst on Aurora
     - alert noise caused by configuration sensitivity, routing drift, or true flapping
   - do not stop at "alarm fired"; identify the app behavior or SQL family that created the metric

   - do not stop at "alarm fired"; identify the app behavior or query family that created the metric

## Useful snippets

### STS identity
```bash
python - <<'PY'
import boto3, os, json
session = boto3.Session(
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    region_name=os.environ.get('AWS_DEFAULT_REGION', 'ap-northeast-2'),
)
print(json.dumps(session.client('sts').get_caller_identity(), indent=2, default=str))
PY
```

### Alarm history
```bash
python - <<'PY'
import boto3, os, json
session = boto3.Session(
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    region_name=os.environ.get('AWS_DEFAULT_REGION', 'ap-northeast-2'),
)
cw = session.client('cloudwatch')
resp = cw.describe_alarm_history(
    AlarmName='/aws/ecs/notifly-services-prod/web-console console error',
    HistoryItemType='StateUpdate',
    MaxRecords=10,
)
print(json.dumps(resp['AlarmHistoryItems'], indent=2, default=str))
PY
```

### Metric datapoints with errors only
```bash
python - <<'PY'
import boto3, os, datetime
session = boto3.Session(
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    region_name=os.environ.get('AWS_DEFAULT_REGION', 'ap-northeast-2'),
)
cw = session.client('cloudwatch')
resp = cw.get_metric_statistics(
    Namespace='ConsoleErrors',
    MetricName='/aws/ecs/notifly-services-prod/web-console console error',
    StartTime=datetime.datetime(2026,4,21,5,20,tzinfo=datetime.timezone.utc),
    EndTime=datetime.datetime(2026,4,21,7,45,tzinfo=datetime.timezone.utc),
    Period=60,
    Statistics=['Sum','SampleCount'],
)
for p in sorted(resp['Datapoints'], key=lambda x: x['Timestamp']):
    if p.get('Sum', 0) > 0:
        print(p['Timestamp'].isoformat(), p['Sum'], p.get('SampleCount'))
PY
```

### Logs Insights broad error scan
```python
query = r'''
fields @timestamp, @message, @logStream
| filter @message like /Error|TypeError|ReferenceError|Exception|Unhandled/
| sort @timestamp desc
| limit 100
'''
```

## SQS + Lambda retry / DLQ investigation pattern

This same boto3-via-`terminal` approach also works well for queue-consumer incidents such as:
- "Is retry actually happening?"
- "Are messages accumulating in the DLQ right now?"
- "Is Lambda consuming normally but some messages still exhausting maxReceiveCount?"

Recommended workflow:

1. **Read live queue attributes first**
   - call `sqs.get_queue_attributes(..., AttributeNames=['All'])`
   - capture at minimum:
     - `ApproximateNumberOfMessages`
     - `ApproximateNumberOfMessagesNotVisible`
     - `ApproximateNumberOfMessagesDelayed`
     - `VisibilityTimeout`
     - `RedrivePolicy`
     - `RedriveAllowPolicy`
   - this tells you whether the main queue is backlogged *now* and whether the DLQ currently has visible messages

2. **Pull CloudWatch SQS metrics over time**
   - use `cloudwatch.get_metric_data()` for:
     - `ApproximateNumberOfMessagesVisible`
     - `ApproximateNumberOfMessagesNotVisible`
     - `ApproximateAgeOfOldestMessage`
     - `NumberOfMessagesReceived`
     - `NumberOfMessagesDeleted`
     - `NumberOfMessagesSent`
   - compare main queue vs DLQ
   - interpretation pattern:
     - main queue near zero + DLQ non-zero and flat -> old DLQ residue, not necessarily active accumulation
     - DLQ visible increasing while main queue is active -> current failures are outpacing successful processing
     - `Received` >> `Deleted` on main queue -> repeated retries / poison messages likely
     - `ApproximateAgeOfOldestMessage` rising on DLQ while count stays flat -> stale unprocessed DLQ backlog

3. **Sample a few DLQ messages carefully**
   - use `sqs.receive_message()` with a tiny `VisibilityTimeout` (for example `1`) and `MaxNumberOfMessages=10`
   - inspect only safe metadata + selected body keys:
     - `MessageId`
     - `ApproximateReceiveCount`
     - `SentTimestamp`
     - command / tenant identifiers (if non-sensitive)
   - avoid dumping full payloads if they may contain credentials or user data
   - if sampled messages show `ApproximateReceiveCount = maxReceiveCount + 1`, that confirms they exhausted retries before landing in DLQ

4. **Correlate with Lambda logs**
   - query `/aws/lambda/<function-name>` with Logs Insights for phrases such as:
     - `will retry via SQS`
     - `rate-limited`
     - `failed, will retry via SQS`
     - service-specific failure text
   - aggregate by tenant/shop/command if possible using `parse ... | stats count() by ...`
   - this distinguishes:
     - retry path active and healthy
     - generic application failures
     - one noisy tenant dominating retries

5. **State the result precisely**
   - separate these cases:
     - retry mechanism is broken
     - retry mechanism is working, but some messages still poison-pill into DLQ
     - DLQ contains historical residue, not active accumulation

Practical example pattern observed in Notifly `cafe24-worker`:
- recent logs showed many `rate-limited for <mall>, will retry via SQS`
- main queue was empty at inspection time
- DLQ had a fixed non-zero visible count
- sampled DLQ messages had `ApproximateReceiveCount = 7` while queue `maxReceiveCount = 6`
- conclusion: retry path was active, but some rate-limited messages exhausted retry budget and landed in DLQ; the DLQ was not necessarily increasing at that moment

## Interpretation pattern

A strong alarm investigation answer should include:
1. current alarm state
2. exact alarm transition times
3. exact datapoint(s) that triggered it
4. correlated application log line(s)
5. whether the issue is a real server fault or a handled business case mislabeled as 5xx
6. concrete remediation at backend, frontend, and alerting layers if applicable

## Dynamic alarm design findings for CloudWatch/RDS

When the user asks for alarms that adapt automatically to instance churn or failover, prefer these rules of thumb:

1. **Do not propose SEARCH expressions for alarms**
   - CloudWatch `SEARCH()` is useful for graphs but cannot back an alarm because it returns multiple time series.

2. **Use Metrics Insights alarms for dynamic fleets**
   - Metrics Insights alarms are designed for multi-resource queries and can automatically include new matching resources.
   - For tag-based dynamic alarms, enable **resource tags for telemetry** first.

3. **For per-resource identification, use multi-time-series alarms + contributors**
   - Multi-time-series alarms can be inspected with `DescribeAlarmContributors`.
   - The returned `ContributorAttributes` can identify the specific breaching resource (for example `DBInstanceIdentifier`).
   - A practical pattern is: alarm -> SNS/EventBridge -> Lambda -> `DescribeAlarmContributors` -> enriched Slack/page message.
   - Avoid adding `LIMIT` to fleet/cluster coverage queries unless you intentionally want to monitor only the top N series. Metrics Insights can return up to 500 time series and Aurora can have more than 10 instances, so `LIMIT 10` can silently drop cluster members and contributors.

4. **For Aurora/RDS, verify actual metric dimensions before proposing a query**
   - Use `list_metrics` or `get_metric_data` to confirm which labels exist on the target metric.
   - In practice, `AWS/RDS` instance CPU metrics may expose `DBInstanceIdentifier` without `DBClusterIdentifier`, so a query cannot always dynamically filter to one cluster unless you add tags.
   - Do not assume prefix/wildcard filtering on identifiers will solve this; validate with a real query.

5. **Tagging is often the cleanest solution**
   - If instance membership is dynamic and failover changes roles, add a stable tag such as `Service=notifly`, `Env=prod`, or `DbCluster=notifly-db-prod-cluster` to every DB instance.
   - Then create Metrics Insights alarms using `WHERE tag.<key> = 'value' GROUP BY DBInstanceIdentifier`.

6. **If tags are unavailable, recommend automation instead of clever math**
   - Use EventBridge/Lambda or IaC automation to discover current cluster members and create/update per-instance alarms.
   - This is more reliable than trying to force CloudWatch metric math to emulate dynamic membership.

## Pitfalls

- Do not rely on `execute_code` for AWS API calls if credentials are only present in shell env.
- Do not stop at alarm metadata; always correlate with logs.
- Alarm metrics may aggregate unrelated app errors; identify the specific one tied to the alarm window.
- Some application logs may include full serialized payloads or embedded credentials/config (for example, raw `Received event:` messages). Prefer aggregated/parsing queries over dumping raw payloads, and redact any sensitive fields before reporting.
- Treat SQS `ReceiveMessage` on a production main queue as potentially mutating, not harmless read-only inspection. If `RedrivePolicy.maxReceiveCount` is very low (for example `1`), sampling a visible message can hide it and later push it to DLQ. Prefer CloudWatch metrics, Lambda consumer logs, and DLQ-only sampling with a tiny visibility timeout unless the user explicitly accepts the risk.
- Convert UTC timestamps to the user's likely timezone if operationally relevant.

## Example learned pattern

For web-console console-error alarms, a single `OK -> ALARM` transition was traced to a repeated application error like:
- `Error: The campaign was updated by another user: <id>`
- followed by `PUT .../campaigns` returning `500`

This indicates a likely optimistic-locking or stale-write conflict being surfaced as a server error. Recommended fix:
- return `409 Conflict` instead of `500`
- prevent duplicate/in-flight save requests on the frontend
- exclude handled conflicts from error alarm metrics
