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

Interpret response:
- `ok: true` → retrieval works
- `missing_scope` → scopes/reinstall problem
- `not_in_channel` or `no_permission` → membership problem
- `channel_not_found` → wrong channel/token/workspace
- `thread_not_found` → wrong ts

## Practical notes

- For long-range Slack support/CS Q&A dataset extraction, use the same `conversations.history` + `conversations.replies` pattern but make the export resumable, persist raw JSONL, categorize threads into coarse topic CSVs, and validate category row totals before packaging. See `references/bulk-channel-qa-dataset-export.md`.
- `app_mention` only gives messages pertinent to the app; do not rely on it for full thread context.
- For private channels, “scope exists” is not enough; membership is usually the real blocker.
- If the agent runtime cannot directly call Slack Web API, enrich thread context in the bridge/backend before invoking the agent.
- When validating accessible channels, fully paginate `conversations.list`; private channels can be missed if you stop early.
- In the Andrej Hermes profile, Slack Web API access may require explicitly loading `SLACK_BOT_TOKEN` from `/home/ubuntu/.hermes/profiles/andrej/.env` inside a one-off script; terminal subprocesses may strip messaging secrets from ambient `os.environ`. Never print the token.
- To inspect a permalink, parse `/archives/{channel}/p{10digits}{6digits}` into `channel` and `ts={10digits}.{6digits}`, then call `conversations.replies`. For keyword expansion when `search.messages` returns `not_allowed_token_type`, page `conversations.history` for the channel/time window and locally filter terms such as `발송 중단`, `캠페인 중단`, `중지 가능`, `중단 가능`.

## Good user-facing fallback

If the app cannot retrieve the root due to membership or policy:
- tell the user exactly why (`not_in_channel`, `missing_scope`, etc.)
- ask them to invite the app or reinstall with updated scopes
- optionally ask them to paste the root message manually so work can continue

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
