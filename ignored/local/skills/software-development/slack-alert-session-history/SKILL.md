---
name: slack-alert-session-history
description: Recover Slack alert root details and prior thread context from Hermes session history with a single script call when live Slack history or root-message retrieval is unavailable.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [slack, sessions, alerts, cloudwatch, amazon-q, thread-context, debugging]
---

# Slack Alert Session History

Use this when a user asks:
- "이 얼럿 원문/상세정보 다시 보여줘"
- "그 Slack 스레드에서 무슨 컨텍스트가 들어왔지?"
- "live Slack API 없이 이전 alert thread 내용을 빨리 확인하고 싶다"

This skill is for **Hermes session archive inspection**, not live Slack history.

Important boundary: when the user gives a Slack permalink/thread URL and asks to inspect the actual thread history, do **not** default to Hermes archives. First use the live Slack Web API workflow from `slack-thread-root-retrieval`: parse `channel`/`thread_ts`, load `SLACK_BOT_TOKEN` from the active profile `.env` if needed, and call `conversations.replies` / `conversations.history`. Use this archive skill only after the live API is unavailable, fails with an API-level error, or the user specifically asks for Hermes-visible prior sessions.

It also covers routing recovery when Slack group/channel delivery fails (for example `not_in_channel`) and you need to resolve a named person's DM target from Hermes archives. See `references/slack-dm-target-resolution.md`.

For Notifly AI-agent Slack alerts involving streaming failures, `finishReason: length`, client disconnects, or `TokenLimiterProcessor`, do not judge the PR from the diff alone. Classify output-side length vs transport close/abort vs input-side context budget, then correlate the Slack root with prod `internal-api-service` tool/processor logs. See `references/ai-agent-token-budget-incidents.md`.

## Core idea

When Hermes handled a Slack thread, the useful root context often landed in two places:

1. `~/.hermes/sessions/sessions.json`
   - channel/thread → `session_id` lookup table
2. `~/.hermes/sessions/session_<session_id>.json`
   - actual transcript
   - often the **first user message** contains:
     - `[Thread context — prior messages in this thread ...]`
     - alert root text such as Amazon Q / CloudWatch notification
     - the user's follow-up question

So the fastest path is:
- resolve the target `session_id`
- inspect the session JSON directly
- extract injected thread context + first user ask + relevant assistant findings

## Fast path

### 1) If you already know `session_id`

Run one command:

```bash
python ~/.hermes/skills/software-development/slack-alert-session-history/scripts/inspect_slack_alert_session_history.py \
  --session-id 20260421_095149_7e990f80
```

### 2) If you know `channel_id` and `thread_ts`

```bash
python ~/.hermes/skills/software-development/slack-alert-session-history/scripts/inspect_slack_alert_session_history.py \
  --channel-id C04KT7EH5RQ \
  --thread-ts 1776764135.019959
```

### 3) If you only know the channel

First list candidate sessions:

```bash
python ~/.hermes/skills/software-development/slack-alert-session-history/scripts/inspect_slack_alert_session_history.py \
  --channel-id C04KT7EH5RQ
```

Then rerun with the desired `--thread-ts` or `--session-id`.

## Cross-profile keyword search for prior discussions

When the user asks “기존에 고민해 본 적 있는지 Slack 같은 곳에서 찾아봐” and you do not have live Slack search context/channel, search Hermes' Slack/session archives across profiles before concluding. `session_search` may only cover the current profile/recent indexed subset; fall back to scanning `~/.hermes/profiles/*/sessions/session_*.json`.

## Channel-level wording / term-frequency analysis

When the user asks which terms customers use more often in a Slack channel, prefer existing per-channel exports or curated CS datasets over Hermes session archives. Count customer/root-thread text separately from assistant replies, and report exact phrase, synonym, and broad semantic buckets separately. See `references/channel-term-frequency-analysis.md` for the reusable workflow and regex/counting pattern.

Use a small script under `~/.hermes` or `execute_code`; avoid writing outside `~/.hermes`. Search only `user`/`assistant` messages and skip tool dumps / context compaction blocks, because they create many false positives.

Reusable pattern:

```python
import json, re
from pathlib import Path
root = Path('/home/ubuntu/.hermes/profiles')
rx = re.compile(r'perRequestTimeout|Service Connect|internal-api-service|SSE|heartbeat|ALB idle', re.I)
for p in root.glob('*/sessions/session_*.json'):
    data = json.loads(p.read_text(errors='ignore'))
    hits = []
    for m in data.get('messages', []):
        if m.get('role') not in ('user', 'assistant'):
            continue
        c = m.get('content') or ''
        if not isinstance(c, str) or 'CONTEXT COMPACTION' in c:
            continue
        if rx.search(c):
            hits.append(re.sub(r'\s+', ' ', c)[:700])
    if hits:
        print(p, hits[:2])
```

In the final answer, distinguish:
- “Hermes-visible Slack/session archive found no prior discussion” from
- “Slack workspace definitely has no discussion.”

## Optional narrowing

If a session drifted into other topics, filter findings by keyword:

```bash
python ~/.hermes/skills/software-development/slack-alert-session-history/scripts/inspect_slack_alert_session_history.py \
  --channel-id C04KT7EH5RQ \
  --thread-ts 1776764135.019959 \
  --query CPUUtilization
```

Other useful queries:
- `CloudWatch`
- `writer`
- `쿼리`
- `Amazon Q`
- tenant/shard suffix like `560ac4c54db05db5bccc54788da901c5`

## What the script prints

- session metadata (`session_id`, `created_at`, `updated_at`, `channel_id`, `thread_ts`)
- injected thread context block, if present
- first user ask after the thread context
- relevant assistant findings snippets
- optional keyword-matched snippets across the transcript

## Why this is the minimal-step path

Without the script, the workflow is usually:
1. search `sessions.json`
2. find the matching session key
3. open the session JSON
4. manually locate the first user message
5. scroll for the relevant assistant conclusion

This skill compresses that into **one command**.

## Missing transcript recovery

If `sessions/sessions.json` maps a Slack thread to a `session_id` but `sessions/session_<session_id>.json` is absent, do **not** stop at `Session file not found`.

Fastest fallback: try the indexed session DB directly first:

```python
session_search(session_id="20260616_071223_b58951", role_filter="user,assistant,tool")
```

In current Hermes profiles, the JSON archive can be missing while `state.db` / `session_search` still has the transcript. If the session has a `parent_session_id`, inspect that too; Slack thread roots often live in the parent while the active continuation holds the compacted context.

If the DB lookup is absent or incomplete, inspect Slack cache files (`slack_api_cache/thread_<channel>_<thread_ts>.json` and `_summary.json`), then search session archives by durable alert identifiers such as Sentry issue id, error class, CloudWatch alarm name, or Slack permalink timestamp. The useful discussion may live in a later PR-review / CloudWatch-investigation session rather than the registry session. See `references/missing-session-file-recovery.md`.

## Caveats

- This is **not** canonical Slack history; it is Hermes' archived view.
- It only works if Hermes already saw the thread or the user pasted the alert/context into the session.
- A registry mapping can exist even when the transcript file is missing; recover via Slack cache + keyword `session_search` before saying there is no conversation history.
- If the root message never entered Hermes, use the live Slack/AWS debugging skills instead.
- A single session may contain multiple subtopics; use `--query` to isolate the alert-related parts.
- If `session_search` or the script finds nothing, check whether another Hermes profile handled the thread. For cross-profile archive inspection, see `references/cross-profile-session-archive-inspection.md`.

## Good workflow in practice

For a live Slack permalink/thread URL, prefer `slack-thread-root-retrieval` first. Only use this archive workflow if Slack API access is unavailable or returns an explicit error.

Archive workflow:

1. Try `--channel-id + --thread-ts` if you have them.
2. If you do not know the thread, run list mode on the channel.
3. Read the extracted `Thread context` block first.
4. Then read the filtered `Assistant findings` section.
5. If needed, rerun with a tighter `--query`.

## Verification

You have the right session if:
- the printed `thread_ts` matches the Slack thread you expect
- the injected thread context includes the alert root or prior thread messages
- the first user ask matches the investigation request

## Related skills

- `slack-thread-root-retrieval` — for live Slack root-message retrieval via API
- `hermes-slack-thread-context-debugging` — when Hermes failed to ingest the root properly
