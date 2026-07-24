# Notifly project-statistics scheduled-run triage

Use this when checking whether `aggregate_project_statistics` ran overnight and whether a specific project, such as class101 prod, actually got rows.

## Core lesson

Do not trust only the Step Functions top-level execution status. The project-statistics workflow can end as top-level `SUCCEEDED` while its own control-plane metadata is finalized as `FAILED` because the ASL catches group failures and returns a success-shaped terminal state.

The real pass/fail evidence is the combination of:

1. scheduled state machine history/output
2. Glue job runs filtered by `--PROJECT_ID` and `--TARGET_DATE`
3. PostgreSQL `project_statistics_${project_id}` rows for the collected window

## Expected window

For the daily KST run at KST 08:30-ish:

```text
KST today = D
expected target_date = D - 1
collected_from = target_date 00:00 KST converted to UTC hour key
collected_to = target_date + 1 day 00:00 KST converted to UTC hour key
```

Example:

```text
KST today: 2026-07-03
target_date: 2026-07-02
collected_from: 2026-07-01_15
collected_to: 2026-07-02_15
```

## AWS checks

Check scheduled workflow executions around the KST run window:

```bash
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:ap-northeast-2:702197142747:stateMachine:project-statistics-etl-workflow \
  --max-results 100
```

Then fetch history for the candidate execution:

```bash
aws stepfunctions get-execution-history \
  --execution-arn "$EXECUTION_ARN" \
  --max-results 1000
```

Look for:

- `FinalizeWorkflowRunFailed`
- `failure_context.failed_stage = GLUE`
- `groupResults[].group_error = GLUE`
- `Glue.ConcurrentRunsExceededException`
- generated `ProjectStatisticsSchedules` containing the target project id

A common failure mode:

```text
workflow starts
-> scheduler builds hundreds of project schedules
-> Glue Map submits up to MaxConcurrency
-> Glue.ConcurrentRunsExceededException occurs
-> remaining Map items are aborted
-> target project may be in the schedule list but never get a Glue run
-> no rows are written for that project/window
```

Check Glue job runs by project/date, not just global run counts:

```bash
aws glue get-job-runs --job-name aggregate_project_statistics --max-results 200
```

Filter each `JobRun` by:

```text
Arguments["--PROJECT_ID"] == target project id
Arguments["--TARGET_DATE"] == target date
JobRunState == SUCCEEDED
```

If there is no matching run, the project was not executed even if the workflow created a schedule entry.

## PostgreSQL verification

Read scheduler Lambda env for DB connection values if the shell does not expose `DB_*`. Do not print secrets.

For class101 prod:

```text
project_id = b2b4a8f879a75673b755bff42fc1deb6
table = project_statistics_b2b4a8f879a75673b755bff42fc1deb6
```

Query rows for the expected collected window:

```sql
SELECT metric_type,
  COUNT(*) AS rows,
  COALESCE(SUM(count), 0) AS summed_count,
  MIN(created_at) AS created_min,
  MAX(created_at) AS created_max
FROM project_statistics_${project_id}
WHERE collected_from = :collected_from
AND collected_to = :collected_to
GROUP BY metric_type
ORDER BY metric_type;
```

Also query the previous window as a sanity check. If target window is zero rows but previous window has the expected 8 metric families, the issue is the latest scheduled execution, not table absence.

## Interpretation

- SFn top-level `SUCCEEDED` + internal `FinalizeWorkflowRunFailed` + no matching Glue run + zero PG rows => problem; scheduled workflow did not process the target project.
- Matching Glue `SUCCEEDED` + zero PG rows => load/output issue; inspect Glue logs and table constraints.
- Matching Glue absent but project present in schedule list => orchestration/concurrency/Map abort issue.
- Project absent from schedule list => scheduler project-selection issue.

## Likely remediation for ConcurrentRunsExceeded

Running exactly at Glue `MaxConcurrentRuns` is brittle. Lower Step Functions `MaxConcurrency`, reduce group fan-out, or add retry/backoff for `Glue.ConcurrentRunsExceededException`. A selected backfill for the specific project/date can restore missing rows:

```text
project_id=<target project>
start_date=<target_date>
end_date=<target_date + 1 day>
metric_type=all
clear_before_run=true
wait_for_completion=true
```

Use the GitHub Actions workflow when available:

```bash
HOME=/home/ubuntu gh workflow run manual_execute_project_statistics_backfill.yml \
  --repo team-michael/notifly-event-data-pipeline \
  --ref main \
  -f project_id='<target project>' \
  -f start_date='<target_date>' \
  -f end_date='<target_date + 1 day>' \
  -f metric_type='all' \
  -f clear_before_run='true' \
  -f wait_for_completion='true'
```

If the request comes from a Slack alert thread and the operator asks for “same handling,” parse the permalink/channel/thread timestamp and pass completion callback inputs too, so the workflow posts back into the same operational thread:

```bash
HOME=/home/ubuntu gh workflow run manual_execute_project_statistics_backfill.yml \
  --repo team-michael/notifly-event-data-pipeline \
  --ref main \
  -f project_id='<target project>' \
  -f start_date='<target_date>' \
  -f end_date='<target_date + 1 day>' \
  -f metric_type='all' \
  -f clear_before_run='true' \
  -f channel_id='<slack_channel_id>' \
  -f thread_ts='<slack_thread_ts>' \
  -f wait_for_completion='true'
```

For Slack permalinks like `/archives/C06MPST0BEK/p1783035124910439`, convert `p1783035124910439` to `thread_ts=1783035124.910439` unless the actual thread root ts is visible in the platform context. Prefer the provided root/thread context when available.

Control-plane nuance observed for project-statistics failures:

- `[Control Plane] Manual Repair Actions` exists, but `release-stale-workflow-item` only applies to `LOCKED`/`RUNNING` stale leases, and `mark-workflow-run-failed` only applies to `RUNNING` runs.
- If the failed item is already terminal `FAILED`, do **not** force a repair action just to clear it. The selected project-statistics backfill can reacquire the same deterministic `input_hash` after the old lease is stale, increment `attempt_count`, update the item `run_id` to the selected backfill execution, and finalize it as `SUCCEEDED`.
- After such a successful rerun, `statistics_control_plane_items.last_error_code` / `last_error_message` may still contain the previous failure. Treat `status=SUCCEEDED`, `attempt_count`, `glue_job_run_id`, Step Functions `ExecutionSucceeded`, and Glue `JobRunState=SUCCEEDED` as current truth; do not report stale `last_error_message` as the active failure.
- Verify downstream, not just Actions success: GitHub Actions success -> selected Step Functions execution `SUCCEEDED` -> Glue job run `SUCCEEDED` -> PostgreSQL `project_statistics_<project_id>` rows for the KST-derived UTC window, e.g. target_date `2026-07-02` means `collected_from=2026-07-01_15`, `collected_to=2026-07-02_15`.
- In the final Slack reply for a same-thread repair, keep it short and evidence-first: same pattern verdict, project/product mapping, backfill run URL, selected Step Functions status, Glue run id/state, and compact PG row counts by `metric_type`. Avoid over-explaining Step Functions internals unless the operator asks why.

### Exact `RunAggregationDefault` concurrency-edge diagnostic

For `project-statistics-etl-workflow` alerts whose failed state is `RunAggregationDefault` and reason is `ConcurrentRunsExceededException`, prove whether Glue started or failed before job creation:

1. In Step Functions history, inspect the item sequence around the failed project:
   - `AcquireWorkflowItemLease` / `LambdaFunctionSucceeded` should return `should_execute=true` and an `input_hash`.
   - `TaskScheduled` for `glue:startJobRun.sync` should show `JobName=aggregate_project_statistics` plus `--PROJECT_ID`, `--TARGET_DATE`, `--METRIC_TYPE`.
   - If `TaskStarted` is followed by `TaskFailed` with `Glue.ConcurrentRunsExceededException` and no `TaskStateExited` containing `glueJob.Id`, the Glue script never ran; failure happened at job submission.
2. Compare Step Functions fan-out to Glue job capacity:
   - Current observed shape: outer `ProcessGroups MaxConcurrency=2` and inner `RunParallellyProjectStatistics MaxConcurrency=25` can submit `2*25=50` jobs.
   - `aggregate_project_statistics.ExecutionProperty.MaxConcurrentRuns=50` gives zero headroom, so transient active-run accounting can reject later submissions even if some runs are about to finish.
3. Check `get-job-runs` for the target project/date:
   - `same_project_runs=0` means no Glue run was created for that project/window.
   - Neighboring runs may be `SUCCEEDED` or `STOPPED`; do not infer target success from global job activity.
4. Verify PostgreSQL rows for the project table/window after AWS triage:
   - `project_statistics_${project_id}` should have rows for `collected_from=<target_date 00:00 KST as UTC hour key>` and `collected_to=<next day 00:00 KST as UTC hour key>`.
   - If target window is zero and previous window has rows, this is a missed scheduled execution for that window, not a missing table.

Interpretation wording: “ETL transform/load did not fail; Glue job submission failed before the script started because orchestration fan-out hit Glue concurrent-run capacity.”
