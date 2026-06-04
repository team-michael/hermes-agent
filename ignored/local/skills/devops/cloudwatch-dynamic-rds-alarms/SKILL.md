---
name: cloudwatch-dynamic-rds-alarms
description: Design CloudWatch alarms for Aurora/RDS fleets where instance names and roles change over time. Covers Metrics Insights multi-time-series alarms, contributor lookup, and why tags are required for cluster-scoped dynamic per-instance alerting.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [cloudwatch, rds, aurora, alarms, metrics-insights, dynamic-alerting, tags]
---

# CloudWatch Dynamic RDS/Aurora Alarms

Use this when the user wants alerts that keep working even if:
- Aurora instances are added/removed
- writer/reader roles change due to failover
- fixed per-instance alarm names are operationally brittle

## Core findings

### 1. SEARCH expressions are not usable for alarms
CloudWatch `SEARCH(...)` can create dynamic graphs, but **cannot back alarms** because it returns multiple time series.

So this approach is a dead end for dynamic per-instance alerting:
- `SEARCH('{AWS/RDS,DBInstanceIdentifier} ...')`
- metric-math alarm on top of SEARCH

### 2. Metrics Insights alarms are the right primitive
CloudWatch **Metrics Insights alarms** can monitor changing fleets without manually updating alarm definitions.

AWS docs explicitly state these queries can:
- catch new resources
- adapt as resources change
- use `GROUP BY`
- use resource tags in alarm queries

### 3. Multi-time-series alarms expose contributors
For Metrics Insights alarms that monitor multiple time series, use:
- `DescribeAlarmContributors`

This returns the individual breaching series and identifying attributes (for example metric dimensions like `DBInstanceIdentifier`).

This is the clean way to enrich notifications with the exact breaching instance.

### 4. For Aurora/RDS instance metrics, tags are usually required
Practical finding from live testing:
- per-instance `AWS/RDS` metrics may expose only `DBInstanceIdentifier`
- they may **not** expose `DBClusterIdentifier` on instance time series
- wildcard/prefix matching like `DBInstanceIdentifier = 'notifly-db-prod%'` did **not** work in Metrics Insights testing

Therefore, if you want:
- "all current instances in this cluster"
- while surviving add/remove/failover

then the robust solution is to use **resource tags** and filter by tag.

## Recommended architecture

For Aurora Optimized Reads cache-hit alarms specifically, see `references/aurora-optimized-reads-cache-hit-ratio.md`. Key lesson: treat `AuroraOptimizedReadsCacheHitRatio` as a warning/diagnostic signal, require persistence for noisy boundary flaps, and keep existing Terraform alarm names/`for_each` keys when tuning so the plan remains in-place under `prevent_destroy`.

### Step 1: tag cluster instances with a stable cluster key
Good tag name:
- `DBClusterIdentifier`

Example value:
- `notifly-db-prod-cluster`

Why this tag name works well:
- directly maps to Aurora/RDS cluster identity
- easy to reuse in Metrics Insights queries
- remains stable even when instance names or roles change

### Step 2: enable CloudWatch resource tags for telemetry
This must be enabled in CloudWatch before tag-based Metrics Insights alarms work.

### Step 3: create Metrics Insights multi-time-series alarms
Example CPU alarm:

```sql
SELECT MAX(CPUUtilization)
FROM SCHEMA("AWS/RDS", DBInstanceIdentifier)
WHERE tag.DBClusterIdentifier = 'notifly-db-prod-cluster'
GROUP BY DBInstanceIdentifier
ORDER BY MAX() DESC
```

Example FreeableMemory alarm:

```sql
SELECT MIN(FreeableMemory)
FROM SCHEMA("AWS/RDS", DBInstanceIdentifier)
WHERE tag.DBClusterIdentifier = 'notifly-db-prod-cluster'
GROUP BY DBInstanceIdentifier
ORDER BY MIN() ASC
```

Use `SCHEMA("AWS/RDS", DBInstanceIdentifier)` instead of bare `FROM "AWS/RDS"` for RDS instance alarms so the query analyzes only instance-level time series and avoids cluster/other dimension noise.

Do **not** add `LIMIT` to fleet coverage alarms unless deliberately monitoring only top-N series. Aurora clusters can exceed 10 instances and Metrics Insights can return up to 500 time series, so `LIMIT 10` can silently drop instances and contributors.

This gives you:
- dynamic inclusion/exclusion as instances change
- per-instance contributors
- no dependence on fixed instance inventory

### Step 4: enrich notifications with contributors
Preferred flow:
- CloudWatch alarm
- SNS or EventBridge
- Lambda or notification worker
- call `DescribeAlarmContributors(AlarmName=...)`
- extract contributor attributes
- send Slack/incident message including `DBInstanceIdentifier`

This is safer than assuming the initial alarm payload includes enough contributor detail.

## What this solves vs what it does not

### Solves
- dynamic instance add/remove
- failover changing writer/reader roles
- per-instance alert attribution without hand-maintained alarm inventory

### Does not directly solve
- "current writer only" alerting

Writer-specific dynamic alerting is harder because writer/reader is runtime state, not just static inventory. Options then are:
- cluster-level metrics
- automation that retargets alarms after failover
- separate runtime discovery logic

## Terraform implementation note
If the Terraform-managed Aurora cluster and cluster instances currently have `tags = {}` and `lifecycle.ignore_changes = [tags]`, then:
- add the stable tag to both cluster and cluster instances
- remove tag ignore if you want Terraform to actually apply the tags

Example pattern:

```hcl
tags = merge(
  try(each.value.tags, {}),
  {
    DBClusterIdentifier = each.value.cluster_identifier
  },
)
```

For incident-style dynamic RDS instance alarms, practical defaults are:
- CPU: keep parity with existing per-instance incident alarms, e.g. `CPUUtilization > 70` for `5/5` minutes, instead of copying a noisy cluster warning like `>50` for `3/3`.
- FreeableMemory: do **not** blindly use one fixed threshold as a capacity-pressure signal across heterogeneous instance classes. First list the live `DBInstanceClass` values, estimate/measure total memory per class, and replay recent `FreeableMemory` history plus alarm history. For Aurora, low free memory often reflects cache/buffer use, so split the semantics:
  - **Capacity warning**: class-aware or percentage-based, likely non-paging, and preferably combined with swap growth / latency / DB load.
  - **Incident/page**: avoid paging on a fixed `FreeableMemory` byte threshold across heterogeneous instance classes. A byte floor can be useful as warning-only visibility, but it is not equivalent to CPU percent and has different meaning on a 62 GiB reader vs a 125 GiB writer. For paging, prefer a custom `FreeableMemoryPercent` metric, class/tag-specific alarms, or a composite pressure signal using swap growth / latency / DB load.
- RDS does not expose a native `FreeableMemoryPercent` metric in `AWS/RDS`. You can compute a relative value per instance with CloudWatch metric math by combining `AWS/RDS.FreeableMemory` with `DB_PERF_INSIGHTS('RDS', '<DbiResourceId>', 'os.memory.total.avg')`, e.g. `100 * freeable / (total_kb * 1024)`. This works for explicit per-instance alarms but does **not** preserve the tag-based Metrics Insights fleet query pattern because `DB_PERF_INSIGHTS` requires concrete `DbiResourceId` values and is not stored as a Metrics Insights metric. If you need both percent semantics and dynamic tag-based fleet coverage, publish a custom `FreeableMemoryPercent` metric with `DBClusterIdentifier` and `DBInstanceIdentifier` dimensions.
- Alarm descriptions should state byte thresholds precisely when using CloudWatch byte metrics; avoid ambiguous `GB` vs `GiB` wording.
- Alarm names should describe the monitored scope rather than the implementation mechanism. Prefer names like `notifly-db-prod-instance-high-cpu-usage` over names containing `-dynamic-`; dynamic behavior is an implementation detail.

## Verification checklist
1. Confirm RDS cluster/instances actually have the tag.
2. Confirm CloudWatch resource-tags-for-telemetry is enabled.
3. Test the Metrics Insights query in `GetMetricData` or console.
4. Create the alarm.
5. Confirm the live alarm state reason says the expected number of time series were evaluated, for example `4 time series evaluated to OK`.
6. Trigger or wait for a breach.
7. Call `DescribeAlarmContributors` and confirm contributor attributes include the instance identifier. An OK alarm can legitimately return an empty contributors list.

## Decommissioning legacy static alarms
After a dynamic fleet alarm is live, prefer a two-step decommission for old per-instance human-facing alarms:

1. **Non-destructive alert-path removal first**
   - Keep the legacy `aws_cloudwatch_metric_alarm` resources in Terraform state.
   - Set `actions_enabled = false` and `alarm_actions = []` for redundant static alarms.
   - Verify the plan is in-place only, e.g. `0 to add, N to change, 0 to destroy`.

2. **Physical deletion only with explicit destroy procedure**
   - Many guarded Terraform roots use `lifecycle.prevent_destroy = true` on alarm resources.
   - Simply removing `for_each` entries can produce a correct-looking `N to destroy` plan and then fail on `prevent_destroy`.
   - Terraform `removed` blocks do not support individual `for_each` instance keys such as `resource.name["key"]` as a destroy override.
   - If actual CloudWatch alarm deletion is required, follow the repo's human-operated destroy/replace procedure instead of trying to bypass guardrails in a normal PR.

This preserves observability rollback while stopping duplicate pages.

## Pitfalls
- Do not use SEARCH expressions for alarms.
- Do not assume instance metrics expose `DBClusterIdentifier` as a dimension.
- Do not rely on instance name prefix wildcards unless you verified the query language supports the exact pattern you need.
- Do not assume SNS alarm payloads alone contain sufficient per-contributor detail; enrich via `DescribeAlarmContributors`.
- Do not confuse autoscaling helper alarms with human-facing incident alarms.

## When to prefer automation instead
If tagging cannot be guaranteed, use EventBridge/Lambda automation to:
- detect cluster membership changes
- create/update/delete per-instance alarms

But if tags are available, Metrics Insights alarms are the cleaner AWS-native solution.
