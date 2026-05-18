# Aurora Reader Replica `canceling statement due to conflict with recovery`

Pattern for PostgreSQL Aurora reader replica WAL-recovery conflicts that surface as ERROR logs in downstream ECS services (notably `api-service`).

## Alarm manifestation

- **Alarm name**: `/aws/ecs/notifly-services-prod/api-service console error` (or any ECS `ConsoleErrors` metric-filter alarm)
- **Namespace**: `ConsoleErrors`
- **Current trigger log signature**:
  ```
  Failed to get user data error: canceling statement due to conflict with recovery
  severity: 'ERROR',
  code: '40001',
  detail: 'User query may not have access to page data due to replica disconnect.',
  hint: 'When the replica reconnects you will be able to repeat your command.',
  file: 'grv.c',
  line: '750',
  routine: 'grread_mq'
  ```
- **Stack trace**: goes through `pg/lib/client.js` retry paths (`packages/common/dist/db.js` → `userdb/dist/index.js` → `api-service/lib/api/user-state/db.js`)

This is **not** an `api-service` code bug. It is an Aurora PostgreSQL infrastructure behavior where a reader replica cancels read queries that conflict with WAL recovery.

## Immediate triage flow

### 1. Confirm the error family and volume concentration

Check whether the entire alarm-window count belongs to this single family or is mixed with other ERROR patterns:

```bash
python3 -c "
import boto3, datetime
logs = boto3.client('logs', region_name='ap-northeast-2')
start_ms = int((datetime.datetime.utcnow() - datetime.timedelta(minutes=20)).timestamp() * 1000)
end_ms   = int(datetime.datetime.utcnow().timestamp() * 1000)
for pattern in ['canceling statement due to conflict with recovery', 'relation does not exist', 'UnhandledPromise']:
    n = len(logs.filter_log_events(
        logGroupName='/aws/ecs/notifly-services-prod/api-service',
        filterPattern=pattern, startTime=start_ms, endTime=end_ms, limit=1000
    ).get('events', []))
    print(f'{pattern}: {n}')
"
```

### 2. Bound the spike with 15-minute buckets

A transient Aurora hiccup typically shows 0 → concentrated burst → 0 within one or two 15-minute windows:

```bash
python3 -c "
import boto3, datetime
logs = boto3.client('logs', region_name='ap-northeast-2')
for offset in range(0, 120, 15):
    s = int((datetime.datetime.utcnow() - datetime.timedelta(minutes=offset+15)).timestamp() * 1000)
    e = int((datetime.datetime.utcnow() - datetime.timedelta(minutes=offset)).timestamp() * 1000)
    n = len(logs.filter_log_events(
        logGroupName='/aws/ecs/notifly-services-prod/api-service',
        filterPattern='canceling statement due to conflict with recovery',
        startTime=s, endTime=e, limit=1000
    ).get('events', []))
    t = (datetime.datetime.utcnow() - datetime.timedelta(minutes=offset+15)).strftime('%H:%M')
    print(f'{t}: {n}')
"
```

- **Normal baseline**: 0 per 15 minutes, or 2–30 per day total (historical daily counts).
- **Transient spike**: 500–1,500+ in a single 15-minute window, surrounded by zeros.
- **Sustained issue**: nonzero counts across consecutive windows for ≥ 1 hour.

### 3. Correlate with RDS ReadLatency / CPU

If the spike is current, check whether the cluster has already recovered:

```bash
python3 -c "
import boto3, datetime
cw = boto3.client('cloudwatch', region_name='ap-northeast-2')
now = datetime.datetime.utcnow()
for dbi in ['notifly-db-prod-a', 'notifly-db-prod-b', 'notifly-db-prod-c', 'notifly-db-prod-d']:
    resp = cw.get_metric_statistics(
        Namespace='AWS/RDS', MetricName='ReadLatency',
        Dimensions=[{'Name':'DBInstanceIdentifier','Value':dbi}],
        StartTime=now - datetime.timedelta(minutes=30), EndTime=now,
        Period=300, Statistics=['Average','Maximum'])
    pts = sorted(resp['Datapoints'], key=lambda x: x['Timestamp'])
    for p in pts[-2:]:
        t = p['Timestamp'].strftime('%H:%M')
        print(f'{dbi} {t} avg={p[\"Average\"]:.4f}s max={p[\"Maximum\"]:.4f}s')
"
```

- **Recovered**: ReadLatency drops back to < 0.005 s, CPU normalizes.
- **Still degraded**: ReadLatency stays > 0.05 s or CPU stays elevated on readers.

## Scope attribution

- Extract `project_id` from the sharded table name in the failed query (e.g., `users_32d8d9d6294d52e7a5427c036b471f91` → `32d8d9d6294d52e7a5427c036b471f91`).
- Map via DynamoDB `project` table. Multiple projects may appear if the replica conflict affected concurrent requests across tenants.
- `project_campaign_pairs` may appear from other log fields (e.g., `error-response` lines); they reflect the API request context, not DB ownership.

## Classification guidance

| Pattern | Condition | Status | Rationale |
|---|---|---|---|
| **Transient spike** | Single 15-min burst, then 0; ReadLatency recovered | `no_action` | Aurora internal replica hiccup, already resolved. No customer-facing data loss. |
| **Sustained/recurring** | > 1 hour of continuous conflicts across multiple windows, or daily recurrence at same clock time | `needs_fix` | Indicates chronic replica pressure (heavy write batch, undersized reader, or hot-table contention). Requires PI or DBA review. |
| **Mixed with other errors** | `relation does not exist` or unhandled exception counts are also significant | `needs_fix` | The DB conflict may be hiding or compounding a separate code issue. |

## Distinguishing from application bugs

| Replica conflict | Application bug |
|---|---|
| `code: '40001'` with `detail: 'User query may not have access to page data due to replica disconnect.'` | Custom business/validation error message |
| `file: 'grv.c'` / `routine: 'grread_mq'` (Postgres internal) | Application `.js` file in stack top frame |
| Stack goes through `pg/lib/client.js` retry wrappers | Stack ends in application route/controller |
| Multiple unrelated projects affected simultaneously | Usually scoped to one project or one campaign |
| RDS ReadLatency spikes correlate in time | RDS metrics stay flat |

## Long-term remediation options

1. **Log-level audit** — These logs are emitted as `ERROR` from the `pg` driver retry path. Consider whether a transient replica conflict should be `WARN` (retried and may succeed on next attempt) rather than `ERROR`, so the coarse `ConsoleErrors` metric filter does not treat Aurora maintenance spikes as service incidents.
2. **Alarm threshold / evaluation periods** — A 1-minute period with threshold 1 is extremely sensitive to any single ERROR log. For DB-replica noise, increasing `EvaluationPeriods` or requiring a sustained rate would reduce false-positive paging.
3. **Reader sizing / topology** — If recurrence is sustained, evaluate whether reader instances are sized for peak WAL apply rates, or if query routing should temporarily avoid the lagging replica.
