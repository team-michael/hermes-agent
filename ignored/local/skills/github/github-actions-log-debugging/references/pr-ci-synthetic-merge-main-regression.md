# PR CI failure caused by newly merged `main` changes

Use this when a PR was green earlier, then starts failing after unrelated changes land on `main`.

## Mechanism

GitHub `pull_request` checks usually run against a synthetic merge of:

- the PR head, and
- the current base branch tip (`main`)

So a failure can appear on an unchanged PR when `main` gains a new regression. This is especially confusing after rebases/force-pushes because the failed check is shown on the PR, but the root cause may be a commit that recently landed on `main`.

## Investigation pattern

1. Identify the failed run head SHA and failed job/step.

```bash
gh api repos/OWNER/REPO/actions/runs/RUN_ID \
  --jq '{event,head_branch,head_sha,display_title,run_attempt}'

gh api repos/OWNER/REPO/actions/jobs/JOB_ID \
  --jq '{name,head_sha,run_id,steps:[.steps[] | select(.conclusion=="failure") | {name,number,conclusion}]}'
```

2. Save the full failed job log under `~/.hermes/...` and search for the actual compiler/test error, not just the failing workflow name.

```bash
gh run view RUN_ID --repo OWNER/REPO --job JOB_ID --log > ~/.hermes/tmp/job.log
rg 'TS[0-9]+|FAIL|Expected|Received|error ' ~/.hermes/tmp/job.log
```

3. Check whether the failure-producing code came from current PR head or from a recently merged `main` PR.

```bash
# Find commits that introduced the function/string/file fragment.
git log --oneline -S'<unique symbol or error-adjacent string>' -- path/to/file

# See whether the suspect commit is already in main.
git merge-base --is-ancestor SUSPECT_COMMIT origin/main && echo in-main

# Compare the failed head against current main.
git merge-base FAILED_HEAD origin/main
git rev-list --left-right --count origin/main...FAILED_HEAD
```

4. If the suspect is a recently merged PR, query that PR/checks too. The same job may have failed there first.

```bash
gh api repos/OWNER/REPO/pulls/PR_NUMBER \
  --jq '{number,state,merged_at,head:.head.ref,sha:.head.sha,base:.base.ref,url:.html_url}'

gh api "repos/OWNER/REPO/commits/SUSPECT_COMMIT/check-runs?per_page=100" \
  --jq '[.check_runs[] | {name,status,conclusion,details_url}]'
```

## Fix pattern

- Fix the shared/base regression on the active PR branch if that is the branch being prepared for merge.
- Rebase the PR branch onto latest `origin/main` so GitHub's mergeability and local state agree.
- Force-push with an explicit lease if history changed.
- Verify both:
  - local/remote SHA equality, and
  - PR check buckets (`pass`/`pending`/`fail`/`skipped`).

## Example: Zod `RefinementCtx` probe helper

A helper added to `main` used the existing validator as a probe by passing only:

```js
{ addIssue: (issue) => { /* collect issue.message */ } }
```

But the validator helper JSDoc said `ctx` was `import('zod').RefinementCtx`, whose type also requires `path`. TypeScript then failed with:

```text
TS2345: Argument of type '{ addIssue: (issue: IssueData) => void; }' is not assignable to parameter of type 'RefinementCtx'.
Property 'path' is missing ...
```

The durable fix was not to invent a fake `path`; it was to type the helper to the actual contract it needs:

```js
/** @typedef {{ addIssue: (issue: import('zod').IssueData) => void }} ZodIssueCollector */

/** @param {any} message @param {string} channel @param {ZodIssueCollector} ctx @param {Array<string | number>} path */
function validateCampaignMessagePayload(message, channel, ctx, path) {
  // only calls ctx.addIssue(...)
}
```

This keeps production `superRefine` callers valid while allowing lightweight probe collectors in tests/tool-schema summary code.
