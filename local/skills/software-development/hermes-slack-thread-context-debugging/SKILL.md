---
name: hermes-slack-thread-context-debugging
description: Diagnose why Hermes cannot read Slack thread root messages, especially AWS Chatbot / Amazon Q / CloudWatch alert roots delivered as bot_message attachments or blocks.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [hermes, slack, gateway, debugging, aws-chatbot, amazon-q, cloudwatch, attachments, thread-context]
---

# Hermes Slack Thread Context Debugging

Use this when Hermes is invoked inside a Slack thread but seems unable to see or reason over the thread root message.

Especially relevant when the root message was posted by:
- AWS Chatbot / Amazon Q Developer in chat applications
- CloudWatch alarm notifications
- other Slack apps/bots that render content in `attachments` or `blocks`

## Core diagnosis

If Hermes can reply in the thread but says it cannot see the root message, the failure is usually **not** missing LLM skill or missing reasoning. It is usually an **ingress/gateway parsing problem** in the Slack adapter.

There are 3 common causes in Hermes:

1. **Bot messages are filtered out on ingress**
   - File: `gateway/platforms/slack.py`
   - In `_handle_slack_message()`, bot senders are ignored unless `allow_bots` permits them.
   - This affects whether AWS Chatbot messages can trigger Hermes directly.

2. **Thread context fetch skips bot messages**
   - File: `gateway/platforms/slack.py`
   - In `_fetch_thread_context()`, fetched thread messages with `bot_id` or `subtype == "bot_message"` are skipped.
   - This is the key reason Hermes misses AWS Chatbot / Amazon Q alert roots when a human later asks inside the thread.

3. **Attachment/block text is not extracted**
   - Hermes currently relies heavily on top-level `text`.
   - AWS Chatbot / Amazon Q alert details may live in Slack `attachments[]` or `blocks[]`, not in `text`.
   - Even if the message is fetched, Hermes may still miss the real error unless attachments/blocks are flattened to text.

## Relevant code locations

### Slack adapter
- `gateway/platforms/slack.py`
  - `_handle_slack_message()`
  - `_fetch_thread_context()`
  - inbound file handling around `event.get("files", [])`

### Tests
- `tests/gateway/test_slack.py`
- `tests/gateway/test_slack_approval_buttons.py`

### Docs
- `website/docs/user-guide/messaging/slack.md`

## What to verify first

1. Confirm Hermes already calls `conversations.replies`
   - Search for `_fetch_thread_context` and `conversations_replies`
   - If present, the issue is probably **parsing/filtering**, not missing Slack API access.

2. Confirm the root message is bot-authored
   - Look for `bot_id` or `subtype == "bot_message"`
   - AWS Chatbot / Amazon Q alerts usually match this pattern.

3. Confirm the real content is in `attachments` or `blocks`
   - Check whether top-level `text` is empty/short
   - Inspect `attachments[].title/text/fields/fallback`
   - Inspect `blocks[]`

4. Check current filtering behavior
   - In `_fetch_thread_context()`, if all bot messages are skipped, root context will never reach the model.

## Recommended fix

### Principle
Separate:
- **trigger policy**: whether Hermes should respond to bot messages directly
- **context policy**: whether Hermes should read external bot/app messages as background context when a human asks in the thread

For AWS Chatbot-style alerts, you usually want:
- do **not** let external bots freely trigger Hermes
- but **do** include external bot root messages in thread context

### Fix 1: skip only Hermes' own messages, not all bot messages

In `_fetch_thread_context()`, replace blanket bot filtering:

```python
if msg.get("bot_id") or msg.get("subtype") == "bot_message":
    continue
```

with logic that only suppresses Hermes-authored messages.

Pattern:

```python
def _is_own_bot_message(self, msg: dict, team_id: str) -> bool:
    bot_uid = self._team_bot_user_ids.get(team_id, self._bot_user_id)
    if bot_uid and msg.get("user") == bot_uid:
        return True
    return False
```

Then:

```python
if self._is_own_bot_message(msg, team_id):
    continue
```

### Fix 2: add Slack message text extraction for attachments and blocks

Create a helper such as:

```python
def _extract_slack_message_text(self, msg: dict) -> str:
    parts = []

    text = (msg.get("text") or "").strip()
    if text:
        parts.append(text)

    for att in msg.get("attachments", []) or []:
        for key in ("pretext", "title", "text", "footer", "fallback"):
            value = (att.get(key) or "").strip()
            if value:
                parts.append(value)

        for field in att.get("fields", []) or []:
            title = (field.get("title") or "").strip()
            value = (field.get("value") or "").strip()
            if title and value:
                parts.append(f"{title}: {value}")
            elif value:
                parts.append(value)

    parts.extend(self._extract_text_from_blocks(msg.get("blocks", []) or []))

    seen = set()
    cleaned = []
    for p in parts:
        p = re.sub(r"\s+", " ", p).strip()
        if p and p not in seen:
            seen.add(p)
            cleaned.append(p)

    return "\n".join(cleaned).strip()
```

Minimum block support:
- `section.text.text`
- `section.fields[*].text`
- `header.text.text`
- `context.elements[*].text`
- `rich_text` recursive flattening
- `image.alt_text`

### Fix 3: bridge image files from fetched thread context into media URLs

Slack `conversations.replies` can return root/parent image attachments in `messages[0].files`, while the triggering reply event has no `files`. If these are only rendered as text, gateway vision enrichment never runs.

Recommended pattern:

```python
# _fetch_thread_context stores both formatted text and cached media paths
_ThreadContextCache(
    content=content,
    media_urls=context_media_urls,
    media_types=context_media_types,
)
```

In `_handle_slack_message()`, after `_fetch_thread_context(...)`, merge the cached thread-context media into the current `MessageEvent.media_urls/media_types` before constructing the event. This lets `gateway.run._prepare_inbound_message_text()` auto-run vision on images attached to the thread parent/root.

Also add a textual marker such as `[attached image: filename.jpg]` to the thread context, so the model can tie the vision description back to the parent message.

Add a regression test where:
- the triggering reply has no `files`
- `conversations.replies` returns a parent/root message with `files[].url_private_download`
- `_download_slack_file` is awaited
- the emitted `MessageEvent.media_urls` contains the cached parent image path

### Fix 4: use the extractor in both places

#### In `_fetch_thread_context()`
Replace:

```python
msg_text = msg.get("text", "").strip()
```

with:

```python
msg_text = self._extract_slack_message_text(msg)
```

#### In `_handle_slack_message()`
Replace plain top-level text capture:

```python
text = event.get("text", "")
```

with:

```python
text = self._extract_slack_message_text(event) or event.get("text", "")
```

This makes inbound parsing consistent for human messages, app messages, and thread context fetches.

## Runtime behavior to account for during verification

### Existing thread sessions can mask the fix

Even after patching and restarting the gateway, the same Slack thread may still appear unchanged if Hermes already has an active/restored session for that thread.

Reason:
- `_handle_slack_message()` only calls `_fetch_thread_context()` when there is **no active session** for the thread
- after a gateway restart, Hermes can suspend/restore in-flight sessions
- therefore a previously active thread may not re-fetch the root/context on the next message

Practical implication:
- do **not** verify this fix only by replying again in the exact same long-lived thread
- prefer one of:
  1. start a **new test thread** with an AWS Chatbot / Amazon Q root
  2. clear/remove the relevant session state before retesting
  3. explicitly inspect logs/session transcripts to confirm whether `[Thread context — prior messages ...]` was injected

Additional pitfall discovered in Hermes:
- after an unclean/timed-out restart, `SessionStore.suspend_recently_active()` can mark a thread session `suspended=True`
- on the next message, `get_or_create_session()` will auto-reset that session key to a fresh `session_id`
- if Slack pre-checks only `session_key in _entries`, it may wrongly treat the thread as already warm and skip `_fetch_thread_context()`
- result: the follow-up turn lands in a new session **without** the earlier thread history unless suspended sessions are treated as needing a fresh fetch

Concrete verification clues:
- inspect `~/.hermes/logs/agent.log`
  - if inbound messages for the target thread previously show a payload beginning with `[Thread context — prior messages ...]`, the fetch path definitely worked at least once
  - if post-restart inbound messages in the same thread no longer include that preamble, `_fetch_thread_context()` likely did **not** run on those later turns
  - if startup logs show `Suspended N in-flight session(s) from previous run`, assume session restore may mask the fix
- inspect `~/.hermes/sessions/sessions.json`
  - confirm which `session_id` is currently bound to the Slack `session_key` (`agent:main:slack:group:<channel>:<thread_ts>`)
  - if the thread key is rebound to a new session after restart, be careful: you may be looking at session continuity / replacement behavior, not a regression in the Slack parsing patch itself

If the post-restart session transcript lacks the `[Thread context ...]` preamble, that usually means the fetch path did not run for that turn.

## Why config/skill alone is insufficient

### Not solved by a skill
A skill only helps after the relevant content has already entered the prompt. If the Slack adapter discards the root message or fails to extract attachment text, no skill can recover it.

### Not solved by `SLACK_ALLOW_BOTS=all`
`SLACK_ALLOW_BOTS=all` affects trigger acceptance in `_handle_slack_message()`.
It does **not** fix `_fetch_thread_context()` skipping bot messages, and does not parse attachments/blocks.

Use `SLACK_ALLOW_BOTS` only if you intentionally want Hermes to process bot-authored messages as primary inbound events.

## Optional config extension

If you want conservative defaults, add flags such as:

```yaml
platforms:
  slack:
    extra:
      include_external_bot_thread_context: true
      parse_attachments_in_thread_context: true
```

Default recommendation for AWS-alert-heavy Slack workspaces:
- `include_external_bot_thread_context: true`
- keep direct bot triggering conservative unless explicitly needed

## Test cases to add

1. **AWS Chatbot-like thread root**
   - `subtype = "bot_message"`
   - top-level `text` empty or short
   - real content in `attachments[].title/text/fields`
   - human invokes Hermes in a reply
   - expected: thread context includes alert content

2. **Hermes own previous replies are excluded**
   - expected: no circular self-context

3. **Attachment-only message with empty text**
   - expected: non-empty extracted context

4. **Regression: existing human-only thread behavior remains unchanged**

## Debugging checklist

- `search_files("_fetch_thread_context", path="gateway/platforms", file_glob="slack.py")`
- `read_file("gateway/platforms/slack.py", ...)`
- inspect for:
  - `subtype == "bot_message"`
  - `msg.get("attachments")`
  - `msg.get("blocks")`
  - `conversations_replies`
- inspect tests to see whether current behavior intentionally skips bot messages

## Safe local hotfix workflow

If you must patch Hermes locally before upstreaming:

1. create a dedicated git branch, e.g. `fix/slack-thread-root-context`
2. commit the patch — do **not** leave it as an uncommitted edit on `main`
3. optionally export a backup patch file with `git format-patch -1 HEAD --stdout > ~/.hermes/patches/<name>.patch`

Why this matters:
- Hermes installs from a git checkout under `~/.hermes/hermes-agent`
- the install/update flow stashes local changes, updates the repo, and defaults to checking out `main`
- so your local fix is safer as a **named branch + commit**, because after update you can re-checkout the branch or cherry-pick the commit

Practical recovery options after `hermes update`:
- `git checkout <hotfix-branch>`
- or `git cherry-pick <commit>`
- or `git apply ~/.hermes/patches/<name>.patch`

## Practical takeaway

If a human asks Hermes to investigate a CloudWatch/AWS Chatbot alert inside a Slack thread and Hermes cannot see the root message, the most likely fix is:

1. include external bot messages in fetched thread context
2. flatten Slack attachments/blocks into plain text
3. keep Hermes' own bot messages excluded

That is a **gateway adapter fix**, not a prompt/skill fix.
