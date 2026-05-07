---
name: hermes-local-patch-rebase
description: Rebase Hermes' local main patch branch after `hermes update`, including agent-led conflict resolution, validation, and force-with-lease push to team-michael/main. Use when `hermes update` fails while rebasing main onto origin/main, when local main is behind team-michael/main, or when the user asks to apply local Hermes patches after an update.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [hermes, update, git, rebase, local-patches, conflict-resolution]
---

# Hermes Main Patch Rebase

Use this skill when Hermes needs to keep local `main` as the team patch branch after `hermes update`, especially when the CLI update path aborts because a local patch commit conflicts with updated `origin/main`.

This is intentionally **agent-led**, not a blind script. Inspect conflicts, understand the local patch intent, preserve upstream fixes, edit code directly, then validate.

## Defaults

- Repo: `~/.hermes/hermes-agent`
- Local branch: `main`
- Upstream base: `origin/main`
- Backup remote: `team-michael`
- Backup ref: `team-michael/main`

If the repo path or branch differs, discover it from:

```bash
git -C ~/.hermes/hermes-agent status --short --branch
git -C ~/.hermes/hermes-agent config --get branch.main.remote
sed -n '/^update:/,/^[^ ]/p' ~/.hermes/config.yaml
```

## Workflow

1. **Capture current state**

   ```bash
   git -C ~/.hermes/hermes-agent status --short --branch
   git -C ~/.hermes/hermes-agent log --oneline --decorate --max-count=8
   git -C ~/.hermes/hermes-agent rev-list --left-right --count origin/main...main
   git -C ~/.hermes/hermes-agent rev-list --left-right --count main...team-michael/main
   ```

   If a rebase is already in progress, continue from that state instead of aborting by default.

2. **Fetch both remotes**

   ```bash
   git -C ~/.hermes/hermes-agent fetch origin team-michael
   git -C ~/.hermes/hermes-agent checkout main
   git -C ~/.hermes/hermes-agent merge --ff-only team-michael/main
   ```

   If local `main` and `team-michael/main` diverged, stop and explain. Do not reset user state unless explicitly asked.

3. **Start or resume the main rebase**

   ```bash
   git -C ~/.hermes/hermes-agent rebase origin/main
   ```

   If it succeeds, go to validation.

4. **Resolve conflicts as an engineer**

   For every conflict:

   ```bash
   git -C ~/.hermes/hermes-agent status --short
   git -C ~/.hermes/hermes-agent diff --name-only --diff-filter=U
   git -C ~/.hermes/hermes-agent show --stat --patch REBASE_HEAD
   git -C ~/.hermes/hermes-agent diff --ours -- <file>
   git -C ~/.hermes/hermes-agent diff --theirs -- <file>
   ```

   Interpret the sides correctly during rebase:

   - `ours` is `origin/main` plus already-replayed local commits.
   - `theirs` is the local `main` patch commit currently being replayed.

   Keep upstream behavior unless the local patch intentionally changes it. Re-apply only the local patch's real intent.

   After editing:

   ```bash
   git -C ~/.hermes/hermes-agent diff --check
   ./venv/bin/python -m py_compile run_agent.py agent/bedrock_adapter.py hermes_cli/main.py
   git -C ~/.hermes/hermes-agent add <resolved-files>
   GIT_EDITOR=true git -C ~/.hermes/hermes-agent rebase --continue
   ```

   Repeat until rebase finishes.

5. **Run focused validation**

   Pick tests matching the local patch commits currently present. For the current Notifly Hermes local branch, the representative suite is:

   ```bash
   ./venv/bin/python -m pytest \
     tests/hermes_cli/test_update_autostash.py::test_get_configured_local_patch_branch_prefers_env_over_config \
     tests/hermes_cli/test_update_autostash.py::test_cmd_update_rebases_main_when_configured_patch_branch_is_main \
     tests/hermes_cli/test_update_autostash.py::test_cmd_update_exits_when_configured_main_rebase_fails \
     tests/hermes_cli/test_update_autostash.py::test_cmd_update_rebases_configured_local_patch_branch_before_restoring_stash \
     tests/hermes_cli/test_update_autostash.py::test_cmd_update_exits_when_local_patch_branch_rebase_fails \
     tests/gateway/test_slack_approval_buttons.py::TestSlackThreadContext::test_includes_external_bot_parent_attachment_text \
     tests/gateway/test_slack_approval_buttons.py::TestSlackThreadContext::test_includes_external_bot_parent_block_text \
     tests/gateway/test_slack_approval_buttons.py::TestSlackThreadContext::test_skips_own_bot_messages \
     tests/gateway/test_slack.py::TestThreadReplyHandling::test_suspended_thread_session_refetches_thread_context \
     tests/agent/test_bedrock_adapter.py::TestBedrockContextLength::test_claude_opus_4_6
   ```

   If a listed test no longer exists after upstream changes, find the nearest replacement instead of silently skipping coverage.

6. **Push the rewritten branch**

   Use force-with-lease only after a successful rebase and validation:

   ```bash
   git -C ~/.hermes/hermes-agent push --force-with-lease team-michael main:main
   ```

   For a simple local-skill/docs commit where no history rewrite occurred, use the normal push:

   ```bash
   git -C ~/.hermes/hermes-agent push team-michael main:main
   ```

   If HTTPS credentials are needed, do not print or embed the token in the remote URL. In the Andrej profile the token may live in `/home/ubuntu/.hermes/profiles/andrej/.env` even when terminal subprocess env is sanitized and `git push` fails with `could not read Username for 'https://github.com'`. Use a temporary `GIT_ASKPASS` helper under `~/.hermes/cache/` that reads `GITHUB_TOKEN`/`GH_TOKEN` from the profile `.env`, then delete it immediately after the push. `gh auth status` can show a valid token while plain `git push` still lacks non-interactive credentials.

7. **Verify final state**

   ```bash
   git -C ~/.hermes/hermes-agent status --short --branch
   git -C ~/.hermes/hermes-agent rev-list --left-right --count origin/main...main
   git -C ~/.hermes/hermes-agent rev-list --left-right --count main...team-michael/main
   git -C ~/.hermes/hermes-agent log --reverse --format='%h %s' origin/main..main
   git -C ~/.hermes/hermes-agent ls-remote team-michael refs/heads/main
   hermes update
   ```

   A good final state has:

   - clean worktree
   - active branch `main`
   - `origin/main...main` showing `0 N`
   - remote `team-michael/main` at the same tip
   - `hermes update` exits cleanly

## Pitfalls

- Do not assume a conflict means the local patch should win. Upstream may have absorbed part of the patch.
- Do not run `git reset --hard` unless explicitly asked or after confirming all important work is preserved.
- Do not leave conflict markers in source files.
- Do not print tokens from `~/.bashrc` or `.env`.
- Do not skip tests just because rebase completed.
