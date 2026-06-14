---
name: github-actions-log-debugging
description: Inspect GitHub Actions job failures and logs without gh CLI, including the signed-blob redirect behavior on the logs endpoint.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [GitHub, Actions, CI, Debugging, Logs]
    related_skills: [github-pr-workflow, github-code-review]
---

# GitHub Actions Log Debugging

Use when a PR/job/check failed and `gh` is unavailable or inconvenient.

## When to use
- Need to inspect a failed GitHub Actions job from a PR/check URL
- Need job logs via API
- Need to determine whether failure is build/deploy/auth/health-check

## Core gotcha
`GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs` often returns a **302 redirect** to a signed blob-storage URL.

Important consequence:
- The initial GitHub API request needs `Authorization`
- The redirected blob URL should be fetched **without** the GitHub `Authorization` header
- Some HTTP clients that blindly preserve auth across redirects can get **401** on the redirected URL

`curl -L` usually handles this correctly. Custom Python/urllib code may need manual redirect handling.

## Inputs you usually have
- Run URL or job URL, e.g. `.../actions/runs/<run_id>/job/<job_id>?pr=<pr>`
- Repo owner/name
- GitHub token in env or local secret store

## Investigation recipe

For manually-triggered operational workflows (`workflow_dispatch`) that run production scripts, also use `references/workflow-dispatch-operational-scripts.md`. It covers comparing nearby dispatch runs, reading the workflow at the failing SHA, checking optional-input CLI rendering, and separating direct CI failure from live application-state conflicts.

**Notifly/Hermes pitfall:** do not treat the local Hermes VM as the real workflow runtime for checks that depend on GitHub secrets, VPN routing, runner network, AWS/RDS reachability, or production-like environment variables. Local checks are good for unit tests, typecheck, actionlint, static scans, and shell/YAML syntax. If the behavior requires actual environment access, validate it by dispatching the workflow on the target branch and inspecting run logs/status. In reports, separate "local code gates passed" from "workflow runtime verified".

### 1. Fetch job metadata
Use the job API first to learn which step failed.

```bash
curl -s \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$OWNER/$REPO/actions/jobs/$JOB_ID"
```

Look at:
- `status`
- `conclusion`
- `steps[].name`
- `steps[].conclusion`

### 2. Fetch logs
#### Preferred: curl
```bash
curl -L -s \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$OWNER/$REPO/actions/jobs/$JOB_ID/logs"
```

#### Python/urllib fallback
If redirect auth handling is broken, do it manually:
1. Request the logs endpoint with a no-redirect opener
2. Read the `Location` header from the 302
3. Fetch that blob URL **without** the GitHub auth header

Sketch:
```python
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

opener = urllib.request.build_opener(NoRedirect)
req = urllib.request.Request(api_logs_url, headers=github_headers)
try:
    opener.open(req)
except urllib.error.HTTPError as e:
    signed_url = e.headers['Location']
    with urllib.request.urlopen(signed_url) as r:
        text = r.read().decode('utf-8', errors='replace')
```

## 3. Identify the actual failing layer
Distinguish these cases:
- **Auth/config failure**: deploy/login step fails immediately with explicit unauthorized/forbidden errors
- **Deploy success, readiness failure**: deploy step succeeds, later health check or smoke test times out
- **Build/test failure**: compile/test/lint step fails before deploy

For deploy workflows, always check whether the deploy step itself succeeded before blaming tokens.

## 3b. The real error may be in a PR comment, not the run log

Some workflows redirect a step's stdout/stderr to a file (`terraform plan … > plan.stdout.txt 2> plan.stderr.txt`) and then upsert that captured output into a **bot PR comment** via `actions/github-script`, while the job step itself only sets an outcome var and `exit 0`s. The final job failure then comes from a separate `Fail leg if checks or apply errored` step that just runs `exit 1` based on an outcome var — so the raw run log shows only `exit 1` with no diagnostic.

In that case the actual error text lives in the upserted PR comment, keyed by an HTML marker like `<!-- terraform:plan:<root> -->`, usually inside a `<details><summary>Plan output</summary>` block. Fetch it from the issue comments API:

```bash
gh api "repos/$OWNER/$REPO/issues/$PR/comments" --jq '.[].body' > /tmp/pr_comments.txt
# then grep for: Error:, prevent_destroy, "will be destroyed", ❌, "failed"
```

Tell-tale that you're in this pattern: a step named like "Fail leg …" / "Fail if …" is the failing one, the actual build/plan/test step shows `success` or no useful output, and the workflow uses `> file.txt` redirection + a `github-script` comment upsert. Read the comment before concluding the underlying step "passed".

Beware misleading summary fields: if the captured tool exits non-zero, downstream parse steps may fall back to zeroed/empty summaries (e.g. a destructive-change detector reporting `destroy=0` because the plan JSON was never produced). Don't trust a "0 changes / not destructive" summary when the upstream step failed.

## 4. Correlate with workflow definition
- required secrets/env names
- deploy command
- post-deploy health-check logic
- timeout settings
- whether stderr is swallowed with `|| true` or `curl -s`

This often explains why logs look sparse.

## 5. Compare against the previous red baseline
When `main` is already red, do not treat the current run's full failure list as caused by the latest change. First compare failed test IDs against the nearest prior `main` failure:

```bash
cache="$HOME/.hermes/cache/gha-compare-$NEW_RUN"
mkdir -p "$cache"
gh run view "$NEW_RUN" --repo "$OWNER/$REPO" --job "$NEW_JOB" --log > "$cache/new.log"
gh run view "$OLD_RUN" --repo "$OWNER/$REPO" --job "$OLD_JOB" --log > "$cache/old.log"
grep -E 'FAILED tests/.*::' "$cache/new.log" | sed -E 's/.*FAILED (tests\/[^ ]+).*/\1/' | sort -u > "$cache/new.tests"
grep -E 'FAILED tests/.*::' "$cache/old.log" | sed -E 's/.*FAILED (tests\/[^ ]+).*/\1/' | sort -u > "$cache/old.tests"
comm -13 "$cache/old.tests" "$cache/new.tests"   # newly introduced failures
comm -23 "$cache/old.tests" "$cache/new.tests"   # resolved/disappeared failures
```

Report new vs pre-existing failures separately. Fix the newly introduced failures first; if the run still fails only because of pre-existing baseline failures, say so explicitly instead of implying the latest patch is fully green.

### CI flake pattern: monotonic-time debounce
Tests that call debounce/rate-limit helpers soon after process start can fail if production code uses `dict.get(key, 0.0)` and compares `time.monotonic() - last < cooldown`: missing state looks like a timestamp at process start, so early tests think the first event is still cooling down. Prefer `last = store.get(key)` and check `last is not None` before applying the cooldown. In tests, monkeypatch `time.monotonic` to a small fixed value to prove missing state is still sendable.

### CI drift pattern: live recommendation defaults
If tests are meant to verify routing/credential selection, mock live model recommendation functions. Otherwise changing service-side defaults (e.g. provider recommended auxiliary model rotating from one model ID to another) makes unrelated tests fail. Keep separate tests for the actual recommendation path.

### CI hang pattern: Jest finished but Node stays alive
If a JS service CI step takes 30+ minutes but the log says `Test Suites: ... passed`, `Time: 20s`, then `Jest did not exit one second after the test run has completed`, compare the test runner's reported time with the enclosing task/workflow step time. A large gap means the tests finished; Node is waiting on referenced handles. Inspect new code/tests for long `setTimeout`/`setInterval`, servers, Redis/DB clients, or streams whose cleanup depends on abort events that may not fire in `app.request()`/unit-test environments. For production long-lived timers attached to sockets/SSE, prefer `timer.unref?.()` so they do not keep CI/test processes alive; verify with a minimal child-process repro that exits only after timers are unref'ed. Avoid `jest --forceExit` as the primary fix because it masks real handle leaks. For a concise SSE-specific repro/test recipe, see `references/jest-open-handle-sse-timers.md`.

Verification nuance: after an `unref()` fix, success is not necessarily "no Jest warning". Re-query both the PR check and the merge-commit/main run, then compare the api-service job duration before vs after. If the job drops from ~30m to ~2m but the `Jest did not exit...` warning remains, report this split explicitly: the long-duration regression is fixed, but at least one residual open handle remains as follow-up cleanup.

## Practical pattern from Cloudflare preview debugging
If logs show:
- env contains masked Cloudflare token/account id
- `wrangler deploy` succeeded
- repeated `Not ready yet` / empty health responses
- final timeout in `Health check`

Then root cause is **not missing Cloudflare credentials**. It's a **post-deploy readiness/health-check failure** (route propagation, app not ready, endpoint not responding, or poor observability in the curl command).

## PR closeout after long-running checks
When a background `gh pr checks --watch` or polling process completes, do not rely only on its final notification text. It may be truncated or contain partial/malformed output. Re-query live GitHub state before reporting completion.

For the full repair loop after a PR check fails, see `references/pr-check-repair-loop.md`. Key pitfall: `gh pr checks` exits non-zero while checks are pending/failing, so polling scripts must capture output with `|| true` and inspect states explicitly; otherwise the script exits before it can observe the next check transition.

Re-query live GitHub state before reporting completion:

```bash
gh pr checks "$PR" --repo "$OWNER/$REPO" \
  --json name,state,workflow,link \
  --jq '[.[] | {name,state,workflow,link}] | sort_by(.workflow,.name)'

gh pr view "$PR" --repo "$OWNER/$REPO" \
  --json headRefOid,mergeStateStatus,reviewDecision,statusCheckRollup \
  --jq '{headRefOid,mergeStateStatus,reviewDecision,checks:[.statusCheckRollup[]? | {name:.name,status:.status,conclusion:.conclusion,workflowName:.workflowName}]}'
```

Report CI/check status separately from branch-protection status. A PR can be fully green (`SUCCESS`/expected `SKIPPED`) while still `mergeStateStatus: BLOCKED` because `reviewDecision: REVIEW_REQUIRED`. In that case say: code/CI is green; remaining blocker is review approval, not a failing check.

## Recommended report format
- Job name / URL
- Failed step
- Whether credentials were present in CI env
- Whether deploy command succeeded
- Exact terminal failure condition (timeout, 404, TLS, empty response, bad SHA, etc.)
- Most likely root cause layer
- Optional next instrumentation step
- For PR closeout: check summary, head SHA, worktree cleanliness, `mergeStateStatus`, and `reviewDecision`

## Common follow-up improvement
If health-check logs are uninformative, patch workflow commands to surface the failure mode:
- prefer `curl -Ssv` during debugging
- print HTTP status / headers / body prefix
- avoid swallowing stderr too early
- log the exact URL and expected revision/SHA
