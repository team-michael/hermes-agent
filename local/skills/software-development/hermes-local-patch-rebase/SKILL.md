---
name: hermes-local-patch-rebase
description: Rebase Hermes' local patch branch after `hermes update`, including agent-led conflict resolution, validation, and force-with-lease push to team-michael. Use when `hermes update` fails with "Failed to rebase configured local patch branch", when local/hermes-patches is behind main, or when the user asks to apply local Hermes patches after an update.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [hermes, update, git, rebase, local-patches, conflict-resolution]
---

# Hermes Local Patch Rebase

Use this skill when Hermes needs to keep `local/hermes-patches` active after `hermes update`, especially when the CLI update path aborts because a local patch commit conflicts with the updated `main`.

This is intentionally **agent-led**, not a blind script. Inspect conflicts, understand the local patch intent, preserve upstream fixes, edit code directly, then validate.

## Defaults

- Repo: `~/.hermes/hermes-agent`
- Base branch: `main`
- Local patch branch: `local/hermes-patches`
- Backup remote: `team-michael`
- Backup ref: `team-michael/local/hermes-patches`

If the repo path or branch differs, discover it from:

```bash
git -C ~/.hermes/hermes-agent status --short --branch
git -C ~/.hermes/hermes-agent config --get branch.local/hermes-patches.remote
sed -n '/^update:/,/^[^ ]/p' ~/.hermes/config.yaml
```

## Workflow

1. **Capture current state**

   ```bash
   git -C ~/.hermes/hermes-agent status --short --branch
   git -C ~/.hermes/hermes-agent log --oneline --decorate --max-count=8
   git -C ~/.hermes/hermes-agent rev-list --left-right --count main...local/hermes-patches
   ```

   If a rebase is already in progress, continue from that state instead of aborting by default.

2. **Update the base**

   ```bash
   git -C ~/.hermes/hermes-agent fetch origin team-michael
   git -C ~/.hermes/hermes-agent checkout main
   git -C ~/.hermes/hermes-agent pull --ff-only origin main
   ```

   If `main` cannot fast-forward, stop and explain. Do not reset user state unless explicitly asked.

3. **Start or resume the local patch rebase**

   ```bash
   git -C ~/.hermes/hermes-agent checkout local/hermes-patches
   git -C ~/.hermes/hermes-agent rebase main
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

   - `ours` is the updated base branch plus already-replayed commits.
   - `theirs` is the local patch commit currently being replayed.

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
   git -C ~/.hermes/hermes-agent push --force-with-lease team-michael local/hermes-patches:local/hermes-patches
   ```

   If HTTPS credentials are needed, load `GITHUB_TOKEN` from `~/.bashrc` without printing it and use a temporary credential helper.

7. **Verify final state**

   ```bash
   git -C ~/.hermes/hermes-agent status --short --branch
   git -C ~/.hermes/hermes-agent rev-list --left-right --count main...local/hermes-patches
   git -C ~/.hermes/hermes-agent log --reverse --format='%h %s' main..local/hermes-patches
   git -C ~/.hermes/hermes-agent ls-remote team-michael refs/heads/local/hermes-patches
   hermes update
   ```

   A good final state has:

   - clean worktree
   - active branch `local/hermes-patches`
   - `main...local/hermes-patches` showing `0 N`
   - remote `team-michael/local/hermes-patches` at the same tip
   - `hermes update` exits cleanly

## Pitfalls

- Do not assume a conflict means the local patch should win. Upstream may have absorbed part of the patch.
- Do not run `git reset --hard` unless explicitly asked or after confirming all important work is preserved.
- Do not leave conflict markers in source files.
- Do not print tokens from `~/.bashrc` or `.env`.
- Do not skip tests just because rebase completed.
