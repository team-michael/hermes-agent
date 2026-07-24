# Aurora Writer CPU Spike — Scheduled Batch Lambda Correlation

## Alarm shape

- CloudWatch Metrics Insights alarm using `metric_query.expression`
- Example: `SELECT MAX(CPUUtilization) FROM SCHEMA("AWS/RDS", DBInstanceIdentifier) WHERE tag.DBClusterIdentifier = 'notifly-db-prod-cluster' GROUP BY DBInstanceIdentifier ORDER BY MAX() DESC`
- Alarm name: `notifly-db-prod-instance-high-cpu-usage` (or similar dynamic instance alarm)
- Threshold: typically `> 70%` for 5 minutes

## Why the helper metric fields are null

The `check` helper resolves `describe-alarms` but does not parse `metric_query` expressions. It expects `Namespace` + `MetricName` + `Dimensions` at the alarm top level. When the alarm uses `metric_query`, `metric.namespace`, `metric.name`, and `metric.dimensions` are all null/empty. This is expected behavior — do not treat it as missing data.

## Quick triage checklist

1. **Read the Terraform `metric_query.expression`** to understand what the alarm actually measures. The `code` field from the helper usually contains the exact expression.
2. **Identify the breaching instance** — run per-instance `CPUUtilization` for all cluster members. The dynamic query returns the max across instances; one instance drives the alarm.
3. **Check instance role** — use `describe-db-clusters` to identify writer vs readers.
4. **Performance Insights** — if available, run `describe-dimension-keys` with `Group: db.sql` on the offending instance. If `NotAuthorizedException`, fall back immediately.
5. **Lambda batch correlation** (PI fallback) — check `AWS/Lambda` `Invocations` for `scheduled-batch-delivery`, `scheduled-batch-kakao-alimtalk-delivery`, `scheduled-batch-text-message-delivery`, `user-journey-node-runner` during the exact CPU spike window.
   - Look for a sudden jump (e.g., ~250 → ~900 invocations/min).
   - Check `Duration` — if average jumps from ~300 ms to ~10,000 ms, the Lambdas are doing heavy DB work.
   - Check `Errors` — if zero, the batch completed normally.
6. **Time-of-day check** — spikes at ~01:00 UTC (~10:00 KST) strongly correlate with the daily scheduled campaign batch window.
7. **ECS service logs** — check `segment-publisher` for `Start extracting project segment` and `recipients published` lines during the window.
8. **Classification** — if Lambda Errors=0, CPU recovers within 5–10 minutes, and no other alarms (e.g., `BatchFailure`, `lambda error`) fire, classify as transient batch workload.

## Per-instance CPU commands

```bash
for id in notifly-db-prod-a notifly-db-prod-b notifly-db-prod-c notifly-db-prod-d; do
  aws cloudwatch get-metric-statistics --region ap-northeast-2 \
    --namespace AWS/RDS --metric-name CPUUtilization \
    --statistics Average Maximum \
    --dimensions Name=DBInstanceIdentifier,Value=$id \
    --start-time 'YYYY-MM-DDTHH:MM:SSZ' \
    --end-time 'YYYY-MM-DDTHH:MM:SSZ' \
    --period 60 \
    --query 'Datapoints[*].{Timestamp:Timestamp,Avg:Average,Max:Maximum}' \
    --output json | jq -s '.[0] | sort_by(.Timestamp)'
done
```

## Lambda batch correlation commands

```bash
for fn in scheduled-batch-delivery scheduled-batch-text-message-delivery \
          scheduled-batch-kakao-alimtalk-delivery \
          scheduled-batch-kakao-friendtalk-delivery \
          user-journey-node-runner kds-consumer; do
  aws cloudwatch get-metric-statistics --region ap-northeast-2 \
    --namespace AWS/Lambda --metric-name Invocations \
    --statistics Sum --dimensions Name=FunctionName,Value=$fn \
    --start-time 'YYYY-MM-DDTHH:MM:SSZ' \
    --end-time 'YYYY-MM-DDTHH:MM:SSZ' \
    --period 60 \
    --query 'Datapoints[*].{Timestamp:Timestamp,Sum:Sum}' \
    --output json
done
```

## Interpretation

| Pattern | Classification |
|---------|---------------|
| CPU spike on writer, Lambda batch invocations spike simultaneously, Errors=0, Duration elevated, CPU recovers in < 10 min | `no_action` |
| CPU spike with Lambda Errors > 0 or Duration near Timeout, or does not recover | `needs_fix` or `urgent` |
| CPU spike on a reader (not writer) with no batch correlation | `needs_fix` — investigate runaway query or replica instability |

## Scope

The alarm itself is infra-wide (cluster-level). Lambda logs may contain `project_id`/`campaign_id` for scope, but EMF metric emission lines in `scheduled-batch-delivery` do NOT carry project/campaign IDs. Use `kds-consumer` or `segment-publisher` logs for project scope instead, or accept infra-wide scope.

## Data retention limits when investigating old alarms

- **Performance Insights**: PI data is retained for only 7 days. When the alarm fired more than 7 days ago, `pi describe-dimension-keys` returns `InvalidArgumentException: Specify a start time that's within 7 days of the current date and time.` Fall back immediately to Lambda batch correlation.
- **CloudWatch 1-minute metrics**: Retained for 15 days. For alarms older than 15 days, `get-metric-statistics` with `--period 60` returns empty. Use `--period 300` (5-minute, retained 63 days) instead. The 5-minute Maximum is a conservative proxy — the actual 1-minute peak may have been higher.
- **CloudWatch alarm history**: Retained for 90 days. Use `describe-alarm-history` with `--history-item-type StateUpdate` and parse `HistoryData` JSON for `oldState.stateValue` / `newState.stateValue` when `StateValue` is null.

## Borderline threshold classification

The alarm threshold (`> 70%` for 5 consecutive 1-minute periods) is borderline for the daily batch peak. Observed daily writer CPU maxima at 01:00 UTC (10:00 KST):

| Date | 5-min Max CPU | Alarm fired? |
|------|---------------|--------------|
| 2026-06-03 | 73.6% | No |
| 2026-06-04 | 71.9% | No |
| 2026-06-05 | 75.5% | **Yes** (only day with 5 consecutive 1-min points > 70%) |
| 2026-06-06 | 72.5% | No |
| 2026-06-07 | 73.5% | No |
| 2026-06-10 | 74.6% | No |
| 2026-06-15 | 70.3% | No |
| 2026-06-20 | 71.9% | No |
| 2026-06-24 | 72.2% | No |

Only 1 ALARM transition in 90 days. The alarm fires when the daily spike happens to sustain > 70% for 5 consecutive 1-minute points — most days the spike peaks at 70-74% but dips below 70% within 2-3 minutes. Classify as `no_action` when:
- The alarm auto-recovers within 60 seconds
- Lambda `Errors = 0` during the window
- Only 1 ALARM transition in the 30-day window
- The spike occurs at the expected daily batch time (~01:00 UTC / 10:00 KST)

## Known gotchas

- **EMF metric lines lack project scope**: `scheduled-batch-delivery` Lambda stdout emits CloudWatch EMF metrics at INFO level. These tab-delimited lines contain only `_aws`, `channel`, `outcome`, etc., not `projectId` or `campaignId`. Logs Insights `parse` on these lines for project scope will fail.
- **kds-consumer JSON logs do carry project scope**: `kds-consumer` uses structured JSON logging. A Logs Insights `parse @message /"project_id":"(?<project_id>[^"]+)"/ ...` query works there.
- **Scheduled batch window**: Daily at ~01:00 UTC (10:00 KST). Alarms firing near this time are likely batch-driven.
