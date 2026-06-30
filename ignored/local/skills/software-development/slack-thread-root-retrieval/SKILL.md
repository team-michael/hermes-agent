---
name: slack-thread-root-retrieval
description: Diagnose and implement retrieval of Slack thread root messages for bots/agents. Covers conversations.replies, scope/membership checks, reinstall pitfalls, token-type mistakes, and event-payload enrichment.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [slack, threads, debugging, integrations, events]
---

# Slack Thread Root Retrieval

## Notifly Slack permalink rule

When a Slack permalink is provided, use the Slack Web API before browser fallback: parse `channel`/`ts`, fetch with `conversations.history` or `conversations.replies`, download `url_private_download` attachments with the bot token, then analyze screenshots locally. See `references/slack-permalink-api-first.md`.

Use this when a Slack bot/agent can see a threaded reply or mention but cannot see the thread's root message.

## Core facts

- The canonical API for getting a thread root is `conversations.replies`.
- Call it with:
  - `channel=<conversation id>`
  - `ts=<thread_ts>`
- In the response, `messages[0]` is the parent/root message.
- Do **not** assume `app_mention` or other event payloads include the root message.
- Scopes alone are not sufficient; the app must also be a member of the conversation.

## Required Slack scopes

Depending on conversation type:
- Public channels: `channels:history`
- Private channels: `groups:history`
- DMs: `im:history`
- Group DMs: `mpim:history`

Often also useful for discovery/validation:
- `channels:read`
- `groups:read`
- `im:read`

## Root-cause checklist

Check in this order:

1. **Correct API design**
   - Are you explicitly calling `conversations.replies` when `thread_ts` is present?
   - If not, fix the integration first. This is the most common architectural gap.

2. **Correct token type**
   - Use a workspace Web API token, usually bot token `xoxb-...`
   - Do **not** use signing secret
   - Do **not** use `xapp-...` app-level token for `conversations.replies`
   - Verify token belongs to the same workspace/team as the target channel

3. **Reinstall after scope changes**
   - After adding scopes in Slack app config, reinstall the app to the workspace
   - If using OAuth install flow, ensure the scope list in code/config also matches

4. **Conversation membership**
   - Public/private channels: the app must actually be in the channel
   - Private channels especially require explicit invite
   - If missing, expect `not_in_channel` or `no_permission`

5. **Correct identifiers**
   - Use the actual `channel` ID, not channel name
   - Use `thread_ts` or a valid message `ts`
   - If `thread_not_found`, verify the ts refers to a threadable message

6. **SDK/event model gaps**
   - Some SDK payload models may omit `thread_ts` or root context
   - Inspect raw payloads when fields seem missing

## Typical failure modes

- `missing_scope`
  - Scope missing, stale install, or OAuth scope mismatch
- `no_permission`
  - App not a member of the conversation, or workspace policy restriction
- `not_in_channel`
  - App must be invited to the channel
- `channel_not_found`
  - Wrong channel ID or token/workspace mismatch
- `thread_not_found`
  - Wrong `ts`, or using a non-threadable subtype
- `not_allowed_token_type`
  - Wrong token class, e.g. `xapp-...`

## Recommended integration pattern

When processing Slack events:

1. Receive event
2. If `thread_ts` exists, call `conversations.replies(channel, ts=thread_ts)`
3. Extract `root = response["messages"][0]`
4. Pass both event message and root message into downstream agent context
5. If call fails, surface the exact Slack error and branch by error code

### Python example

```python
if event.get("thread_ts"):
    resp = client.conversations_replies(
        channel=event["channel"],
        ts=event["thread_ts"],
    )
    root = resp["messages"][0]
    context = {
        "root_text": root.get("text"),
        "root_user": root.get("user"),
        "root_ts": root.get("ts"),
        "reply_text": event.get("text"),
        "reply_ts": event.get("ts"),
    }
```

### Minimal curl test

```bash
curl -s -H "Authorization: Bearer xoxb-..." \
  "https://slack.com/api/conversations.replies?channel=C12345678&ts=1712345678.123456"
```

### Reusable local script

For Notifly/Hermes Slack permalink work, a reusable script is available at `scripts/fetch_slack_thread.py`:

```bash
python <skill_dir>/scripts/fetch_slack_thread.py C12345678 1712345678.123456
```

It loads `SLACK_BOT_TOKEN` from the active env or `/home/ubuntu/.hermes/profiles/andrej/.env`, fetches `conversations.replies`, extracts message text/attachments/blocks into a compact summary, and writes raw + summary JSON under `~/.hermes/profiles/andrej/slack_api_cache/` without printing the token.

Interpret response:
- `ok: true` → retrieval works
- `missing_scope` → scopes/reinstall problem
- `not_in_channel` or `no_permission` → membership problem
- `channel_not_found` → wrong channel/token/workspace
- `thread_not_found` → wrong ts

## Practical notes

- In Notifly Slack work, treat Slack permalinks as structured Slack data, not ordinary web links. Browser login pages are **not** evidence that content is inaccessible. **Do not open the permalink in the browser as the first retrieval attempt.** First parse channel/ts, load `SLACK_BOT_TOKEN` from `/home/ubuntu/.hermes/profiles/andrej/.env` if it is not already in the process environment, then call Slack Web API (`conversations.history` with a tight `oldest/latest` window for the exact permalink message; `conversations.replies` with `thread_ts` for the full thread). If the bot token is not available in the active process, use Hermes-local recovery before giving up: `send_message(action='list')` can confirm known Slack channel/thread targets, `~/.hermes/profiles/<profile>/channel_directory.json` / `sessions/sessions.json` can map `channel:thread_ts` to a session id, and `session_search(session_id=...)` can recover prior thread context. Only say content is inaccessible after API-level failure **and** local/session-cache recovery fail; state those attempted paths explicitly. If the Slack message has `files[]`, download image evidence via `url_private_download` with the bearer token and run vision/OCR before summarizing. If the Slack content links to Google Docs/Sheets/Drive, follow with authenticated Google Workspace access before giving product/sales conclusions. See `references/slack-permalink-api-first-with-media.md` for the compact permalink + screenshot retrieval recipe.
- For long-range Slack support/CS Q&A dataset extraction, use the same `conversations.history` + `conversations.replies` pattern but make the export resumable, persist raw JSONL, categorize threads into coarse topic CSVs, and validate category row totals before packaging. See `references/bulk-channel-qa-dataset-export.md`.
- `app_mention` only gives messages pertinent to the app; do not rely on it for full thread context.
- For private channels, “scope exists” is not enough; membership is usually the real blocker.
- If the agent runtime cannot directly call Slack Web API, enrich thread context in the bridge/backend before invoking the agent.
- When validating accessible channels, fully paginate `conversations.list`; private channels can be missed if you stop early.
- In the Andrej Hermes profile, Slack Web API access may require explicitly loading `SLACK_BOT_TOKEN` from `/home/ubuntu/.hermes/profiles/andrej/.env` inside a one-off script; terminal subprocesses may strip messaging secrets from ambient `os.environ`. Never print the token.
- To inspect a permalink, parse `/archives/{channel}/p{10digits}{6digits}` into `channel` and `ts={10digits}.{6digits}`, then call `conversations.replies`. For keyword expansion when `search.messages` returns `not_allowed_token_type`, page `conversations.history` for the channel/time window and locally filter terms such as `발송 중단`, `캠페인 중단`, `중지 가능`, `중단 가능`.
- For cross-source research tasks, Slack bot tokens may not support global `search.messages` (`not_allowed_token_type`) and may also lack `conversations.list` scopes (`missing_scope`). In that case, do not claim “no Slack evidence”; state the API limitation, use known permalinks/thread IDs or previously exported accessible-channel indexes, then retrieve exact threads with `conversations.replies`.
- Slack apps such as Supbot/standup may put the useful content in `attachments[]`, not `message.text`, and the first attachment can be only a generic fallback like “X posted an update”. When summarizing standup/product evidence, iterate **all** attachments and extract `text`, `fallback`, `fields`, and block text; otherwise you will miss “yesterday/today/blockers” content.
- When thread root files/images are the evidence, fetch `messages[0].files[]` metadata and, if needed, download via `url_private_download` using the bot token without printing it. OCR/vision can extract event signage, dates, or agenda text even when message text is only a short label like `GFSA`.
- For Slack permalinks with attached PDFs/checklists/guidelines, use the API-first attachment workflow in `references/slack-permalink-pdf-attachments.md`: parse channel/ts, fetch `conversations.replies` plus a tight `conversations.history` window around the permalink timestamp, download only PDF files via `url_private_download`, extract with `pdfinfo`/`pdftotext -layout` or OCR fallback, then summarize by artifact and cross-check against the active doc/task.
- When the user asks whether external links in a Slack thread are accessible, fetch the thread first, extract all raw URLs, then classify each URL by cheap HTTP probe plus rendered browser content where needed. LinkedIn in particular can return `200` while showing a modal; individual public posts may become readable after dismissing the modal, while company `/posts/` listing pages often authwall. See `references/slack-thread-external-link-access-checks.md`.
- When the user asks to inspect LinkedIn posts with attached videos/screenshots, use the rendered DOM to extract `video.currentSrc`/`poster` and lazy image `data-delayed-url`, then download media if needed, extract representative frames with `ffmpeg`, and summarize post text separately from UI evidence. See `references/linkedin-post-media-extraction.md`.
- When the user asks to continue the discussion **in the current chat** from a Slack permalink, fetch the full thread, identify the latest user-relevant message as the active prompt, and answer directly from that tail context. If the tail asks about GitHub PRs/files, verify the PR/file evidence via GitHub API before repeating prior assistant summaries. Avoid Markdown tables for Notifly Slack PR/link summaries; use bullets/numbered lists because Slack tables wrap poorly. See `references/slack-thread-current-session-continuation.md`.
- When the user asks to prepare a new session to continue work from a Slack permalink, treat this as a handoff task: Slack API first, then session-history/cache fallback if the API cannot access the channel, and write an operational handoff under the active profile with stale-thread-root caveats, exact worktree/PR context, invariants, next steps, and verification commands. See `references/slack-thread-continuation-handoff.md`.
- When deciding the "latest" message in a fetched Slack thread, do **not** trust the cached summary array order or `i` field. Pagination, cache merging, or compaction artifacts can make array-tail messages older than earlier entries. Always sort messages by numeric `ts` descending and use that as the latest user/assistant turn before answering. If the user says the last question is wrong, immediately re-read/sort by `ts` and correct course.

## Good user-facing fallback

If the app cannot retrieve the root due to membership or policy:
- tell the user exactly why (`not_in_channel`, `missing_scope`, etc.)
- ask them to invite the app or reinstall with updated scopes
- optionally ask them to paste the root message manually so work can continue

## Absorbed skills: Slack thread context debugging and session history

The following reference files were absorbed from formerly standalone skills. Each covers a specific facet of the same class-level problem: diagnosing why Hermes cannot read Slack thread root messages or recovering context when live API access is unavailable.

### AWS Chatbot / Amazon Q thread context debugging
- `references/slack-aws-chatbot-thread-context-debugging.md` — Diagnoses why Hermes misses AWS Chatbot / Amazon Q alert roots; `allow_bots` config vs gateway code fix; attachment/block parsing; reaction lifecycle (`message_subscriptions` vs `channel_skill_bindings`); testing checklist

### Hermes gateway Slack thread context debugging
- `references/hermes-slack-thread-context-debugging.md` — Deep gateway code fix guide for `_fetch_thread_context()` bot filtering and attachment/block extraction; `_extract_slack_message_text()` helper; session suspend/restore masking; `/mute` `/unmute` multi-profile behavior
- `references/hermes-slack-thread-context-debugging-slack-mute-unmute-multiple-profiles.md` — Multi-profile mute/unmute session-specific reference

### Slack alert session history recovery
- `references/slack-alert-session-history.md` — Recover alert root details and prior thread context from Hermes session archives when live Slack API is unavailable; `sessions.json` lookup, `session_search` fallback, cross-profile archive inspection
- `scripts/slack-alert-session-history-inspect_slack_alert_session_history.py` — Reusable script to inspect Slack alert session history by channel/thread/session ID
- `references/slack-alert-session-history-slack-dm-target-resolution.md` — DM target resolution from Hermes archives when Slack group delivery fails
- `references/slack-alert-session-history-ai-agent-token-budget-incidents.md` — AI-agent Slack alert streaming failure classification (finishReason: length, client disconnects, TokenLimiterProcessor)
- `references/slack-alert-session-history-slack-session-artifact-extraction.md` — Slack permalink + session recovery with file artifact verification
- `references/slack-alert-session-history-cross-profile-session-archive-inspection.md` — Cross-profile session archive inspection
- `references/slack-alert-session-history-channel-term-frequency-analysis.md` — Channel-level wording/term-frequency analysis from session archives
- `references/slack-alert-session-history-missing-session-file-recovery.md` — Missing session transcript file recovery via session_search and Slack cache

## References

Official docs:
- `conversations.replies`
- `messaging/retrieving-messages`
- `events/app_mention`
- `events/message/message_replied`

Useful issue patterns:
- bot not in channel → Slack SDK/community issues reporting `not_in_channel`
- reinstall required after scope changes → Node Slack SDK issue reports
- wrong token type (`xapp`, signing secret) → Python Slack SDK issue reports
- SDK field omissions like missing `threadTs` → Java Slack SDK issue reports
