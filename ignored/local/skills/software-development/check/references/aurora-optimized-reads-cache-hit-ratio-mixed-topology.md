# Aurora Optimized Reads Cache Hit Ratio — Mixed Topology Alarm

## Trigger

CloudWatch alarm `AuroraOptimizedReadsCacheHitRatio` on `DBClusterIdentifier`
threshold `<= 30` (or similar low value), period 3600s.

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
depending on working-set fit.

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
