# Aurora Optimized Reads Cache Hit Ratio — Mixed Topology Alarm

## Trigger

CloudWatch alarm `AuroraOptimizedReadsCacheHitRatio` on `DBClusterIdentifier`
threshold `<= 30` (or similar low value), period 3600s.

**Current live config (verified 2026-07-08)**: alarm name `Low Aurora pg
Optimized cache hit ratio`, `threshold = 25.0`, `evaluation_periods = 6`,
`datapoints_to_alarm = 3`, `comparison_operator =
LessThanOrEqualToThreshold`, `period = 3600`. Terraform location:
`infra/terraform/prod/ap-northeast-2/rds/instances.tf:363`. The
`alarm_description` field already states the threshold was deliberately
lowered from a 30% boundary to 25% specifically "to avoid paging on 30%
boundary flaps" — so Option A below (threshold adjustment) has already been
applied once historically; do not propose lowering it further as a fresh
action item unless recurrence clearly worsens.

**Recurrence baseline (as of 2026-07-08)**: sporadic, not daily —
`alarm_count_30d=4`, `alarm_count_7d=2`, isolated to two dates
(2026-06-29 and 2026-07-08) with no days in between. Metric value typically
recovers above threshold within 1-3 hours of breach (e.g. 22.4% → 24.5% →
28.3% → 36.4% across consecutive hourly points same morning). This pattern
alone is `no_action`; only escalate if daily recurrence starts or recovery
stops happening within the same day.

**Dominant project attribution via PI `top_sql`**: when Performance Insights
`db.load.avg` grouped by `db.sql` is available for the alarm focus window,
the top contending queries on Aurora Optimized Reads readers are commonly
`user_journey_sessions_<project_id>` session-count queries and
`users_<project_id>` point lookups. Map the `project_id` via DynamoDB
`project` and report the dominant project/product in `범위:`, but treat any
attempt to narrow further to a specific `user_journey_id` as a **separate,
optional follow-up** — direct Postgres reads from this environment can be
network-unreachable (VPC-restricted `notifly-db-prod-read-only` proxy
endpoint; a bare `psql`/`psycopg2` connection attempt from the Hermes
sandbox can hang and time out with no error, not just fail fast). Do not
block finalizing the answer on this follow-up; state in the final Korean
state in the final Korean answer that campaign/user journey narrowing was attempted but Postgres was
unreachable from this session, and note it as a tracked follow-up rather
than treating it as blocking evidence.

## Getting the exact SQL fingerprint (not just table family)

The helper's `rds_performance_insights.detected_scope_ids` only returns
sanitized table families (`users_<project_id>`, `event_intermediate_counts_<project_id>`,
etc.), not the literal SQL text. When the user asks "which query is the root
cause" (not just "which project"), Performance Insights is directly queryable
from this environment (it worked cleanly on 2026-07-10, contradicting the
`NotAuthorizedException` fallback note above — try PI first, fall back only
if it actually errors):

```python
import boto3, datetime

session = boto3.Session(region_name="ap-northeast-2")
rds = session.client("rds")
pi = session.client("pi")

# 1. Resolve writer vs reader and DbiResourceId (required for PI calls)
members = rds.describe_db_clusters(DBClusterIdentifier="notifly-db-prod-cluster")["DBClusters"][0]["DBClusterMembers"]
for m in members:
    d = rds.describe_db_instances(DBInstanceIdentifier=m["DBInstanceIdentifier"])["DBInstances"][0]
    print(m["DBInstanceIdentifier"], m["IsClusterWriter"], d["DbiResourceId"], d["DBInstanceClass"])

# 2. Per-reader top SQL by db.load.avg, bounded to the alarm focus window
start = datetime.datetime(2026,7,10,5,0,0, tzinfo=datetime.timezone.utc)
end   = datetime.datetime(2026,7,10,7,30,0, tzinfo=datetime.timezone.utc)
resp = pi.describe_dimension_keys(
    ServiceType="RDS", Identifier="<reader DbiResourceId>",
    StartTime=start, EndTime=end, Metric="db.load.avg",
    GroupBy={"Group": "db.sql", "Limit": 5},
)
for k in resp["Keys"]:
    dims = k["Dimensions"]
    print(round(k["Total"], 3), dims.get("db.sql.statement", "")[:200])
```

Run this against all NVMe reader instances (not just one) — the same top
query commonly appears near the top of every reader's list, which is itself
evidence that it's the dominant cache-thrashing contributor rather than an
artifact of one instance's local working set. As of 2026-07-10 the two
recurring top queries across all three readers were a
`user_journey_sessions_<project_id>` session-count aggregate scoped to a
single `user_journey_id` (`... where "user_journey_id" = '<id>' and "id" not
like '...'`) and a `users_<project_id>` single-row point lookup
(`select * from "users_<project_id>" where "notifly_user_id" = $1`). Both use
indexed/PK columns, so the individual query cost is low — the cache pressure
comes from call *frequency*, not per-query cost. When reporting root cause,
name the literal SQL text (truncated) plus the mapped project, not just the
table family.

## Root cause

The alarm is usually **infrastructure-characteristic**, not an incident.
The `notifly-db-prod-cluster` runs mixed instance classes:

| Instance | Class | NVMe Optimized Reads |
|----------|-------|----------------------|
| Writer   | `db.r6g.4xlarge`  | No  |
| Readers a,b,d | `db.r6gd.2xlarge` | Yes |

`AuroraOptimizedReadsCacheHitRatio` is a cluster-level average.
Instances without NVMe cache contribute no cache hits, pulling the average down.
Reader instances with NVMe cache naturally show ratios in the 6–35% range
depending on working-set fit. Recent hourly peaks on reader nodes have
observed ~28–39% during active load windows.

Cluster-level daily averages are typically much lower (7–17%) because
non-NVMe writer nodes contribute zero cache hits, and off-peak hours drive
the average down even when peak-hour reader values are healthy.

## Quick diagnosis

1. **Per-instance metric** by `DBInstanceIdentifier`:

```python
import boto3, datetime

cw = boto3.client('cloudwatch', region_name='ap-northeast-2')
instances = ['notifly-db-prod-a','notifly-db-prod-b',
             'notifly-db-prod-c','notifly-db-prod-d']
end = datetime.datetime.now(datetime.timezone.utc)
start = end - datetime.timedelta(days=1)

for inst in instances:
    r = cw.get_metric_statistics(
        Namespace='AWS/RDS',
        MetricName='AuroraOptimizedReadsCacheHitRatio',
        Dimensions=[{'Name':'DBInstanceIdentifier','Value':inst}],
        StartTime=start.isoformat(),
        EndTime=end.isoformat(),
        Period=3600, Statistics=['Average'])
    print(inst, [(p['Timestamp'].isoformat(), round(p['Average'],2))
                 for p in sorted(r['Datapoints'], key=lambda x:x['Timestamp'])])
```

- **NVMe-less instances** (`db.r6g.*`): no datapoints (or `null`).
- **NVMe-capable instances** (`db.r6gd.*`): values 6–35% are normal for this workload.

**Shell equivalent** (bounded to alarm window, for quick triage):

```bash
for inst in notifly-db-prod-a notifly-db-prod-b notifly-db-prod-c notifly-db-prod-d; do
  echo "=== $inst ==="
  aws cloudwatch get-metric-statistics --region ap-northeast-2 \
    --namespace AWS/RDS --metric-name AuroraOptimizedReadsCacheHitRatio \
    --dimensions Name=DBInstanceIdentifier,Value="$inst" \
    --start-time '2026-06-02T20:00:00Z' --end-time '2026-06-03T02:30:00Z' \
    --period 3600 --statistics Average --output json \
    | jq -r '.Datapoints | sort_by(.Timestamp) | .[] | [.Timestamp, .Average] | @tsv'
done
```

Replace the `--start-time` / `--end-time` with the alarm
`StateReasonData.startDate` ± 3 hours window.

2. **Cross-check actual health** (cluster-level):

```bash
aws cloudwatch get-metric-statistics \
  --region ap-northeast-2 \
  --namespace AWS/RDS \
  --metric-name ReadLatency \
  --dimensions Name=DBClusterIdentifier,Value=notifly-db-prod-cluster \
  --start-time $(date -u -d '3 hours ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time   $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 3600 --statistics Average
```

If `ReadLatency` < 5 ms and `CPUUtilization` < 50%, the cluster is healthy
and the low cache-hit ratio is architectural, not operational.

## Classification

- **`no_action`** when ReadLatency/CPU are healthy and the mixed topology is known.
- **`needs_fix`** only if ReadLatency or CPU spike simultaneously, indicating real
  read amplification or cache thrashing.

## Rapid-flap classification (2026-07-10 case)

When this alarm (or any alarm sitting near a noisy metric's natural
oscillation band) transitions OK↔ALARM many times in a short window (e.g. 6-7
flips in 30-40 minutes: `07:14 ALARM → 07:27 OK → 07:44 ALARM → 07:46 OK →
07:48 ALARM → 07:49 OK → 07:50 ALARM`), check `history.rapid_recurrence` and
the underlying health metrics (ReadLatency, CPUUtilization, per-instance
cache-hit-ratio breakdown) for the same window before deciding severity.

If ReadLatency stays ~2ms, CPU stays 20-30%, and each individual reader's
cache-hit-ratio is independently oscillating 12-28% (i.e. the flap is real
metric noise, not a data/monitoring artifact), this is **not an incident** —
the DB is healthy. But it is also not `no_action`: sustained OK↔ALARM
flapping burns paging budget and attention, so it should be classified
`needs_fix` for the alarm-tuning work itself, distinct from the (healthy)
underlying system.

**Do not just re-lower the threshold again.** This alarm's `alarm_description`
already documents a prior fix (30% → 25%) for the exact same flapping
symptom. If it recurs at the new threshold, the metric's natural variance is
wider than the gap being defended, and lowering the threshold again only
delays the next recurrence. Prefer widening the evaluation window instead:
raise `evaluation_periods`/`datapoints_to_alarm` (e.g. from 6/3 to 12/9,
extending the observation window from ~3h to ~6h) so transient noise gets
averaged out before triggering, rather than reacting to single-hour dips.
Terraform location: `infra/terraform/prod/ap-northeast-2/rds/instances.tf:363`
(`"Low Aurora pg Optimized cache hit ratio"` block, fields
`evaluation_periods` / `datapoints_to_alarm` / `threshold`).

## Long-term remediation

**Option A — Threshold adjustment** (fastest):
Update Terraform `infra/terraform/prod/ap-northeast-2/rds/instances.tf`
alarm `"Low Aurora pg Optimized cache hit ratio"`:
- Raise `threshold` from `30.0` to `5.0`, or remove the alarm entirely.

**Option B — Instance class standardization**:
Migrate writer to `db.r6gd.4xlarge` (or larger) so all nodes have NVMe cache.
This raises the cluster-level ratio but is a capacity-planning decision.

**Option C — Disable alarm**:
If this alarm fires repeatedly and never correlates with real performance
degradation, remove it to reduce noise.

## Historical context

- Alarm introduced: commit `16b212d27` (2026-04-11).
- Last threshold/alarm tuning: commit `617576c70` (2026-04-29).

## 2026-07-10 recurrence (10 flips in one day)

`alarm_count_1d=10`, `rapid_recurrence.status=rapid` (2 transitions within
10 minutes, 8 within ~2 hours, e.g. `07:48→07:50→08:07→08:41→08:50→09:07→
09:37→09:41 UTC`). Verified during this recurrence: `ReadLatency` ~2ms flat,
`CPUUtilization` 25-32% flat across the entire 07:00-09:30 UTC window — cluster
fully healthy, consistent with the architectural (mixed NVMe/non-NVMe
topology) explanation, not a load incident. PI top SQL on readers again
showed the same `user_journey_sessions_<project_id>` session-count query
(project `b2b4a8f879a75673b755bff42fc1deb6`) and `users_<project_id>` point
lookup (project `32d8d9d6294d52e7a5427c036b471f91`) as dominant — unchanged
from the 2026-07-10 (morning) case above, reinforcing this is steady-state
background load, not a new query pattern. Classified `needs_fix` (alarm
tuning only) per the rapid-flap rule above, since this is now the second
documented rapid-flap day; if it recurs a third time, escalate the Terraform
`evaluation_periods`/`datapoints_to_alarm` widening from a suggestion to a
scheduled task.

## 2026-07-10 (later same day) — third recurrence day, 13 flips

Same alarm fired again later the same UTC day, bringing `alarm_count_1d=13`
(daily_alarm_counts: `2026-06-29: 2`, `2026-07-08: 2`, `2026-07-10: 13`) —
this is the **third distinct calendar day** this exact rapid-flap pattern
has recurred (06/29, 07/08, 07/10), and 07/10 alone now has more flips than
the earlier 07/10 entry above (13 vs 10), confirming a worsening trend
within the same day rather than a one-off. `rapid_recurrence.status` was
`normal` at the moment of the latest transition (19 min since previous) but
`alarm_count_within_30m=3` and 8 transitions occurred within the preceding
~2 hours (08:41-10:38 UTC) - still a flapping day by the alarm_count_1d
signal even when the instantaneous rapid_recurrence check reads normal.

Cluster health re-verified for 08:30-10:52 UTC: `ReadLatency` flat at ~2ms,
`CPUUtilization` cluster average 22-39% (per-instance peaks up to ~75% on a
single reader, consistent with one NVMe reader taking disproportionate
load). Healthy. PI dominant projects unchanged from prior entries: `stepup`
(`32d8d9d6294d52e7a5427c036b471f91`, users_/event_intermediate_counts_ point
lookups) and `regather` (`b57754a9497a545ab9b0e4aadd6f53b6`,
delivery_result_ query) as top two by focus load.

Per this doc's own escalation rule ("if it recurs a third time, escalate the
Terraform evaluation_periods/datapoints_to_alarm widening from a suggestion
to a scheduled task"): **this is that third recurrence.** Treat the
Terraform widening (raise `evaluation_periods`/`datapoints_to_alarm` from
6/3 to roughly 12/9 in
`infra/terraform/prod/ap-northeast-2/rds/instances.tf:363`, block `"Low
Aurora pg Optimized cache hit ratio"`) as a `needs_fix` action item to
schedule now, not just a suggestion for next time.

## 2026-07-10 (evening) — fourth recurrence day, 14 flips, still unfixed

Same alarm, same day, now `alarm_count_1d=14` (up from 13 earlier the same
day, `daily_alarm_counts`: `2026-06-29: 2`, `2026-07-08: 2`, `2026-07-10:
18` cumulative for 30d window). `rapid_recurrence.status=rapid` again (2
transitions within 10 minutes: 10:37→10:41 UTC). Re-verified cluster health
05:00-11:00 UTC: `ReadLatency` flat ~2ms, `CPUUtilization` cluster average
19-28% (per-instance max spikes to ~81% on individual readers, average
stays low) — still healthy, still the same mixed-topology architectural
signature. PI top SQL unchanged: `stepup`
(`32d8d9d6294d52e7a5427c036b471f91`) and `regather`
(`b57754a9497a545ab9b0e4aadd6f53b6`) remain dominant contributors, plus
`playio` (`ffde3a7a000b5b2198961b3fff400acd`) as a smaller third.

**The Terraform `evaluation_periods`/`datapoints_to_alarm` widening flagged
as a scheduled `needs_fix` task after the third recurrence has still not
been applied as of this entry.** Each subsequent flap day without the fix
is the same known issue recurring, not new information — continue reporting
`needs_fix` (tuning debt) rather than re-deriving root cause each time, and
treat the fix as increasingly overdue given four flap-days now on record.

## 2026-07-10 (later still) — sixth same-day check, 17 flips, still unfixed

`alarm_count_1d=17`, `alarm_count_7d=19`, `alarm_count_30d=21`
(`daily_alarm_counts`: `2026-06-29: 2`, `2026-07-08: 2`, `2026-07-10: 17`).
Re-verified cluster health for the trailing 6h to 11:xx UTC: `ReadLatency`
flat ~0.002s (max 0.004-0.005s), `CPUUtilization` cluster average 22-33%
(max per-period up to ~78%). Still healthy, still the same architectural
signature. No new evidence — the Terraform `evaluation_periods`/
`datapoints_to_alarm` widening (6/3 → ~12/9) is now overdue across six
same-day check-ins. Continue `needs_fix` for the alarm-tuning debt; do not
re-derive root cause on subsequent occurrences unless health metrics or PI
dominant projects actually change.

## 2026-07-10 (later) — fifth recurrence day, 15 flips same day, still unfixed

Same alarm, same calendar day, `alarm_count_1d=15`, `alarm_count_7d=17`,
`alarm_count_30d=19` (`daily_alarm_counts`: `2026-06-29: 2`, `2026-07-08: 2`,
`2026-07-10: 15`). `rapid_recurrence.status=normal` at the instant of the
latest transition (34 min since previous), but 8 transitions still landed
within the preceding ~2 hours (09:07-11:15 UTC) — same flapping-day pattern
as prior entries even when the instantaneous check reads normal.

Re-verified cluster health 05:30-11:30 UTC: `ReadLatency` flat at ~2ms
(0.002s avg, max 0.004-0.006s), `CPUUtilization` cluster average 22-34%
(per-instance max spikes 59-81% on individual readers, average stays low).
Still healthy, still the same mixed-NVMe-topology architectural signature.
PI dominant projects unchanged: `stepup` (`32d8d9d6294d52e7a5427c036b471f91`),
`regather` (`b57754a9497a545ab9b0e4aadd6f53b6`), `playio`
(`ffde3a7a000b5b2198961b3fff400acd`).

This is now the **fifth documented flap-day** (06/29, 07/08, 07/10 ×3
sub-entries) with the Terraform `evaluation_periods`/`datapoints_to_alarm`
widening (6/3 → ~12/9) still not applied. Continue classifying `needs_fix`
for the alarm-tuning debt on every occurrence until the Terraform change
actually lands — do not silently downgrade to `no_action` just because the
underlying DB is healthy each time.
