# Notifly project statistics Athena/Glue capacity review

Use this when reviewing a new Notifly data-pipeline job for “will Athena be slow?” or “will Athena quota/rate limits be hit?”, especially for project-level statistics/precompute jobs.

## Key distinction

Do not assume every statistics pipeline consumes Athena DML quota. First inspect the actual code path:

- `scheduler.aws.athena.query`, `start_query_execution`, or SQL submitted to Athena -> Athena DML quota/runtime review applies.
- `GlueContext.create_dynamic_frame.from_catalog(...)` / `CatalogReader.read_table_by_project_time(...)` -> Glue/Spark reads Glue Catalog/S3 partitions; this does **not** consume Athena `StartQueryExecution` DML slots.
- JDBC reads from PostgreSQL -> Athena is not involved; review RDS query/index/concurrency impact instead.

For NOTIFLY-990-style `aggregate_project_statistics`, the implementation shape was:

- dashboard totals/trends: PostgreSQL JDBC aggregate over `users_${projectId}`, `device_${projectId}`, `delivery_result_${projectId}`, `message_events_${projectId}`
- usage input metrics: Glue Catalog read of `notifly_event_logs` Parquet table via `read_event_logs(...)`
- no direct Athena query submission in the new job/scheduler code

So the main risk was **not Athena quota**, but **Glue fan-out + S3 small files + PostgreSQL aggregate load**.

## Review checklist

1. Code path proof
   - Search changed job/scheduler paths for `athena`, `start_query_execution`, and project-specific query helpers.
   - Read the extract path and Glue entrypoint.
   - Identify whether each metric family uses PostgreSQL JDBC, Glue Catalog/S3, or Athena.

2. Athena quota only if Athena is actually used
   - Check region/account identity first.
   - Inspect Service Quotas for `Active DML queries`, `DML query timeout`, and `Active DDL queries`.
   - Inspect workgroups and recent query behavior, but report this as contextual if the new job does not use Athena.

3. Glue/Spark quota and concurrency
   - Read job config: `MaxConcurrentRuns`, `NumberOfWorkers`, `WorkerType`, `Timeout`.
   - Check Glue quotas: max concurrent job runs/account, queued job runs, task DPUs/account.
   - Count scheduled projects. Full project fan-out can create hundreds of Glue runs even if each run reads only one project/day.

4. S3 partition scan volume
   - Confirm Glue table partition keys. For `notifly_event_logs`, observed durable shape: `project_id`, `dt`, `h`, `pre_conversion`.
   - For KST daily jobs, map the target KST day to a UTC hour-key window and estimate object/byte volume for that exact partition window.
   - Watch object count separately from bytes: many tiny Parquet files can dominate Glue/S3 listing/open overhead even when total GiB is modest.

5. PostgreSQL aggregate risk
   - If dashboard metrics read PG per-project tables, inspect indexes on filter columns.
   - `dashboard_total`-style `created_at < end` totals over `users_${projectId}` / `device_${projectId}` may scan large tables if there is no `created_at` index.
   - Check the generated SQL shape, not just the table names. A NOTIFLY-990 implementation that emitted one `UNION ALL` branch per metric produced repeated scans: users 5x, device 9x, delivery_result 2x, message_events 2x for `metric_type=all`. Collapse these into one scan per source family using `COUNT(*) FILTER (...)`, `GROUPING SETS`, or a materialized CTE before raising concurrency.
   - Verify whether the extract uses the writer connection (`Postgresql connection`) or the read-only/reader connection (`Postgresql connection RO`). Dashboard precompute reads should use RO for extract and writer only for the tiny load/upsert step.
   - `delivery_result` may be safer if it has `(event_name, created_at)`; check `message_events` separately.
   - Daily fan-out can concentrate RDS load around KST 00:00; pull writer CPU/DBLoad/IOPS by KST hour. If KST 00 is already hot, prefer low initial concurrency or staggered groups even if the logical target date is the previous KST day.

## Useful AWS probes

Athena quotas:

```bash
aws service-quotas list-service-quotas \
  --service-code athena \
  --region ap-northeast-2 \
  --query "Quotas[?contains(QuotaName, 'DML') || contains(QuotaName, 'DDL') || contains(QuotaName, 'query') || contains(QuotaName, 'active')].{Name:QuotaName,Value:Value,Adjustable:Adjustable,Code:QuotaCode}" \
  --output table
```

Glue quotas:

```bash
aws service-quotas list-service-quotas \
  --service-code glue \
  --region ap-northeast-2 \
  --query "Quotas[?contains(QuotaName, 'concurrent') || contains(QuotaName, 'Concurrent') || contains(QuotaName, 'DPU') || contains(QuotaName, 'jobs') || contains(QuotaName, 'job')].{Name:QuotaName,Value:Value,Adjustable:Adjustable,Code:QuotaCode}" \
  --output table
```

Glue table partition shape:

```bash
aws glue get-table \
  --database-name notifly_analytics \
  --name notifly_event_logs \
  --region ap-northeast-2 \
  --query 'Table.{Name:Name,Location:StorageDescriptor.Location,InputFormat:StorageDescriptor.InputFormat,PartitionKeys:PartitionKeys[].Name}' \
  --output json
```

Project count:

```bash
aws dynamodb scan \
  --table-name project \
  --select COUNT \
  --region ap-northeast-2 \
  --query '{Count:Count,ScannedCount:ScannedCount}' \
  --output json
```

## Interpretation template

Lead with the direct answer:

```text
Athena quota/rate limit is not the blocker if the new job does not call Athena StartQueryExecution.
The real capacity risks are Glue fan-out, S3 small-file scan overhead, and PostgreSQL aggregate load.
```

Then separate evidence buckets:

- code path: Athena vs Glue Catalog vs JDBC
- account quota: Athena, Glue
- current usage: active queries/runs, recent runtimes if inspected
- data volume: project count, active projects, S3 bytes/objects for the target window
- operational recommendation: canary/shadow run, MaxConcurrency cap, top-volume project checks, RDS metrics to watch

## Project metadata generator comparison

When the user asks whether `project-metadata-generator` already does PostgreSQL work, check `services/lambda/project-metadata-generator` before answering.

Durable observed shape:

- `index.js` runs two collectors:
  - `getRecentEventListMappedByProjectId()` from `lib/athena.js` -> Athena over `notifly_event_logs` for recent event names.
  - `getRecentUserPropertyFieldNamesMappedByProjectId()` from `lib/db.js` -> PostgreSQL over per-project user tables.
- The PG query is deliberately small/sampling-like:
  - `users_${projectId}` / legacy `user_${projectId}`
  - `updated_at >= now - 1h`
  - `LIMIT 1500`
  - `pLimit(10)` concurrency across projects
  - query goes through `@notifly/userdb.executeQueryWithShadowing`, which executes the encrypted `users_${projectId}` shadow query and decrypts/normalizes rows.
- Do not equate this with daily full-project dashboard precompute. The metadata-generator PG workload samples recent user-property keys; project-statistics dashboard precompute may aggregate large `users_*`, `device_*`, `delivery_result_*`, and `message_events_*` tables and needs a separate RDS capacity review.

## Use project-metadata-generator as a PG load baseline

When asked whether a new project-statistics task is safe because `project-metadata-generator` already runs PostgreSQL queries, compare **query shape and peak concurrency**, not just the fact that both touch PG.

Observed durable pattern for `project-metadata-generator`:

- Event metadata path uses Athena over `notifly_event_logs`.
- User-property metadata path uses PG via `services/lambda/project-metadata-generator/lib/db.js`.
- It scans project ids, then queries each project table with `pLimit(10)`.
- Query shape is recent-window sampling:
  - `users_${projectId}` / legacy `user_${projectId}` only
  - `updated_at >= now - 1h`
  - `LIMIT 1500`
  - `jsonb_object_keys(...)`
- Runtime is hourly EventBridge; Lambda timeout/memory can be read from Terraform, and REPORT logs give a real baseline. In the NOTIFLY-990 review, recent runs were roughly p50 7–8 min, p95 8–10 min, max ~11 min under 900s timeout with no errors/throttles.

Interpretation pattern:

- Existing generator stability does **not** imply a new daily aggregate is safe.
- Generator is many small-ish recent-window queries at concurrency 10.
- A project-statistics job can be fewer queries per day but much higher peak pressure if it scans several large per-project tables and runs with Glue concurrency 100–200.
- Compare rough peak pressure as:
  - existing: `10 concurrent PG queries × 1 recent-window users-table sample`
  - new: `N concurrent Glue jobs × repeated source-table scans per project`
- If EXPLAIN shows repeated scans for one logical project query, treat each scan as a separate pressure unit until the SQL is consolidated.

Useful NOTIFLY-990 finding to preserve:

- The initial `metric_type=all` query shape produced repeated scans: users 5x, device 9x, delivery_result 2x, message_events 2x.
- With `MaxConcurrentRuns=200`, this is not comparable to project-metadata-generator’s `pLimit(10)` even though the new job runs daily instead of hourly.
- Recommendation: use project-metadata-generator as an existence proof that small recent-window PG metadata queries are acceptable, not as proof that full-project dashboard aggregates are safe.

## Recommended rollout for full-project daily stats

- Do not start with maximum configured concurrency just because quotas allow it.
- First collapse repeated PG scans per project where possible:
  - users totals in one scan using `COUNT(*) FILTER (...)`
  - device totals in one scan using `COUNT(*) FILTER (...)`
  - delivery/message daily totals using one materialized source and grouped/channel+total aggregation where practical
- Use RO/read-replica connection for extract reads; reserve writer for the tiny load/upsert step.
- Start with a small canary: top-volume projects plus several normal projects.
- Then run a limited full-project pass with lower `MaxConcurrency`/map concurrency, e.g. 10–20 for PG-heavy dashboard metrics and 50–100 only after observing headroom.
- If usage/S3 metrics and PG dashboard metrics share one job, consider splitting or separately gating their concurrency; S3/Glue-safe concurrency is not automatically RDS-safe concurrency.
- Observe:
  - Glue `ExecutionTime`, failure rate, queueing
  - S3 object/byte read behavior
  - RDS CPU, ReadIOPS/WriteIOPS, DBLoad, lock/latency symptoms
  - API p95 latency during the batch window
  - p95/p99 job duration by project
- Only then raise concurrency.
