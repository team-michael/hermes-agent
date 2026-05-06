---
name: slack-aws-chatbot-thread-context-debugging
description: Diagnose why Hermes cannot read Slack thread root messages from AWS Chatbot / Amazon Q alerts, and determine whether config changes or code changes are required.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [slack, hermes, aws-chatbot, amazon-q, cloudwatch, thread-context, gateway, debugging]
---

# Slack AWS Chatbot Thread Context Debugging

Use this when Hermes is invoked in a Slack thread whose root message was posted by AWS Chatbot / Amazon Q Developer (for example CloudWatch alerts), and Hermes cannot see the actual alert/error content.

## Core insight

This is usually **not** a pure scope problem and **not** something a skill alone can fix.

The common failure mode is:
1. Slack app scopes are present (`channels:history`, `groups:history`, etc.)
2. Hermes Slack adapter does call `conversations.replies`
3. But the thread root is posted as an external bot message (`bot_message` / `bot_id`)
4. The real payload lives in Slack `attachments` / `blocks`, not top-level `text`
5. Hermes drops bot messages from thread context and does not flatten attachments/blocks into text

Result: the LLM never receives the actual alert body.

## When config helps vs when it does not

### Config that may help partially
Hermes supports Slack bot ingress configuration:

```yaml
slack:
  allow_bots: all
```

Equivalent env var:

```bash
SLACK_ALLOW_BOTS=all
```

This only affects whether incoming Slack bot messages are accepted by the adapter.

### Config that does **not** solve the AWS Chatbot root-context problem by itself
Even with `allow_bots: all`, Hermes may still fail to read the root alert because:
- `_fetch_thread_context()` still filters out bot-authored thread messages
- thread-context extraction still reads mostly `msg["text"]`
- Slack `attachments` / `blocks` are not converted into plain text context

So if the user asks whether this can be solved by settings alone, the answer is usually **no**.

## Files to inspect

Primary Hermes files:
- `gateway/platforms/slack.py`
- `gateway/config.py`
- `website/docs/user-guide/messaging/slack.md`
- `tests/gateway/test_slack.py`
- `tests/gateway/test_slack_approval_buttons.py`

## Exact code points worth checking

### 1. Incoming bot filtering
Inspect `gateway/platforms/slack.py` in `_handle_slack_message()`.

Look for logic like:
- `event.get("bot_id")`
- `event.get("subtype") == "bot_message"`
- `allow_bots` / `SLACK_ALLOW_BOTS`

This tells you whether Slack bot messages are accepted at ingress.

### 2. Thread context fetch path
Inspect `_fetch_thread_context()` in `gateway/platforms/slack.py`.

Confirm it calls:
- `client.conversations_replies(channel=..., ts=...)`

Then check whether it discards messages with:
- `msg.get("bot_id")`
- `msg.get("subtype") == "bot_message"`

If yes, AWS Chatbot roots will be omitted from context.

### 3. Attachment / block parsing
Check whether thread context uses only:
- `msg.get("text", "")`

If so, alert bodies inside Slack `attachments` / `blocks` will be invisible.

### 4. Config bridge
Inspect `gateway/config.py` to verify that YAML config maps to env vars, e.g.:
- `slack.allow_bots` -> `SLACK_ALLOW_BOTS`

## GitHub issue lookup checklist
Search the Hermes repo for these terms:
- `slack thread parent`
- `thread context`
- `SLACK_ALLOW_BOTS`
- `conversations.replies`
- `attachment`
- `aws chatbot`
- `amazon q`

Useful issue categories:
- thread root missing from context
- Slack thread fetch on mention
- bot-message filtering
- Slack history/tool exposure

In one investigation, these were relevant:
- `#1953` Slack bot doesn't fetch thread when mentioned
- `#2950` Slack thread parent message missing from conversation context
- `#3198` Add `SLACK_ALLOW_BOTS`
- `#6345` Expose Slack history/thread reads as a tool

If no issue explicitly mentions AWS Chatbot / Amazon Q alert attachments, consider filing a new one because that is a narrower and more actionable bug.

## Recommended fix shape

### Minimal viable code fix
Patch `gateway/platforms/slack.py` so thread-context fetch:
1. excludes only Hermes's own bot messages
2. includes external bot/app messages
3. extracts text from `attachments` and `blocks`

### Good helper structure
Add a helper such as:
- `_extract_slack_message_text(msg: dict) -> str`

It should merge, normalize, and dedupe text from:
- top-level `text`
- `attachments[].pretext`
- `attachments[].title`
- `attachments[].text`
- `attachments[].fields[].title/value`
- `attachments[].footer`
- `attachments[].fallback`
- common Block Kit text fields (`section`, `header`, `context`, `rich_text`, image alt text)

### Important policy distinction
Do **not** confuse:
- message **triggering** policy
- message **context ingestion** policy

For this use case, Hermes does not need to auto-respond to every AWS Chatbot post.
It only needs to read that content as context when a human later invokes Hermes in the thread.

So the safest behavior is:
- keep trigger policy conservative
- broaden thread-context ingestion for external bot messages
- still suppress Hermes's own prior outputs to avoid loops/circular context

## Testing checklist
Add regression tests for:

1. **AWS Chatbot-like thread root**
   - `subtype="bot_message"`
   - real content in `attachments`
   - top-level `text` empty or minimal
   - expected: root content appears in thread context

2. **Own Hermes bot messages still excluded**
   - expected: no circular context

3. **Attachment-only messages**
   - expected: context is still non-empty

4. **Human-only threads unchanged**
   - expected: no regression

## Practical verification commands

Use these to prove which layer is affected:

```bash
source venv/bin/activate

# 1) Config/ingress effect: allow_bots changes whether inbound bot messages are processed
pytest tests/gateway/test_slack.py -k bot_messages_ignored -q
SLACK_ALLOW_BOTS=none pytest tests/gateway/test_slack.py -k bot_messages_ignored -q

# 2) Thread-context effect: even with allow_bots=all, fetched bot messages are still skipped
SLACK_ALLOW_BOTS=all pytest tests/gateway/test_slack_approval_buttons.py::TestSlackThreadContext::test_skips_bot_messages -q
pytest tests/gateway/test_slack_approval_buttons.py::TestSlackThreadContext::test_fetches_and_formats_context -q
```

Interpretation:
- if `test_bot_messages_ignored` fails under the current config but passes with `SLACK_ALLOW_BOTS=none`, the ingress setting is active
- if `test_skips_bot_messages` still passes, thread-context fetch still drops bot-authored messages

This is the cleanest way to demonstrate that `allow_bots` affects inbound event acceptance but does **not** fix thread root ingestion.

## Session / restart nuance

Even after changing config and restarting the gateway, an existing Slack thread may still appear unchanged.

Why:
- `_fetch_thread_context()` is only called when there is **no active session** for that thread
- if the session store still has an entry for the thread, Hermes will continue from session history instead of refetching the root
- after restart, logs like `Suspended 1 in-flight session(s) from previous run` are evidence that the old thread session survived

Practical implication:
- testing in the **same existing thread** can produce a false negative
- use a **fresh thread** or clear/suspend the old session if you want to verify new root-ingestion behavior

## User-facing answer template

When asked whether permissions are enough:
- confirm scopes may already be sufficient
- explain that the remaining problem is usually the Slack adapter's context-ingestion logic
- say that `slack.allow_bots: all` is only a partial/workaround config, not the full fix

When asked whether a skill can solve it:
- say no, not by itself
- explain that skills help after the text reaches the model
- this problem occurs before that, in gateway ingestion

## Practical response summary

Use this concise summary in future conversations:

> If the Slack thread root comes from AWS Chatbot / Amazon Q, Hermes often misses it because the root is an external bot message and the real payload lives in attachments/blocks. `allow_bots: all` can relax ingress, but it does not by itself make Hermes include external bot thread roots or parse attachment content. That requires a patch in `gateway/platforms/slack.py`.
