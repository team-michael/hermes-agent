# Aurora Optimized Reads cache hit ratio after large index backfills

Use when a Notifly/RDS alert is `Low Aurora pg Optimized cache hit ratio` / metric `AWS/RDS AuroraOptimizedReadsCacheHitRatio`, especially after adding indexes across many per-project PostgreSQL tables.

## Mental model

This alert is not the same as “CPU is high” or “a query is slow.” It means the Optimized Reads local cache hit ratio is low. Large index creation and later write-heavy maintenance can legitimately lower it:

- `CREATE INDEX [CONCURRENTLY]` scans large table heaps and writes btree pages, making the local cache cold.
- A newly added secondary index on write-hot tables adds btree maintenance on every `INSERT`/`UPSERT`/`UPDATE`.
- For Notifly EIC tables, `event_intermediate_counts_<projectId>` is write-heavy, so a broad `(notifly_user_id, name, dt)` index rollout can create ongoing write/IO amplification even after the DDL finishes.
- The alarm may be noisy if configured as `Period=3600`, `EvaluationPeriods=1`, `DatapointsToAlarm=1`, threshold `<=30`; one borderline hourly datapoint can page.

## Investigation checklist

1. Parse the Slack/Amazon Q alert:
   - alarm name
   - `DBClusterIdentifier`
   - metric value and timestamp
   - alarm period/evaluation config

2. Read live alarm config and history:
   - `describe_alarms(AlarmNames=[...])`
   - `describe_alarm_history(... HistoryItemType='StateUpdate'/'Action'/'ConfigurationUpdate')`
   - Count actual user-visible notification actions, not just state updates.

3. Reconstruct the metric around the alert:
   - `get_metric_statistics` for `AWS/RDS/AuroraOptimizedReadsCacheHitRatio`
   - Use the same dimensions/period as the alarm for exact transitions.
   - Also inspect minute-level data around the window to see whether the hourly average hid repeated short drops.

4. Check whether index builds are still active:
   ```sql
   select now() as checked_at, pid, datname,
          relid::regclass as table_name,
          index_relid::regclass as index_name,
          phase, blocks_total, blocks_done,
          round(100.0*blocks_done/nullif(blocks_total,0),2) as pct_blocks
   from pg_stat_progress_create_index;
   ```
   If empty, do not say “index creation is currently running.” Shift to post-DDL write/IO amplification analysis.

5. Measure the footprint of the new index family:
   ```sql
   with idx as (
     select c.oid, c.relname as index_name, t.relname as table_name,
            pg_relation_size(c.oid) as bytes,
            coalesce(si.idx_scan,0) as idx_scan,
            coalesce(si.idx_tup_read,0) as idx_tup_read
     from pg_class c
     join pg_index i on i.indexrelid = c.oid
     join pg_class t on t.oid = i.indrelid
     left join pg_stat_user_indexes si on si.indexrelid = c.oid
     where c.relname like 'eic_user_name_dt_idx_%'
   )
   select count(*) as idx_count,
          pg_size_pretty(sum(bytes)) as total_size,
          sum(idx_scan) as total_idx_scan,
          sum(idx_tup_read) as total_idx_tup_read
   from idx;
   ```

   For top-heavy rollouts also list largest indexes and their scans:
   ```sql
   with idx as (
     select c.relname as index_name, t.relname as table_name,
            pg_relation_size(c.oid) as bytes,
            coalesce(si.idx_scan,0) as idx_scan,
            coalesce(si.idx_tup_read,0) as idx_tup_read
     from pg_class c
     join pg_index i on i.indexrelid = c.oid
     join pg_class t on t.oid = i.indrelid
     left join pg_stat_user_indexes si on si.indexrelid = c.oid
     where c.relname like 'eic_user_name_dt_idx_%'
   )
   select table_name, index_name, pg_size_pretty(bytes) as size, idx_scan, idx_tup_read
   from idx
   order by bytes desc
   limit 10;
   ```

6. Compare benefit vs cost:
   - If large new indexes have `idx_scan=0` or very low scans, the read benefit may not yet justify write maintenance cost.
   - Check `pg_stat_database.stats_reset` before over-interpreting scan counters.
   - Compare total heap size vs all-index size vs new-index size for the table family.

7. Pivot to the exact writer and PI:
   - `describe_db_clusters` to identify writer.
   - Performance Insights on writer and readers around the alert.
   - Look for top SQL involving `event_intermediate_counts_* INSERT ... ON CONFLICT` and wait events like `IO:XactSync`, `IO:DataFileRead`, `IO:AuroraOptimizedReadsCacheRead`.
   - If writer top SQL is EIC upserts, frame the hypothesis as write/IO amplification from maintaining the extra index, not necessarily a single slow read query.

8. Correlate with user-impact metrics before calling it an incident:
   - DBLoad / CPU / ReadIOPS / WriteIOPS / latencies
   - API/Lambda p95/p99 latency
   - EIC insert/upsert latency or queue lag
   - application errors / timeouts

9. Verify the metric dimensions before interpreting which host is affected:
   - `AuroraOptimizedReadsCacheHitRatio` may be visible on reader instances and cluster/role dimensions while absent on the writer instance.
   - Pull per-`DBInstanceIdentifier`, `DBClusterIdentifier`, and if present `Role=READER` datapoints before saying "writer cache hit ratio is low."
   - If Performance Insights shows write-heavy SQL on the writer while the cache-ratio metric is reader/cluster scoped, phrase the relationship carefully: writer-side index maintenance can contribute to cluster I/O/cache pressure, but the alarm's datapoints may be from readers or aggregated cluster dimensions.

## Alarm tuning pattern

For `AuroraOptimizedReadsCacheHitRatio`, avoid treating AWS's suggested monitoring as a fixed paging threshold. The metric is a cache-efficiency signal; AWS documentation gives the formula but no universal good/bad threshold.

Practical Notifly pattern after broad EIC index rollout:

- A config like `Threshold <= 30`, `Period=3600`, `EvaluationPeriods=1`, `DatapointsToAlarm=1` is prone to flapping when hourly averages hover around 30%.
- Prefer persistence over simply raising/lowering by guess:
  - warning-only: `<=25%`, 1h period, `3/6`
  - critical/page: `<=20%`, 1h period, `3/6`, and only as a composite with latency/I/O/DBLoad deterioration
- Good composite companions:
  - `ReadLatency` / `WriteLatency`
  - `VolumeReadIOPs` / `VolumeWriteIOPs`
  - `DBLoad`, `DBLoadCPU`, `DBLoadNonCPU`
  - Performance Insights top waits / top SQL
  - API/Lambda p95/p99 latency, queue lag, or error rate
- Use `treat_missing_data = "missing"` unless there is a reason to convert missing datapoints into OK or ALARM.
- Rename alarms to reflect scope and severity, e.g. `notifly-db-prod-reader-low-optimized-reads-cache-hit-ratio-warning`, rather than a generic low-cache-hit page.

When proposing settings, show the observed distribution first: min/p10/p25/p50/max and count of hourly datapoints below candidate thresholds (`<=30`, `<=25`, `<=20`). This makes the tradeoff explicit: threshold defines "how bad," while `datapoints_to_alarm/evaluation_periods` defines "how persistent."

## Reporting pattern

Use this shape:

- Verdict: likely related / unlikely / needs more evidence
- Causal path:
  - index build scan/write if still running, or
  - post-build btree maintenance/write amplification if builds are complete
- Evidence:
  - alarm config/history/frequency
  - cache hit datapoints
  - `pg_stat_progress_create_index` result
  - new index count/size and scan counters
  - PI top SQL/waits on writer
- Impact:
  - separate cache-ratio warning from actual user-facing latency/errors
- Action:
  - no active index build to stop, if true
  - tune alarm persistence if it is noisy (`1/1` -> e.g. `2/3`) only after checking impact
  - consider partial/high-impact-project rollout or dropping unused huge indexes if usage remains low

## Pitfalls

- Do not attribute the alert to the template PR if the template only affects new projects; the broad existing-table backfill is the relevant side effect.
- Do not claim the DDL is still running without `pg_stat_progress_create_index` evidence.
- Do not treat DLQ/CPU/error alarms and Optimized Reads cache-hit alarms as the same class; this metric is a cache/I/O pressure signal.
- Do not recommend dropping indexes solely from low scan counts if stats were recently reset or the feature has not yet exercised the read path.
