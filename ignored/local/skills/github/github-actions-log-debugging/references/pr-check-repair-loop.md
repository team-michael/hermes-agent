# PR check repair loop

Use this when a PR check fails after you already pushed a branch and opened a PR.

## Pattern

1. Re-query live checks; do not trust a stale `gh pr checks --watch` tail.

```bash
gh pr checks "$PR" --repo "$OWNER/$REPO" || true
```

`gh pr checks` returns non-zero while checks are pending/failing, so polling scripts must capture output with `|| true` and inspect the text/state explicitly.

2. Inspect the failed job log only, not the entire run.

```bash
gh run view "$RUN_ID" --repo "$OWNER/$REPO" --job "$JOB_ID" --log-failed > "$HOME/.hermes/profiles/andrej/tmp/<task>/failed.log"
```

Then extract high-signal lines: `##[error]`, `error TS`, `prettier/prettier`, `FAIL`, `ELIFECYCLE`, `ERR_PNPM`.

3. Fix the actual failing layer and push a small follow-up commit.

Typical sequence:
- Prettier/lint failure: format exactly as CI requests; local `eslint --rule 'prettier/prettier: off'` is insufficient for CI parity.
- Typecheck failure: CI may catch this even when focused Jest/ESLint passes. Prefer a minimal type-safe change over weakening the response type too broadly.
- Python `ruff format --check` failure: run `uv run ruff format <changed paths>`, then rerun `ruff check` and `ruff format --check`.

4. Poll the new head checks without `--watch` loops that keep printing a stale failed state.

```bash
for i in $(seq 1 35); do
  status=$(gh pr checks "$PR" --repo "$OWNER/$REPO" 2>&1 || true)
  printf '%s\n' "$status"
  if printf '%s\n' "$status" | grep -q $'\tfail\t'; then exit 2; fi
  if ! printf '%s\n' "$status" | grep -q $'\tpending\t'; then exit 0; fi
  sleep 15
done
exit 124
```

5. Final report should distinguish:
- code/CI green (`SUCCESS`/expected `SKIPPED`)
- deploy/preview checks green or still pending
- branch protection blocker (`REVIEW_REQUIRED`) vs actual failing checks

## Why this matters
`gh pr checks --watch` can continue printing repeated failed rows after a follow-up push, and long output often hides the current failing layer. The reliable loop is: re-query current checks → inspect failed job log → patch → push → poll current checks → final `gh pr view` JSON for merge state.