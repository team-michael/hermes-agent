---
name: update-hermes
description: Update a Hermes checkout while preserving reviewed team-managed local state and patches. Use when Codex needs to run `hermes update`, keep the primary checkout on `main`, update from `origin/main`, synchronize every managed profile, and push `team-michael/main`.
---

# Update Hermes

Run the repository-owned wrapper from the primary checkout:

```bash
python3 .agents/skills/update-hermes/scripts/update_hermes.py
```

## Workflow

The wrapper keeps the active checkout on `main` and performs these steps:

1. Acquire `~/.hermes/locks/hermes-main-maintenance.lock`, shared with the daily state Cron.
2. Reject pre-existing staged changes and dirty paths outside `ignored/local/**` or `.agents/skills/**`.
3. Fetch `origin/main` and `team-michael/main`. Fast-forward from the team remote when possible; stop on unexplained divergence.
4. Export safe state for every live directory under `~/.hermes/profiles`: SOUL, curated config-overlay keys, Markdown memories, and profile-owned skills. Never copy `.env`, auth, sessions, logs, databases, locks, or caches.
5. Commit state-only changes with `[skip ci]`.
6. Validate every local-only commit against `ignored/local/core-patches.yaml`. Undeclared Hermes source changes stop the update.
7. Save the current local commits under `refs/hermes-local-backups/update-*`, then run the official `hermes update --yes`.
8. If the official updater resets divergent local commits while installing upstream, cherry-pick only the validated local commits back onto `main`.
9. Apply and audit all managed profiles, run the core-patch test commands, and verify that `origin/main` is an ancestor of `main`.
10. Push `team-michael/main` with an explicit force-with-lease tied to the fetched remote SHA.

## Conflict Handling

If local commit restoration stops on a conflict:

- Keep the primary checkout on `main`.
- Prefer `origin/main` when it already implements the same fix or feature.
- Keep profile state, SOUL, memories, shared files, and custom skills under `ignored/local`.
- Retain a core patch only when upstream has no equivalent, list every affected path in `ignored/local/core-patches.yaml`, and add focused tests.
- Resolve the conflict and run `git cherry-pick --continue`.
- Rerun the wrapper with `--skip-update`.

Do not abort or reset the cherry-pick until the backup ref printed by the wrapper has been recorded.

## Daily Sync

The Andrej Cron entry runs:

```bash
~/.hermes/profiles/andrej/scripts/hermes_agent_daily_commit_push.sh
```

It is state backup only. It requires local `main` to equal `team-michael/main`, stages existing allowlisted files only, refuses deletions and source changes, makes a normal push, and never fetches or rebases `origin/main`. It does not use `git add -A`, `git reset`, or force push.

## Guardrails

- Keep the primary checkout on `main`.
- Discover profiles dynamically; do not hardcode the managed profile list.
- Create temporary files, refs, backups, and worktrees only below `~/.hermes`.
- Do not put secrets or runtime state under `ignored/local`.
- Do not bypass the core-patch manifest after a failed integrity check.
- Before completion, report the active branch, `origin/main` ancestry, `team-michael/main` equality, profile audit result, and gateway restart status.
