# notifly-event: Terraform alarm removal CI trap + filter substring matching

Two reusable learnings from deduplicating segment-publisher CloudWatch alarms in `notifly-event`.

## 1. `prevent_destroy` fails `terraform plan`, not just apply

### Where the guardrail lives
`infra/terraform/modules/ecs_task_observability/main.tf`:
- `aws_cloudwatch_metric_alarm "metric_alarms"` → `lifecycle { prevent_destroy = true }` (applies to ALL alarms via `for_each`)
- `aws_cloudwatch_log_group "this"` → also `prevent_destroy = true`
- `aws_cloudwatch_log_metric_filter "metric_filters"` → NO `prevent_destroy` (filters delete cleanly)

Alarm/filter inventory is data-driven from `infra/terraform/prod/ap-northeast-2/ecs/tasks.tf` (`metric_alarm_details` / `metric_filters` maps keyed by alarm/filter name).

### Failure chain (PR CI, workflow `.github/workflows/infra-terraform.yml`)
1. You delete an alarm's entry from the `metric_alarm_details` map.
2. The per-root `Terraform plan` step runs `terraform plan -detailed-exitcode`. Because the resource has `prevent_destroy`, plan **errors at plan time**: `Error: Instance cannot be destroyed ... has lifecycle.prevent_destroy set, but the plan calls for this resource to be destroyed.` → exit 1.
3. Plan exit 1 ⇒ no `tfplan.binary`/`tfplan.json` produced.
4. `Detect destructive changes` step sees no `tfplan.json` and defaults `destroy=0 has_destructive=false` — misleading.
5. `Render and publish summary` posts `PLAN_RESULT: failure` (the plan stderr surfaces in the PR comment under "Plan output").
6. Final step `Fail leg if checks or apply errored` runs `exit 1` because `steps.plan.outputs.outcome == 'failure'`.

So the red check is the guardrail, NOT a bug in the dedup logic. Diagnose by reading the workflow's own PR comment (`gh api repos/.../issues/<pr>/comments`) — the Terraform error text is embedded there verbatim.

### Why you can't just make it conditional
`prevent_destroy` must be a literal constant in Terraform; it cannot reference a variable or `each.value`. So a single committed change cannot selectively allow one alarm's deletion.

### Resolutions (per infra/terraform/AGENTS.md)
- **A — refine guardrail scope (committable, PR goes green):** drop `prevent_destroy` from the stateless alarm (and optionally filter) resources in the module, keep it on the log group (the only data-bearing resource). This is an *intentional policy change* affecting all task alarms — get user sign-off. After this, PR plan returns exit 2 (`changes`) and CI passes; the actual destroy still needs a human apply (CI auto-apply on main is blocked by `Block destructive apply` unless `workflow_dispatch` + `allow_destructive=true`).
- **B — keep guardrail, human applies the destroy:** leave HCL as-is (PR check stays red by design). A human runs the destroy locally via `infra/terraform/tf.sh` guarded apply (`ALLOW_APPLY=true`), or `workflow_dispatch` action=apply with `allow_destructive=true`. AGENTS.md permits temporarily commenting out `prevent_destroy` LOCAL-ONLY to produce the reviewed destroy plan — must not be committed, restore immediately.

### Out-of-band apply makes the PR plan diverge
If someone applies the destroy out-of-band (e.g. human runs the guarded apply) BEFORE the PR merges, a CI re-run on the same commit will now plan cleanly: the alarm/filter no longer exist in AWS, so plan shows only the remaining in-place change (`+0 ~1 -0`) and goes green. Verify live state with `aws cloudwatch describe-alarms` / `aws logs describe-metric-filters` rather than trusting the stale first run.

### Local plan reproduction (agent, read-only)
```bash
# in the worktree's root dir (e.g. .../ecs)
terraform init -input=false -no-color           # needs the exact required_version (1.14.8 here)
terraform validate -no-color
terraform plan -no-color -lock=false             # errors out on prevent_destroy as CI does
```
To produce the full reviewed destroy plan locally, temporarily set `prevent_destroy = false` in the module (LOCAL ONLY, never commit), re-run plan (`Plan: 0 to add, 1 to change, 2 to destroy.`), then restore `prevent_destroy = true`.

## 2. CloudWatch unquoted filter terms match as SUBSTRINGS

A metric filter pattern like `took too long` (unquoted, space-separated terms) matches a log line if EACH term appears as a **substring** — not as a whole word. So `took too long` matches BOTH:
- `... took too long: 142345ms` (Pattern A)
- `[WARN] Processing took longer than expected: ...` (Pattern B) — because `too` ⊂ `took` and `long` ⊂ `longer`, even though there's no standalone "too".

This is counterintuitive and fooled an automated reviewer (CodeRabbit) into a false-positive "Critical" claim that the filter wouldn't match Pattern B. Verify authoritatively with:
```bash
aws logs test-metric-filter --region ap-northeast-2 \
  --filter-pattern 'took too long' \
  --log-event-messages \
    'EventCounterCteManager.extract:p took too long: 142345ms' \
    '[WARN] Processing took longer than expected: 1820407 ms'
# matches: [1, 2]  → both
```
Consequence for dedup: an alarm whose filter substring-catches a second log class is a superset of a narrower companion alarm. Keep the superset, remove the redundant narrower alarm. To match ONLY whole words, quote the pattern term.

## 3. The alarm name may be a functional key elsewhere
Before renaming a retained alarm to better match its behavior, grep the repo for the alarm-name string. In notifly-event, `services/lambda/aws-chatbot-custom-action-worker/lib/cloudwatch.js` keys on `metricAlarmName.includes('slow eic query')` to pick the log-enrichment filter pattern. Renaming would (a) break that mapping and (b) force destroy/recreate on the alarm you meant to keep. Document behavior via `alarm_description` + HCL comments instead of renaming.
