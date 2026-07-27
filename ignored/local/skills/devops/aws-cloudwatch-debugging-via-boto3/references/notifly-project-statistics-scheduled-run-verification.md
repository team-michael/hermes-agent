# Notifly project_statistics scheduled-run verification

Use this when checking whether the daily `project-statistics-etl-workflow` actually processed a target project/window after merge or overnight schedule.

## Key pitfall

Step Functions can show top-level `SUCCEEDED` even when the workflow internally finalized the run as failed. The workflow catches group/Glue errors, writes failure metadata via `finalize-workflow-run`, and then exits normally. Do not trust only `list-executions.status`.

Always inspect execution history and/or control-plane metadata for:

- `FinalizeWorkflowRunFailed`
- `failed_stage=GLUE`
- `group_error=GLUE`
- `Glue.ConcurrentRunsExceededException`
- `groupResults` containing `WorkflowItemFailed`

## Verification sequence

1. Determine the scheduled target window.
   - Daily run at KST morning typically targets previous KST date.
   - For `target_date=YYYY-MM-DD`, PG identity window is usually:
     - `collected_from = previous UTC-hour boundary, e.g. YYYY-MM-(DD-1)_15`
     - `collected_to = YYYY-MM-DD_15`

2. List recent executions for both state machines.
   - `project-statistics-etl-workflow` for daily/all-project schedule.
   - `selected-project-statistics-etl-workflow` for manual/project backfill.

3. Pull `get-execution-history` for the scheduled execution.
   - Extract schedule outputs from `RunHelperLambdaAndScheduleProjectStatistics` / `LambdaFunctionSucceeded` / `TaskStateExited` events.
   - Confirm the target project appears in `ProjectStatisticsSchedules` and record its group/index.

4. Match scheduled projects to Glue runs.
   - Query `aggregate_project_statistics` job runs in the run window.
   - Match by `Arguments['--PROJECT_ID']`, `--TARGET_DATE`, and `--METRIC_TYPE`.
   - Classify per project:
     - `succeeded_loaded`: Glue `SUCCEEDED` and PG row count > 0 for the window.
     - `started_stopped`: Glue run exists but state is `STOPPED`/failed; treat as unsafe even if partial PG rows exist.
     - `not_started`: schedule existed but no Glue run was started.

5. Verify PG output per target project.
   - Read `project_statistics_${project_id}` for `collected_from`/`collected_to`.
   - Count rows and distinct `metric_type`.
   - For `started_stopped`, check row count too: partial rows may have been committed before the workflow aborted, so recovery should use `clear_before_run=true`.

## Interpreting `Glue.ConcurrentRunsExceededException`

If the workflow schedules hundreds of projects and the Map/Glue concurrency is set equal to the Glue job `MaxConcurrentRuns`, a race can still occur:

```text
Step Functions submits many Glue runs concurrently
-> Glue accepts up to its effective slot limit
-> one submit sees no free slot and raises ConcurrentRunsExceededException
-> Map catches/fails the group
-> already-started runs may be stopped/aborted
-> later projects are never submitted
```

This is not a per-project data bug. It is orchestration backpressure: the workflow tried to feed Glue as fast as the Glue account/job limit allowed, with no margin/retry.

## Reporting shape

Lead with a human explanation, then counts:

- scheduled project count
- Glue runs started
- Glue succeeded
- Glue stopped/failed
- not started
- target project status
- PG row count for target window

For stakeholders, avoid saying “Step Functions succeeded” without the internal caveat. Prefer:

> The state machine execution ended green, but internally finalized the run as failed after Glue concurrency errors. The target project was scheduled but never started, so rows are absent.

## Recovery guidance

For missing or partial projects, run selected backfill with:

- `project_id=<target>` or a loop over affected projects
- `start_date=<target_date>`
- `end_date=<target_date + 1 day>`
- `metric_type=all`
- `clear_before_run=true`
- `wait_for_completion=true`

Use `clear_before_run=true` for both `not_started` and especially `started_stopped` projects so partial rows are removed before re-materialization.

## Prevention guidance

- Set workflow `MaxConcurrency` below Glue job/account effective concurrency, not exactly equal.
- Add retry/backoff for `Glue.ConcurrentRunsExceededException` around `glue:startJobRun.sync`.
- Consider batching or queueing rather than submitting all project jobs at once.
