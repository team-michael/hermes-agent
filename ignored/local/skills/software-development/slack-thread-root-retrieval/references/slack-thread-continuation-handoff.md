# Slack thread continuation handoff

Use this when the user asks to “prepare a new session to continue” from a Slack permalink or an old thread.

## Pattern

1. Parse the permalink into `channel` and `ts`.
2. Try Slack Web API first (`conversations.replies`).
3. If Slack returns `channel_not_found`, `not_in_channel`, or another access error, do **not** stop if the work may already exist in Hermes history.
4. Search local session history for the permalink forms:
   - raw permalink: `p1781172234265969`
   - split timestamp: `1781172234.265969`
   - compact timestamp: `1781172234265969`
5. If a prior session found/fetched the thread, inspect cached summaries under:
   - `~/.hermes/profiles/<profile>/slack_api_cache/thread_<channel>_<ts_with_underscore>_summary.json`
   - and/or the matching session transcript via `session_search`.
6. Build a new-session handoff under the active profile, e.g.:
   - `~/.hermes/profiles/<profile>/handoffs/<topic>.md`

## Good handoff shape

Keep it operational, not narrative:

- Source Slack permalink and resolved/related Hermes session id.
- Exact repo/worktree/branch/PR if relevant.
- Latest active task in one sentence.
- Skills to load first.
- Prerequisite checks to run before modifying code.
- Current product/technical invariants that must not regress.
- Last known implementation/diagnosis summary.
- Concrete next steps and verification commands.
- Reporting format expected by the user.

## Pitfalls

- A Slack thread root can be stale and misleading when the real continuation is in a later reply. In the handoff, explicitly tell the new session to ignore stale thread-root context and use the handoff as source of truth.
- When deciding the "latest" Slack thread question from fetched summaries/raw JSON, sort messages by numeric `ts`, not by array position or by the truncated tool preview. Slack/cache summaries can present older root/reply windows after newer replies, and truncated output can make the tail look authoritative when it is not.
- Do not persist PR numbers/SHAs to memory; they belong in the handoff/reference only.
- If the cached Slack summary is very long, read just enough to identify the latest active task and stable invariants; avoid copying the whole thread.
- If the prior work used another Hermes profile/worktree, state that explicitly and require live `git status`/PR checks before continuing.
