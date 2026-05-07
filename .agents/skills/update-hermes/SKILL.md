---
name: update-hermes
description: Update a Hermes checkout while preserving team-managed local customizations. Use when Codex needs to run `hermes update`, keep the primary checkout on `main`, rebase local `main` patches against `origin/main`, push `team-michael/main`, and synchronize all repo-managed Hermes profiles, SOUL files, configs, memories, shared files, and custom skills after an update.
---

# Update Hermes

## Workflow

Use `scripts/update_hermes.py` for the normal path. It keeps the active checkout on `main`, treats local `main` as the patch branch, pushes to `team-michael/main` with `--force-with-lease`, and applies local profile state for every directory under `ignored/local/profiles`.

```bash
python3 .agents/skills/update-hermes/scripts/update_hermes.py
```

Default behavior:

1. Verify the current repo is on `main` and clean.
2. Fetch `origin/main` and `team-michael/main`.
3. Fast-forward local `main` from `team-michael/main` when needed; stop if they diverged.
4. Run `hermes update` from the `main` checkout with `HERMES_UPDATE_LOCAL_PATCH_BRANCH=main` set explicitly. This guarantees Hermes rebases local commits onto `origin/main` instead of resetting them away, even if the root/default config does not define `update.local_patch_branch`.
5. Copy current live profile `memories/*.md` files into `ignored/local` and commit them when they changed. Do not copy `.lock` files. Local-only profile/state commits must include `[skip ci]` so upstream test workflows are not triggered by `ignored/local` churn.
6. Push local `main` to `team-michael/main` with `--force-with-lease`.
7. Run `ignored/local/scripts/apply-local-state.py --replace-existing --link-soul` with no profile arguments, so newly added repo-managed profiles are included automatically.
8. Recreate known shared symlinks under `~/.hermes/shared` and `~/.hermes/bin`.
9. Run `ignored/local/scripts/audit-local-state.py`.

## Conflict Handling

If the update stops because `main` cannot be rebased cleanly onto `origin/main`, keep the checkout on `main` and resolve there.

Use these rules:

- Prefer `origin/main` for upstream Hermes changes.
- If a patch-branch change implements a fix or feature now present upstream, drop the local implementation and migrate to the upstream implementation.
- Keep local-only profile, SOUL, config overlay, memory, shared, and custom skill assets under `ignored/local` unless upstream has a direct replacement.
- After resolving, run `git rebase --continue` on `main`, then rerun the script with `--skip-update` to finish memory sync, push, profile sync, and audit.

## Guardrails

- Keep the primary checkout on `main`; do not switch to a separate local patch branch.
- Do not hardcode profile names. Treat every directory under `ignored/local/profiles` as managed profile state.
- Do not create or delete files outside `~/.hermes`; if temporary space is needed, use `~/.hermes/worktrees` or another `~/.hermes` subdirectory.
- Do not use destructive Git commands such as `git reset --hard` or `git checkout --` unless the user explicitly requests them.
- Before final response, report the active branch, `team-michael/main` push status, and profile audit result.
