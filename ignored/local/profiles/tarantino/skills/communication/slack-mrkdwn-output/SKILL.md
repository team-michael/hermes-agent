---
name: slack-mrkdwn-output
description: Format agent responses for Slack delivery via the Hermes gateway. The gateway auto-converts standard Markdown → Slack mrkdwn, so you should write **standard Markdown** (not raw mrkdwn). Key pitfall — writing `*bold*` directly gets converted to italic `_bold_`. Use this whenever the output target is Slack.
tags: [slack, formatting, messaging, mrkdwn, output, markdown]
---

# Slack Output Formatting (Hermes Gateway)

## When to Use
- Any response whose delivery target is Slack (channel, thread, DM).
- `Current Session Context` in the system prompt indicates `Source: Slack`.
- Home channel is Slack (e.g. `clix-app-growth-project` profile).

## Critical Rule: Write Standard Markdown, Not Raw mrkdwn

The Hermes Slack gateway (`hermes-agent/gateway/platforms/slack.py` around lines 470–575) runs a **Markdown → mrkdwn conversion pass** on every message before sending. You write standard Markdown; Slack sees mrkdwn.

### Lesson learned (meta-rule)

When a user says "output for platform X, use X-native syntax," **do not immediately start emitting raw platform syntax**. First check whether the local delivery infrastructure (gateway, adapter, hook) already runs a transform. In this codebase, the Slack gateway's `_format_for_slack` function converts standard Markdown to mrkdwn automatically, so emitting raw mrkdwn (`*bold*`) gets **double-transformed** into the wrong thing (italic).

The verification step is cheap: `search_files("mrkdwn|markdown.*slack", path=hermes-agent/gateway/platforms/)`. Do this once per new delivery channel, then cache the finding in the relevant skill.

### Conversion table (what the gateway does for you)

| You write (Markdown) | Gateway converts to (mrkdwn) | Slack renders as |
|---|---|---|
| `**bold**` | `*bold*` | **bold** |
| `*italic*` | `_italic_` | _italic_ |
| `***both***` | `*_both_*` | **_both_** |
| `~~strike~~` | `~strike~` | ~~strike~~ |
| `` `code` `` | unchanged | `code` |
| triple-backtick block | unchanged | code block |
| `# Header` / `## Header` | `*Header*` (bold) | **Header** |
| `[text](url)` | `<url\|text>` | clickable **text** |
| `> quote` | unchanged | blockquote |

### The #1 pitfall (Minkyu caught this 2026-04-25)

If you write `*bold*` in Slack mrkdwn style directly, the gateway's regex interprets it as **Markdown italic** and converts it to `_bold_`, which Slack then renders as _italic_. So "Slack-friendly raw syntax" actually breaks in this environment.

**Rule:** Always use `**bold**` (standard Markdown) for bold. Never write single-asterisk `*bold*` and expect bold output.

## What Still Does NOT Work (gateway cannot fix these)

- **Tables** (`| a | b |`) — render as raw pipe text. Convert to bullet lists or fixed-width code block.
- **Nested list auto-rendering** — Slack flattens list indentation. Use `•` / `-` + newlines for flat lists. For hierarchy, prefix with indented `◦` or `-` but expect flat visual.
- **H3+ headers** — `###` converts fine to bold, but there's only one level of bold, so don't rely on `#` vs `##` vs `###` for visual hierarchy.

## Output Strategy (default for this profile)

1. **Titles / section headers** → `**Bold Title**` or `## Title` (both convert to Slack bold). Blank line after.
2. **Tabular data** → two options:
   - **Bullet list with bolded keys**:
     ```
     - **Category A** — 14.4M views, 19 videos
     - **Category B** — 13.5M views, 31 videos
     ```
   - **Fixed-width code block** (when alignment matters — code blocks use monospace font in Slack):
     ````
     ```
     Category          Views     Videos
     Widget Photo      14.4M     19
     Campus Anon       13.5M     31
     ```
     ````
3. **Lists** → `•` or `-` at line start + newline. Flat hierarchy is safer than deep nesting.
4. **Emphasis hierarchy** (Minkyu's preference — confirmed 2026-04-25):
   - `**bold**` for: section titles, key terms, quoted hooks/CTAs, callouts, meta emphasis. This is the default emphasis.
   - `_italic_` — **avoid by default.** Italic is visually weak in Slack. Only use for genuine titles of works (book/film titles) where convention requires italic, not for emphasis.
   - `` `code` `` for tool names, filenames, metric names, IDs, app names, short string literals.
5. **Links** → standard Markdown `[label](url)`. Gateway converts to `<url|label>`. For multiple links, put each on its own bullet for scannability.
6. **Numeric lists** (steps) → `1.` / `2.` at line start.
7. **Blockquote** for pulled quotes or callouts → `> ...` on each line (works unchanged).
8. **Emoji** → unicode directly (`🎉`) is fine; Slack auto-converts to `:tada:` style.

## Pitfalls

- **Never write raw Slack mrkdwn (`*bold*`, `<url|text>`) by hand.** The gateway's conversion pass expects Markdown input and will either double-transform or misinterpret it.
- **Triple-backtick code blocks with language hints (` ```python `)** — the language hint may show up in Slack output. Omit the language tag for Slack delivery.
- **Long messages (>4000 chars)** may be truncated. For very long deliverables, split into multiple messages or upload as a file.
- `&`, `<`, `>` as literal characters — gateway handles escaping automatically. Do not pre-escape.
- **Italic `*` regex is greedy-ish**: avoid `*` in prose (e.g., "*asterisk*") since it'll be interpreted as italic. Use `` `*` `` in backticks if you need to show a literal asterisk.

## Quick Reference Template (write exactly like this)

```
## Recommendation

Default bet: X because Y.

## Key Findings

- **Finding 1** — supporting detail, [source](https://source)
- **Finding 2** — supporting detail

## Data

\```
Metric        Value    Delta
Installs      142      +18%
CPA           $3.20    -12%
\```

## Next Step

1. Ship variant A to 2 campuses
2. Measure share/like ratio after 72h
3. Decision gate: ratio ≥ 5% → scale
```

## Threaded Replies: `send_message` Cannot Thread to Slack

**Critical finding (2026-04-28, cron job)**: The Hermes `send_message` tool **does not support `thread_ts`** for Slack. The `slack:chat_id:thread_id` target format is rejected with `Could not resolve 'chat_id:thread_id' on slack` — `_parse_target_ref` in `tools/send_message_tool.py` only recognizes the `chat_id:thread_id` suffix for Telegram topics, Discord threads, and Feishu; Slack falls through to `resolve_channel_name` which doesn't know the `:thread_ts` syntax.

Supported for Slack via `send_message`:
- `slack` — home channel (from `SLACK_HOME_CHANNEL`) ✓ verified
- `slack:C012345` — channel by ID (top-level post) ✓ verified

**NOT supported** (confirmed 2026-04-29):
- `slack:C012345:1777331267.171749` — threaded reply. Errors with `Could not resolve 'chat_id:thread_id' on slack`.
- `slack:#channel-name` — hash-prefixed channel name. Errors with `Could not resolve '#channel-name' on slack`. Despite what the generic `send_message` docstring says about `#channel` formats, Slack specifically rejects this — use the raw `C...` ID or fall back to bare `slack` (home channel alias).

**Response shape for `thread_ts` capture** (confirmed 2026-04-29): `send_message` returns `{"success": true, "chat_id": "C...", "message_id": "1777417771.544779", ...}`. Use `response["message_id"]` as `thread_ts` for subsequent `chat.postMessage` calls.

### Workaround: call Slack Web API directly

For header+thread posting patterns (cron-style daily reports):

```python
import json, urllib.request

# Load profile .env (not the root ~/.hermes/.env — each profile has a distinct token)
env = {}
with open('/home/ubuntu/.hermes/profiles/<profile>/.env') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        k, v = line.split('=', 1)
        # Strip inline comments — profile .env files often have `KEY=value  # description`
        v = v.split('#', 1)[0].strip().strip('"').strip("'")
        env[k] = v
token = env['SLACK_BOT_TOKEN']

# Step 1 — header via send_message (it auto-converts Markdown → mrkdwn)
#   Capture `message_id` from the response → that's the `thread_ts`.
# Step 2 — thread replies via direct chat.postMessage with thread_ts parameter.

def post_thread(text, channel, thread_ts):
    payload = {
        "channel": channel, "thread_ts": thread_ts, "text": text,
        "mrkdwn": True, "unfurl_links": False, "unfurl_media": False,
    }
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps(payload).encode('utf-8'),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())
```

### Formatting in direct-API thread replies

Direct `chat.postMessage` does **NOT** run the gateway's Markdown→mrkdwn conversion. You **must** send native Slack mrkdwn syntax — not standard Markdown.

**Correction (2026-04-29)**: An earlier version of this skill claimed `**bold**` and `[label](url)` "render OK in Slack's own parser on `mrkdwn=True` for most cases." That is **false** in current Slack. On direct `chat.postMessage` with `mrkdwn=True`:
- `**bold**` renders as the literal text `**bold**` (asterisks visible)
- `## Header` renders as the literal text `## Header`
- `[label](url)` renders as the literal text `[label](url)`

You must convert Markdown → mrkdwn yourself before the API call. Drop-in converter (verified working 2026-04-29):

```python
import re

def md_to_mrkdwn(text: str) -> str:
    """Convert standard Markdown to Slack mrkdwn for direct chat.postMessage."""
    lines = text.split('\n')
    out = []
    in_code = False
    for line in lines:
        # Toggle code block; strip any language tag (Slack dislikes ```python)
        if re.match(r'^\s*```', line):
            out.append('```')
            in_code = not in_code
            continue
        if in_code:
            out.append(line)
            continue
        # ATX headers → bold line
        m = re.match(r'^(#{1,6})\s+(.*)$', line)
        if m:
            out.append(f"*{m.group(2).strip()}*")
            continue
        new = line
        # Order matters: triple-star first, then double, then link.
        new = re.sub(r'\*\*\*(.+?)\*\*\*', r'*_\1_*', new)   # ***both***
        new = re.sub(r'\*\*(.+?)\*\*', r'*\1*', new)           # **bold**
        new = re.sub(r'~~(.+?)~~', r'~\1~', new)                # ~~strike~~
        new = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<\2|\1>', new)  # [x](y)
        # NOTE: single-asterisk italic (*x*) is intentionally left alone.
        # Source rarely uses it, and converting would corrupt the just-made *bold*.
        # If you need italic, write _x_ directly in the source — Slack treats _x_ as italic.
        out.append(new)
    return '\n'.join(out)
```

Pattern for header + thread (verified end-to-end, 2026-04-29):

```python
# Stage 1: header via send_message (gateway converts Markdown → mrkdwn)
resp = send_message(action="send", target="slack", message=header_markdown)
thread_ts = resp["message_id"]

# Stage 2: thread replies via chat.postMessage (we convert Markdown → mrkdwn ourselves)
for part_md in parts:
    post_thread(md_to_mrkdwn(part_md), channel, thread_ts)
```

### Token + channel pitfalls

- **Root** `~/.hermes/.env` → default/boris profile's token. If you call `chat.postMessage` with this token on a channel the bot isn't a member of, you get `not_in_channel`.
- **Profile** `~/.hermes/profiles/<profile>/.env` → the correct per-profile bot token (e.g. tarantino). Use this when your cron job runs under a specific profile. Verify with `auth.test` first if unsure which token to use — they're all `xoxb-` prefixed and indistinguishable by shape.

### Character limit for single chat.postMessage

- Slack's hard cap is 40,000 chars for the `text` field, but message truncation shows up visually around ~4000 chars in the Slack UI.
- For long reports, split into 3-4 replies of ~3500 chars each, all targeting the same `thread_ts`.

## Verification Before Sending

Scan the draft for:
- Any `*single-asterisk*` emphasis → replace with `**double**`. Otherwise it renders as italic.
- Any `| ... |` markdown table rows → convert to bullets or code block.
- Any `_italic_` used purely for emphasis → convert to `**bold**` (Minkyu's preference).
- Any `<url|text>` written by hand → convert to `[text](url)` (let the gateway handle the transform).
- Code blocks with language tags → strip the language tag.
