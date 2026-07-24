# BG Requester-Aware Approvals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let all company Slack users work with BG while only Minyong can authorize sensitive actions and Minyong's own recoverable actions run without approval prompts.

**Architecture:** Extend the existing approval engine with profile-scoped required-command patterns and per-platform requester policy. Reuse that single policy from the Slack adapter and gateway slash-command dispatch so buttons, text approvals, and `/yolo` cannot bypass the owner boundary. Enable the feature only through BG's overlay.

**Tech Stack:** Python, asyncio, Slack Bolt adapter, pytest through `scripts/run_tests.sh`, YAML profile configuration.

## Global Constraints

- No new dependency or user-facing environment variable.
- Hardline blocks and `approvals.deny` always outrank requester exemptions.
- Missing requester-policy config preserves current behavior.
- Non-owner prompts are one-operation only.
- All changes stay on `codex/bg-hermes-profile` until verified.
- Tests use the real config and session-context loaders where policy propagation matters.

---

### Task 1: Approval policy and configured command rules

**Files:**
- Modify: `tools/approval.py`
- Create: `tests/tools/test_requester_approval_policy.py`

**Interfaces:**
- Produces: `get_approval_exempt_users(platform: str) -> frozenset[str]`
- Produces: `get_approval_approver_users(platform: str) -> frozenset[str]`
- Produces: `is_current_requester_approval_exempt() -> bool`
- Produces: `can_user_resolve_approval(platform: str, user_id: str) -> bool`
- Produces: `_match_user_require_rule(command: str) -> str | None`

- [ ] **Step 1: Write failing policy tests**

```python
def test_slack_owner_is_exempt_from_recoverable_approval(profile_config, session):
    profile_config({"approvals": {"exempt_users": {"slack": ["UOWNER"]}}})
    session(platform="slack", user_id="UOWNER")
    assert is_current_requester_approval_exempt() is True

def test_non_owner_cannot_resolve_when_approvers_configured(profile_config):
    profile_config({"approvals": {"approver_users": {"slack": ["UOWNER"]}}})
    assert can_user_resolve_approval("slack", "UTEAM") is False

def test_configured_git_push_rule_requires_approval(profile_config):
    profile_config({"approvals": {"require": ["*git push*"]}})
    assert detect_dangerous_command("git push origin HEAD")[0] is True
    assert detect_dangerous_command("git status")[0] is False
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `scripts/run_tests.sh tests/tools/test_requester_approval_policy.py -q`

Expected: failures because the new policy helpers and configured require matcher do not exist.

- [ ] **Step 3: Implement the minimal policy**

```python
def _coerce_platform_user_ids(raw) -> frozenset[str]: ...

def get_approval_exempt_users(platform: str) -> frozenset[str]:
    raw = (_get_approval_config().get("exempt_users") or {}).get(platform)
    return _coerce_platform_user_ids(raw)

def is_current_requester_approval_exempt() -> bool:
    platform = get_session_env("HERMES_SESSION_PLATFORM", "")
    user_id = get_session_env("HERMES_SESSION_USER_ID", "")
    return bool(user_id and user_id in get_approval_exempt_users(platform))
```

Add `_match_user_require_rule()` using the existing normalized command variants and `fnmatch`. Feed a match into `detect_dangerous_command()` as an approvable warning. Check `is_current_requester_approval_exempt()` only after hardline, sudo-stdin, and explicit deny gates in terminal, plugin-escalation, and `execute_code` paths.

- [ ] **Step 4: Run policy tests and relevant approval regression tests**

Run: `scripts/run_tests.sh tests/tools/test_requester_approval_policy.py tests/tools/test_approval.py tests/tools/test_execute_code_approval_cluster.py -q`

Expected: all discovered tests pass.

- [ ] **Step 5: Commit**

```bash
git add tools/approval.py tests/tools/test_requester_approval_policy.py
git commit -m "feat: add requester-aware approval policy"
```

### Task 2: Slack owner-only approval resolution

**Files:**
- Modify: `plugins/platforms/slack/adapter.py`
- Modify: `gateway/run.py`
- Modify: `tests/gateway/test_slack_approval_buttons.py`
- Modify: `tests/gateway/test_slash_access_dispatch.py`

**Interfaces:**
- Consumes: `get_approval_approver_users()` and `can_user_resolve_approval()` from Task 1.
- Produces: owner mentions and owner-only interactive resolution for Slack execution approvals.
- Produces: owner-only `/approve`, `/deny`, and `/yolo` when approvers are configured.

- [ ] **Step 1: Write failing Slack button tests**

```python
async def test_restricted_prompt_mentions_owner_and_is_one_shot_only(configured_owner):
    await adapter.send_exec_approval(chat_id="C1", command="git push", session_key="s")
    blocks = client.chat_postMessage.call_args.kwargs["blocks"]
    assert "<@UOWNER>" in blocks[0]["text"]["text"]
    assert [b["action_id"] for b in blocks[1]["elements"]] == [
        "hermes_approve_once", "hermes_deny",
    ]

async def test_non_owner_approval_click_is_ignored(configured_owner):
    await adapter._handle_approval_action(ack, body_for("UTEAM"), action)
    resolve_gateway_approval.assert_not_called()
```

- [ ] **Step 2: Write failing approval-control command tests**

Drive the real `GatewayRunner._handle_message` path for `/approve`, `/deny`, and `/yolo`. Assert `UTEAM` receives an owner-only denial while `UOWNER` reaches the real handler, including the active-session fast path.

- [ ] **Step 3: Run the focused tests and verify RED**

Run: `scripts/run_tests.sh tests/gateway/test_slack_approval_buttons.py tests/gateway/test_slash_access_dispatch.py -q`

Expected: new owner-only assertions fail against the current any-authorized-user behavior.

- [ ] **Step 4: Implement Slack and slash-command gates**

In `SlackAdapter.send_exec_approval()`, read configured Slack approvers, mention them, and emit only one-operation buttons when the set is non-empty. In `_handle_approval_action()`, perform normal gateway authorization first, then call `can_user_resolve_approval("slack", user_id)` before consuming the approval.

In `GatewayRunner._check_slash_access()`, add an approval-control guard before the existing general slash policy:

```python
if canonical_cmd in {"approve", "deny", "yolo"}:
    if not can_user_resolve_approval(source.platform.value, source.user_id or ""):
        return "⛔ Only a configured approval administrator can run this command."
```

This helper returns `True` when no approver list exists, preserving backward compatibility.

- [ ] **Step 5: Run focused and Slack regression tests**

Run: `scripts/run_tests.sh tests/gateway/test_slack_approval_buttons.py tests/gateway/test_slash_access_dispatch.py tests/gateway/test_approve_deny_commands.py -q`

Expected: all discovered tests pass.

- [ ] **Step 6: Commit**

```bash
git add plugins/platforms/slack/adapter.py gateway/run.py tests/gateway/test_slack_approval_buttons.py tests/gateway/test_slash_access_dispatch.py
git commit -m "feat: restrict Slack execution approvals to owners"
```

### Task 3: BG profile policy and deployment verification

**Files:**
- Modify: `ignored/local/profiles/bg/config.overlay.yaml`
- Modify: `docs/superpowers/specs/2026-07-19-bg-requester-aware-approvals-design.md` only if implementation differs from the approved contract.

**Interfaces:**
- Consumes: requester-aware approval configuration from Tasks 1 and 2.
- Produces: a BG-only GitHub mutation rule set ready for the real Slack Member ID.

- [ ] **Step 1: Add BG's command rules without a fake user ID**

Extend the existing `approvals` block with `timeout: 300` and the complete `require` glob list. Do not write `exempt_users` or `approver_users` into the overlay until the real Member ID is available; the setup step will insert the same real ID into both lists.

- [ ] **Step 2: Verify overlay rendering and isolation**

Run the existing BG local-state script in dry-run mode and inspect the rendered config. Assert the GitHub mutation rules appear only in BG and no token or Member ID placeholder is present.

- [ ] **Step 3: Run the complete relevant suite**

Run:

```bash
scripts/run_tests.sh \
  tests/tools/test_requester_approval_policy.py \
  tests/tools/test_approval.py \
  tests/tools/test_execute_code_approval_cluster.py \
  tests/gateway/test_slack_approval_buttons.py \
  tests/gateway/test_slash_access_dispatch.py \
  tests/gateway/test_approve_deny_commands.py -q
```

Expected: all discovered tests pass with zero failures.

- [ ] **Step 4: Commit safe profile assets**

```bash
git add ignored/local/profiles/bg/config.overlay.yaml
git commit -m "feat: protect BG GitHub mutations"
```

- [ ] **Step 5: Deploy code without starting Slack prematurely**

Fast-forward or cherry-pick the verified commits into `/home/ubuntu/.hermes/hermes-agent`, reinstall only if the source layout requires it, and keep `hermes-gateway-bg.service` stopped until the real `xapp-`, `xoxb-`, and Slack Member ID are installed.

- [ ] **Step 6: Activate with real Slack identity**

After the user supplies credentials through the hidden terminal flow, write the real Member ID to both `approvals.exempt_users.slack` and `approvals.approver_users.slack`, set company-wide Slack admission, start BG, and smoke-test:

1. Minyong `git push` request produces no recoverable prompt.
2. A teammate `gh pr create` request mentions Minyong and shows only `Allow Once` / `Deny`.
3. The teammate's button and `/yolo` attempts are rejected.
4. Minyong's `Allow Once` resolves the exact pending operation.
5. A read-only `gh pr list` request does not prompt.
