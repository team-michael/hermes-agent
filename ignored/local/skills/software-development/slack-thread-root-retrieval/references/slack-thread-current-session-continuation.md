# Slack thread current-session continuation

Use this when the user drops a Slack permalink and asks whether we can continue the discussion here, or asks to answer based on the latest message in that thread.

## Workflow

1. Parse the permalink into `channel` and `ts`.
2. Fetch the thread with Slack Web API (`conversations.replies`) using the reusable `scripts/fetch_slack_thread.py` when available.
3. Treat the **last non-bot/user-relevant message** as the active prompt, not the root message. Long threads often have stale root context.
4. Build a compact working context:
   - root topic in one line
   - latest user ask
   - latest assistant answer if the user is asking to continue/refine it
   - any concrete artifacts mentioned: PRs, files, docs, repos
5. If the latest ask references GitHub PRs, verify with GitHub API/file lists before answering. Do not rely only on previous assistant summaries inside the Slack thread.
6. Answer directly in the current chat; do not create a handoff file unless the user explicitly asks for a new-session handoff.

## Formatting preference for Notifly Slack continuation

- Avoid Markdown tables for PR/link summaries in Slack-style replies; they wrap/break visually.
- Prefer numbered or bulleted lists with Slack links, one PR per bullet.
- Keep Korean concise and evidence-first.

## Example output shape

- `가능. 쓰레드 최신 질문은 “...” 입니다.`
- `답은: ...`
- `근거:`
  - `<PR link|#1234>` — changed `packages/types/...`
  - `<PR link|#1235>` — added delivery/poller contract

## Pitfalls

- `messages[0]` is only the root; it may be months behind the current ask.
- Thread summaries from the fetch script can be truncated. If a specific answer depends on the tail, inspect the raw/cache or query the exact artifact named in the latest message.
- If a previous assistant message inside the Slack thread contains PR numbers, treat them as leads and verify against GitHub before repeating them.
