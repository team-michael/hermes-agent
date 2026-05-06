---
name: update-hermes
description: Update a Hermes checkout while preserving team-managed local customizations. Use when Codex needs to run `hermes update`, keep the primary checkout on `main`, rebase and push `local/hermes-patches` against `origin/main`, re-materialize `ignored/local`, and synchronize all repo-managed Hermes profiles, SOUL files, configs, memories, shared files, and custom skills after an update.
---

# Update Hermes

## Workflow

Use `scripts/update_hermes.py` for the normal path. It keeps the active checkout on `main`, uses a temporary worktree for `local/hermes-patches`, pushes with `--force-with-lease`, and applies local profile state for every directory under `ignored/local/profiles`.

```bash
python3 .agents/skills/update-hermes/scripts/update_hermes.py
```

Default behavior:

1. Verify the current repo is on `main` and clean.
2. Fetch `origin/main` and `team-michael/local/hermes-patches`.
3. Fast-forward the local patch branch from `team-michael/local/hermes-patches` when needed.
4. Run `hermes update` from the main checkout.
5. Rebase `local/hermes-patches` onto `origin/main` in a temporary worktree.
6. Copy current live profile `memories/*.md` files into the temporary patch worktree and commit them when they changed. Do not copy `.lock` files.
7. Push `local/hermes-patches` to `team-michael/local/hermes-patches` with `--force-with-lease`.
8. Restore `ignored/local` from the rebased patch branch into the main checkout.
9. Run `ignored/local/scripts/apply-local-state.py --replace-existing --link-soul` with no profile arguments, so newly added repo-managed profiles are included automatically.
10. Recreate known shared symlinks under `~/.hermes/shared` and `~/.hermes/bin`.
11. Run `ignored/local/scripts/audit-local-state.py`.

## Conflict Handling

If the rebase stops with conflicts, leave the temporary worktree in place and resolve there.

Use these rules:

- Prefer `origin/main` for upstream Hermes changes.
- If a patch-branch change implements a fix or feature now present upstream, drop the local implementation and migrate to the upstream implementation.
- Keep local-only profile, SOUL, config overlay, memory, shared, and custom skill assets under `ignored/local` unless upstream has a direct replacement.
- After resolving, run `git rebase --continue` in the temporary worktree, then rerun the script with `--skip-update` to finish push, materialization, profile sync, and audit.

## Guardrails

- Keep the primary checkout on `main`; do branch operations in a temporary worktree.
- Do not hardcode profile names. Treat every directory under `ignored/local/profiles` as managed profile state.
- Do not create or delete files outside `~/.hermes`; if temporary space is needed, use `~/.hermes/worktrees` or another `~/.hermes` subdirectory.
- Do not use destructive Git commands such as `git reset --hard` or `git checkout --` unless the user explicitly requests them.
- Before final response, report the active branch, patch branch tip, push status, and profile audit result.
