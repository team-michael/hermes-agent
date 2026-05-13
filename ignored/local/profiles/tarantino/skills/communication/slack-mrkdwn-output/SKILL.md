---
name: slack-mrkdwn-output
description: Format agent responses for Slack delivery via the Hermes gateway. The gateway auto-converts standard Markdown → Slack mrkdwn, so you should write **standard Markdown** (not raw mrkdwn). Key pitfall — writing `*bold*` directly gets converted to italic `_bold_`. Use this whenever the output target is Slack.
tags: [slack, formatting, messaging, mrkdwn, output, markdown]
---

# Slack Output Formatting (Hermes Gateway)

## CRITICAL: Tabular answer behavior in Slack (tarantino)

When a Slack response involves tabular data — and especially when the user explicitly asks for "표 형태", "table form", "in a table" — DO NOT emit Markdown pipe tables (`| col1 | col2 |`). Slack does not render them and the user sees raw pipe text.

Decision tree (apply every time a table-shaped answer is in the draft):

1. **Genuine 3+ columns × 3+ rows of parallel structured data** (matrix, comparison grid, mapping table where each row is one entity and each column is one attribute):
   - **Preferred for normal Slack replies:** include a hidden fenced directive in the final response:
     ````
     Visible lead-in text here.

     ```slack-table
     {"headers":["Col A","Col B","Col C"],"rows":[["1","2","3"],["4","5","6"]],"column_settings":[{"is_wrapped":true},{"is_wrapped":true},{"is_wrapped":true}]}
     ```
     ````
     SlackAdapter strips the fenced block and sends one native Block Kit table attached to the **same Slack message**. If the user is in a Slack thread, it stays in that thread because gateway metadata supplies `thread_ts`.
   - **Use `send_message(slack_table=…)` only when intentionally sending a separate/proactive message.** It now supports Slack thread targets as `slack:CHANNEL_ID:THREAD_TS`, but final-answer tables should use the directive above so the table lives inside the answer message.
   - The visible text should be a real one-line summary; the table is appended by Slack at the bottom of that same message.
2. **2-column key/value, ≤ 2 body rows, or short comparison**:
   - Use a bullet list inside the regular response — no `slack_table`, no pipe table.
   - Format: `- **Key** — value` per line.
3. **Wide alignment-critical text that is not really tabular** (e.g. log lines, code output):
   - Use a fenced code block (monospace).

Never emit Markdown pipe tables in a Slack-bound response. The validator on `slack_table` enforces ≥3×3, so undersized data must go through bullets.

Korean cue → English action:
- "표 형태로 답해줘" / "테이블로 정리" → run the decision tree above. Do NOT respond with `| ... |` pipes even if the user wrote them in their request.

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

- **Markdown pipe tables** (`| a | b |`) — render as raw pipe text. The gateway's Markdown → mrkdwn converter does not touch them.
- **Nested list auto-rendering** — Slack flattens list indentation. Use `•` / `-` + newlines for flat lists. For hierarchy, prefix with indented `◦` or `-` but expect flat visual.
- **H3+ headers** — `###` converts fine to bold, but there's only one level of bold, so don't rely on `#` vs `##` vs `###` for visual hierarchy.

## Native Slack tables — same-message directive + `send_message(slack_table=…)` fallback

As of 2026-05-12 tarantino supports two native Slack Block Kit table paths:

1. **Same-message final reply (preferred)** — write a fenced `slack-table` JSON directive in the final response. SlackAdapter strips the directive and attaches the table to the same `chat.postMessage` call. This is the path for normal answers, because it stays inside the current message/thread.
2. **Separate/proactive message** — call `send_message(..., slack_table={...})`. Use this only when you intentionally want to send a standalone message. It supports top-level targets (`slack:C...`) and threaded targets (`slack:C...:THREAD_TS`).

Both paths are **profile-gated** — only `tarantino` sees/uses them; the feature is invisible on the other five profiles (andrej / boris / csm / hashimoto / sdr) and runtime gates drop/ignore the feature elsewhere.

For the design pattern behind this gating (and what to do when you need to add the next profile-isolated feature), see `software-development/hermes-multi-profile-feature-rollout`. That skill carries the two-layer gate template, profile resolution snippet, restart strategy, and the slack-table rollout as a worked-example reference.

When to reach for it:

- 3+ columns × 3+ rows of genuinely parallel data that a reader wants to scan column-by-column (e.g. a competitor matrix, an experiment result grid, an ICP-mapping table).
- The reader benefits from column alignment — misaligned text would hurt comprehension.

When **NOT** to use it (prefer a bullet list in `message` instead):

- 2-column key/value lists → `• **Key** — value`
- Short comparisons (≤ 2 rows)
- Anything mobile-read-heavy — Slack's table block scrolls awkwardly on mobile, bullet lists do not.
- Styled text inside cells — cells are `raw_text`, so `**bold**` / `[link](url)` render as literal characters.

Preferred final-response shape (same Slack message / same thread):

````
Repo 관리 범위 — 이번 변경의 파일 분류입니다.

```slack-table
{"headers":["파일","위치","repo 관리?"],"rows":[["tools/send_message_tool.py","repo 안","관리됨"],["tests/tools/test_send_message_slack_table.py","repo 안","관리됨"]],"column_settings":[{"is_wrapped":true},{"is_wrapped":true},{"is_wrapped":true}]}
```
````

Separate/proactive call shape (use only when intentionally sending another message):

```python
send_message(
    target="slack:C0XXXXXXX",               # or "slack:C0XXXXXXX:1778626719.373509" for a thread reply
    message="ICP 레퍼런스 매핑 — Zai 주요 기능 4개",   # required text fallback
    slack_table={
        "headers": ["앱 고유 기능", "장면", "ICP 레퍼런스", "각도"],
        "rows": [
            ["Zai 알 까기", "2분 몰입", "Bitmoji 270.8K", "Identity play"],
            ["Hangout AI", "황당 모험 공유", "storytime 88.5K", "Fake adventure"],
            ["Switch-to-Reality", "일상 사진 난입", "FOMO 14.5K", "Invisible hangout"],
        ],
        "column_settings": [
            {"is_wrapped": True},
            {"is_wrapped": True},
            {"is_wrapped": True},
            {"is_wrapped": True},
        ]
    }
)
```

Hard limits enforced by the validator (runtime rejection with an instructive error + bullet alternative):

- ≥ 3 columns, ≥ 2 body rows (i.e. header + 2+ rows, minimum 3×3 shape)
- ≤ 20 columns, ≤ 100 total rows (Slack API limits)
- Cell values must be strings (raw_text)
- `column_settings[i].align` ∈ {`left`, `center`, `right`}; `is_wrapped` bool

The `message` field is still mandatory and becomes the mobile push / search / collapsed-thread-preview text — write a real one-line summary of what the table shows. The table itself is also mirrored into the session store as a plain-text grid so the LLM keeps context on subsequent turns.

Hard rules from the Slack docs that bite you (validator surfaces them):
- **Messages surface only** — not modals, not canvases, not home tabs.
- **One table per message** — 2+ yields `invalid_attachments` + `only_one_table_allowed`.
- **Appended as attachment at the bottom** of the message, not inline. Headers/prose go in `message`, table goes last.
- **Cell content** is `raw_text` (plain text only — `**bold**` and `[link](url)` render as literal characters).

For non-tarantino profiles or when the data does not meet the 3×3 minimum, fall back to the bullet / code-block patterns below.

**Verifying the feature is live in your session** (do this before assuming it works):

```python
import os, sys
os.environ['HERMES_PROFILE'] = 'tarantino'
sys.path.insert(0, '/home/ubuntu/.hermes/hermes-agent')
from tools.send_message_tool import SEND_MESSAGE_SCHEMA, _is_slack_table_enabled_for_current_profile
assert _is_slack_table_enabled_for_current_profile()
assert 'slack_table' in SEND_MESSAGE_SCHEMA['parameters']['properties']
```

If the assertion fails after a recent gateway restart, check:
- Tarantino gateway PID start time vs. last commit time on `feat/slack-table-block-tarantino` / `main`. Schema is built at module import, so pre-commit gateway processes will not see it.
- `SLACK_TABLE_ENABLED_PROFILES` allow-list in `tools/send_message_tool.py` still contains your profile.
- `HERMES_PROFILE` env is correctly set in the runtime context (gateway subprocess sets it; one-off CLI runs may not).

See `references/block-kit-table.md` for the full design rationale (why profile gating beats config flags in shared infra), the validator's instructive-error contract, and the rasterize-for-mirror pattern that prevents session-context loss for blocks-only messages.

## The #2 Pitfall: Wrapping the ENTIRE Message in Triple-Backticks

Observed 2026-05-06 (tarantino cron job `0d2144c61a4c`, first run). The agent composed a full daily report — headers, bold emphasis, emoji shortcodes, multiple code blocks for tables and prompts — and then wrapped **the whole thing** in an outer `` ``` ... ``` `` fence before returning it as the final response.

Result in Slack:
- `**bold**` rendered as literal text with asterisks visible
- `:clapper:` / `:point_down:` rendered as literal text instead of emoji
- Every section showed up in monospace font, gutting readability
- The inner code blocks (Top-10 table, Seedance prompts) were invisible as separate blocks because they were nested inside the outer fence

**Rule**: The Slack message body is **plain standard Markdown**. Only wrap **specific** sub-regions in triple-backticks:
- Fixed-width tables that need column alignment
- Code / command snippets
- Copy-paste prompts (Seedance, LLM prompts, etc.) where the user wants a clean clipboard copy

Never wrap:
- The whole report
- A section header + its body
- A paragraph of prose
- A bullet list

If you're tempted to wrap "for visual consistency," stop. Let the gateway's Markdown → mrkdwn pass do its job on the prose and use code fences only where monospace is functionally required.

## Cron-Prompt Authoring Rule (Slack-delivered cron jobs)

When a cron job delivers to Slack (`deliver: slack` or `deliver: slack:C...`), the cron agent runs **non-interactively** — no conversational correction loop exists to catch formatting mistakes. The cron prompt itself must re-embed Slack formatting guardrails, not just rely on the skill being loaded.

Minimum guardrails to paste into any Slack-delivering cron prompt:

```
## 🛑 Slack 출력 포맷 규칙

- 최종 메시지 전체를 triple-backtick 코드블록으로 감싸지 말 것. 감싸면 bold/이모지/링크 전부 깨진다.
- 본문은 **표준 Markdown 평문**으로 작성. 게이트웨이가 자동으로 Slack mrkdwn으로 변환한다.
- 강조는 `**bold**` (단일 별표 `*x*`는 italic으로 변환됨, 금지).
- 표는 **개별** triple-backtick 코드블록, 언어 태그 없이.
- 섹션 헤더는 `## 제목` 사용.
- 최종 응답 = Slack에 그대로 게시될 본문. `## Response` 같은 메타 래퍼 금지.
```

Confirmed failure mode (2026-05-06): loading `slack-mrkdwn-output` as a cron skill was NOT sufficient — the agent still wrapped the whole report. Embedding the explicit "do not wrap the whole message" rule in the cron prompt body is what makes it stick.

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

- **Never wrap the whole message in triple-backticks** (see "#2 Pitfall" section above). Only wrap specific tables / code / copy-paste prompts.
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

## Threaded Slack replies and same-message tables

Current tarantino behavior (2026-05-12+):

- **Normal final answer in a Slack thread**: use the `slack-table` fenced directive. SlackAdapter attaches the table to the same final answer message and preserves the inbound thread via gateway metadata. No tool call needed.
- **Proactive / separate send**: `send_message` now supports Slack threaded targets:
  - `slack:C0123456789` — top-level channel/DM message
  - `slack:C0123456789:1777331267.171749` — reply under that Slack thread (`thread_ts`)
  - `slack:D0123456789:1777331267.171749` — reply under a DM thread
- **Still not supported**: `slack:#channel-name` for Slack in this tool path. Use raw `C...`, `G...`, or `D...` IDs.

Important Slack UI constraint:
- The table is not inline between two paragraphs. Slack renders the Block Kit `table` block as an attachment-style block at the bottom of the **same message**. This is still much better than a separate top-level message: the table stays with the answer and stays inside the current thread.

Direct Web API workaround is now rarely needed. Use it only for advanced custom `blocks` beyond the table helper.

### Token + channel pitfalls

- **Root** `~/.hermes/.env` → default/boris profile's token. If you call `chat.postMessage` with this token on a channel the bot isn't a member of, you get `not_in_channel`.
- **Profile** `~/.hermes/profiles/<profile>/.env` → the correct per-profile bot token (e.g. tarantino). Use this when your cron job runs under a specific profile. Verify with `auth.test` first if unsure which token to use — they're all `xoxb-` prefixed and indistinguishable by shape.

### Character limit for single chat.postMessage

- Slack's hard cap is 40,000 chars for the `text` field, but message truncation shows up visually around ~4000 chars in the Slack UI.
- A same-message table reply sends one `chat.postMessage` call; keep the visible lead-in compact and put the structured content in the table.

## Verification Before Sending

Scan the draft for:
- **Is the entire message wrapped in an outer triple-backtick fence?** If yes, REMOVE the outer fence. Only inner tables / code / copy-paste prompts should be fenced.
- Any `*single-asterisk*` emphasis → replace with `**double**`. Otherwise it renders as italic.
- Any `| ... |` markdown table rows → convert to a `slack-table` directive if genuine ≥3×3 tabular data; otherwise bullets or code block.
- Any `_italic_` used purely for emphasis → convert to `**bold**` (Minkyu's preference).
- Any `<url|text>` written by hand → convert to `[text](url)` (let the gateway handle the transform).
- Code blocks with language tags → strip the language tag.
