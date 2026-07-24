# BG Requester-Aware Approvals Design

## Goal

Keep Brad Gilbert open to the full company Slack workspace while ensuring that only Minyong can authorize sensitive operations. Minyong's own requests should not pause for recoverable approval prompts.

## Required behavior

- Any admitted Slack workspace user can chat with BG.
- A channel conversation starts with `@Brad Gilbert`; later replies in the same thread do not require another mention.
- Slack threads remain shared sessions so participants inherit the visible thread context.
- Minyong's Slack Member ID is approval-exempt for recoverable approval checks.
- Hardline blocks and explicit `approvals.deny` rules still apply to Minyong.
- Other users can perform ordinary conversation, research, read-only GitHub inspection, and normal workspace edits without an owner prompt.
- Other users must obtain Minyong's one-operation approval for configured GitHub mutations and Hermes' existing dangerous terminal or `execute_code` actions.
- Only configured approval administrators can resolve an execution approval or toggle `/yolo`.
- Restricted-user prompts expose only `Allow Once` and `Deny`; session and permanent approval choices are not offered.
- Approval prompts mention the configured Slack approver so Minyong receives a notification.
- No behavior changes when the new requester policy is absent.

## Configuration

The policy is profile-scoped in `config.yaml`:

```yaml
approvals:
  mode: manual
  timeout: 300
  cron_mode: deny
  exempt_users:
    slack:
      - U0123456789
  approver_users:
    slack:
      - U0123456789
  require:
    - "*git push*"
    - "*gh pr create*"
    - "*gh pr merge*"
```

The Member ID above is illustrative. `exempt_users` and `approver_users` accept per-platform lists or comma-separated strings. The BG overlay contains the full GitHub mutation pattern set. The concrete Slack Member ID is inserted only after Minyong supplies it through the setup flow; no placeholder is applied to live configuration.

## Architecture

`tools.approval` remains the single approval-policy source. It reads the current gateway platform and requester from session `ContextVar` state, matches profile-specific required-command globs, bypasses recoverable prompts for configured exempt users, and exposes a helper that checks whether a user may resolve approvals.

The Slack adapter consumes that helper for interactive buttons. When approvers are configured, it mentions them, suppresses persistent approval buttons, and rejects clicks from all other users. The gateway command gate applies the same policy to `/approve`, `/deny`, and `/yolo` on both idle and busy-session paths.

The new configuration is inert for every profile that does not opt in. No new environment variables or dependencies are introduced.

## GitHub mutation coverage

BG's configured rules require approval for:

- `git push` and direct send-pack operations;
- creating, merging, closing, or reopening pull requests;
- creating, editing, closing, or reopening issues;
- creating, deleting, renaming, archiving, or forking repositories;
- release, workflow, run, secret, variable, key, authentication, and codespace mutations;
- `gh api` requests that use mutating methods, fields, or input payloads.

Read-only commands such as `git status`, `gh repo view`, `gh pr list`, and `gh api` GET requests remain unprompted.

## Failure behavior

- Missing or empty approver configuration preserves the historical behavior.
- A configured but non-matching approver fails closed for buttons and approval-control commands.
- Approval timeout means denial; silence is not consent.
- A non-owner cannot persist a session-wide or permanent exception.
- Hardline commands remain blocked even when requested by Minyong.

## Verification

- Unit tests cover required-command matching, read-only non-matches, current-requester exemption, and hardline precedence.
- Slack tests cover owner mentions, button reduction, owner acceptance, and non-owner rejection.
- Gateway dispatch tests cover `/approve`, `/deny`, and `/yolo` for owner and non-owner users on both cold and active-session paths.
- Existing Slack approval tests and the relevant approval suite remain green.
- A BG profile smoke test confirms the policy is absent from other profiles and becomes active only after the real Slack Member ID is installed.
