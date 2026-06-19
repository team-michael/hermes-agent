# Workflow-dispatch operational script failures

Use this reference when a manually-triggered GitHub Actions workflow fails while running an operational script against production state (for example payment/product/admin scripts).

## Lessons from Notifly payment-by-credits investigation

Observed pattern:
- The workflow build/install/compile steps can all pass, while the final operational script step fails because of live application state.
- Recent runs of the same workflow may fail for different reasons as state changes between attempts.
- Workflow input rendering can introduce a separate failure: optional numeric inputs emitted unconditionally can produce malformed CLI invocations such as `--cap-months --requester "..."`.

Recommended investigation sequence:
1. Inspect run metadata and jobs with structured output:
   ```bash
   gh run view <run_id> -R <owner>/<repo> --json databaseId,name,event,headBranch,headSha,status,conclusion,createdAt,updatedAt,url,jobs
   ```
2. Prefer the failed-step log first to avoid truncation noise:
   ```bash
   gh run view <run_id> -R <owner>/<repo> --log-failed
   ```
   If needed, inspect the specific failed job:
   ```bash
   gh run view <run_id> -R <owner>/<repo> --job <job_id> --log
   ```
3. List nearby dispatch runs for the same workflow to detect progression across attempts:
   ```bash
   gh api 'repos/<owner>/<repo>/actions/runs?per_page=30&event=workflow_dispatch' \
     --jq '.workflow_runs[] | select(.name=="<workflow name>") | {id,status,conclusion,created_at,head_branch,head_sha,url:.html_url}'
   ```
4. Read the exact workflow file at the failing SHA, not just `main`, because manual dispatches may run old/new revisions:
   ```bash
   gh api 'repos/<owner>/<repo>/contents/<path>?ref=<head_sha>' --jq '.content' | base64 -d
   ```
5. Trace the script code around the failing stack frame and identify validation order. For operational scripts, distinguish:
   - CLI parsing/input rendering failure
   - missing product/account/entity validation
   - existing state conflict (e.g. "already exists")
   - external provider/API failure
6. If the script reads/writes production state, only perform read-only lookups unless the user explicitly authorizes mutation. Redact secrets and do not echo credentials.
7. Report both the direct failure and the operational implication. Example: "Direct failure is `Payment already exists`; the implication is that rerunning this initiate workflow will keep failing until existing payment state is changed or a different workflow is used."

## What to include in the final report
- Run URL, workflow name, job/step, actor if useful
- Exact error line and stack frame, not just "failed"
- Whether build/test/setup succeeded before the operational step
- The command the workflow attempted to run, with secrets redacted
- Relevant current application state from read-only checks
- Whether retrying as-is will help
- Safe next options, explicitly separating read-only/retry actions from destructive production mutations

## Pitfalls
- Do not treat GitHub Actions deprecation warnings as the root cause unless they actually fail the job.
- Do not assume the latest run has the same cause as earlier runs; compare the sequence.
- Do not run drop/update/migrate workflows in production while investigating unless the user explicitly approves that specific mutation.
- For Notifly API credential operations, distinguish Cognito auth from service-local credential checks. A workflow that only runs `aws cognito-idp admin-set-user-password` can make `api-service` `/authenticate` pass while `integration-service` still rejects Basic Auth, because some integration paths compare the incoming credentials against `project.cognito_api_auth` loaded from DynamoDB/Redis rather than calling Cognito. When investigating this split, inspect the workflow body, then check whether `project.cognito_api_auth` was updated and whether the `project` cache was invalidated. See `references/notifly-mixpanel-cohort-auth-split.md` for the Mixpanel cohort case.
