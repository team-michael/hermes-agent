# Block Kit `table` block — design notes for same-message + `send_message(slack_table=…)` integration

Captured 2026-05-12 during the work that added profile-gated Slack table support to Hermes (`tools/send_message_tool.py`, `gateway/platforms/slack.py`, branch `feat/slack-table-block-tarantino`). Initial commit: `65f10c3be`; follow-up adds same-message/thread support.

This file is the durable explanation of WHY the integration looks the way it does. The SKILL.md body explains HOW to use it. Read this when you're considering changing the design — the trade-offs documented here will save you from regressions.

## Slack capability summary

- Block Kit `table` block was announced 2025-08-14 (https://docs.slack.dev/changelog/2025/08/14/block-kit-table-block/).
- Reference: https://docs.slack.dev/reference/block-kit/blocks/table-block.
- Surfaces: **Messages only** — not modals, not canvases, not home tabs, not App Home.
- Always rendered as an **attachment at the bottom** of the message. Cannot be inlined between other blocks; cannot precede non-table content. The `text` and `blocks[0..n-1]` are body/header content, the table is appended after.
- **One table per message.** Sending two yields `invalid_attachments` with `response_metadata.messages = ["only_one_table_allowed"]`.
- Hard limits: max 100 rows total (header + body), max 20 cells per row, max 20 column_settings entries.
- Cells: `raw_text` (plain text only) or `rich_text` (Slack's element-tree format — NOT mrkdwn string). Writing `**bold**` in a `raw_text` cell renders the asterisks literally.
- Column settings: `align` ∈ {left, center, right}, `is_wrapped` boolean. Use `null` to leave a column at defaults inside an array entry.

## Why profile gating instead of a config flag

The shared-infra constraint is the load-bearing fact. The Hermes codebase under `~/.hermes/hermes-agent/` is **a single working copy** that all 6 profiles (andrej, boris, csm, hashimoto, sdr, tarantino) load from. Each profile runs its own gateway process with `HERMES_PROFILE` set, and they share imports.

A `config.yaml` flag (config-keyed) was the obvious first design. We rejected it because:

1. **Flag-off ≠ code-absent.** When other profiles restart for unrelated reasons (deploy, OS reboot, crash recovery), they load the new code path. A bug in the new path can fire under any profile, not just the opt-in one.
2. **Schema vs. runtime mismatch.** Even if the gateway runtime gates on the flag, the LLM tool schema is computed at module import. If the schema always contains `slack_table`, every profile's LLM sees it and may try to use it — then get rejected at runtime, polluting the model's reasoning loop with errors.
3. **Multi-tenant principle.** Features that touch a single tenant should be invisible to other tenants. Anything visible (in the schema, in the docs, in the API surface) is a future support burden across all 6 profiles.

The chosen design is a **module-level allow-list** (`SLACK_TABLE_ENABLED_PROFILES = frozenset({"tarantino"})`) consulted in three places:

- **Schema build time** — `_build_send_message_schema()` only adds the `slack_table` property when the active profile is in the allow-list. Other profiles' LLMs never see the parameter exists.
- **Runtime tool path** — `_handle_send` re-checks the allow-list and silently drops the field when not enabled. Catches programmatic invocations that didn't go through the schema.
- **Final-response adapter path** — `SlackAdapter.send()` only consumes fenced `slack-table` directives when the same allow-list says the current profile is enabled. Other profiles leave the text untouched, preventing accidental hidden syntax rollout.

To add a profile to the feature: add its name to `SLACK_TABLE_ENABLED_PROFILES`, restart that one gateway. No config plumbing, no env vars to forget.

## Why minimum 3×3, not "let the model decide"

The single biggest LLM failure mode for new structured-output tools is misuse. With `slack_table` exposed naively, models love to render bullet-able 2-column key/value lists as tables. On Slack mobile this is **catastrophic** — tables don't reflow, columns get clipped, narrow phones show a horizontally-scrolling rectangle of text where 4 bullets would have read fluently.

The validator hard-rejects below 3 columns or below 2 body rows, with an instructive error that names the bullet alternative inline:

```
slack_table requires at least 3 columns (got 2). For 2-column data, use a
bullet list in the `message` field instead, e.g.:
- **Key A** — value A
- **Key B** — value B
```

The error text is design surface, not just diagnostic. The model reads it, sees the suggested fallback, and on the retry produces bullets. Don't soften this without re-validating that the model actually changes behavior — the inline example is what makes it work.

## Mirror rasterization — why blocks-only messages corrupt session context

`gateway.mirror.mirror_to_session` writes the sent message into the SQLite session DB so subsequent turns can see what the bot already said. It stores **text only**. A message that carries `blocks` but empty `text` would mirror as an empty row, breaking cross-turn context — the next turn the LLM doesn't know it just sent a table.

Two mitigations stack for the `send_message(slack_table=…)` tool path:

1. **Mandatory `message` field.** Even with `slack_table`, the tool schema marks `message` as required. It serves as Slack's `text` fallback (push notifications, search, collapsed-thread previews) AND as the mirror's primary text.
2. **Plain-text rasterization.** `_rasterize_slack_table_for_mirror` renders the table as a fixed-width ASCII grid and appends it to the mirror text. Session DB then has both the human-readable summary and the table contents the next turn can reason about.

For the final-response `slack-table` directive path, the adapter strips the directive and sends the visible lead-in as `text`. The original assistant message in the gateway session still contains the model's final response; the user-visible Slack message receives the native table. Keep the lead-in specific enough to make push/search/collapsed previews useful.

## API error surface to preserve

Slack's `chat.postMessage` returns structured errors that the model needs to see verbatim to react correctly:

- `invalid_blocks` — block JSON malformed
- `only_one_table_allowed` — second table in a single message
- `blocks_mismatched_elements` — element-tree shape wrong (rich_text only)
- `msg_too_long` — total payload over Slack's ~40KB cap

The current `_send_slack_with_blocks` surfaces `data["error"]` and the first 3 entries of `response_metadata.messages` joined by `; `. Keep the join short (3-entry cap) so error strings stay scannable. **Do not** wrap these in generic "Send failed" without the original code — the model needs the slug to retry intelligently.

## Tests that codify the design

`tests/tools/test_send_message_slack_table.py` and `tests/gateway/test_slack.py` cover:

- Schema visibility per-profile (tarantino exposes, the other 5 + None do not)
- Validator: minimums, maximums, type errors, instructive-message presence
- Block builder: header row prepended, column_settings null-handling, JSON round-trip with Korean text
- Rasterizer: column alignment, Korean unicode survival
- Runtime gate: programmatic invocation on non-allow-listed profile silently downgrades to text path; allow-listed profile takes blocks path; validator errors propagate as `error` in the result dict
- Slack threaded targets: `slack:C...:THREAD_TS` parses and passes `thread_ts` to Slack Web API
- Same-message final response directive: `SlackAdapter.send()` strips a fenced `slack-table` JSON block, posts `blocks=[table]`, preserves `thread_ts`, and leaves the directive untouched on non-allow-listed profiles

Re-run with: `python -m pytest tests/tools/test_send_message_slack_table.py tests/tools/test_send_message_tool.py tests/gateway/test_slack.py -q`

## Future extensions (deliberately deferred)

- **`rich_text` cells with bold/links/mentions.** Required if we want clickable cells. Postponed because converting Markdown → rich_text element tree is non-trivial and the mini-formatter has its own LLM-misuse failure modes.
- **Multi-table messages.** Slack rejects with `only_one_table_allowed`. A helper that auto-splits into multiple chained messages would be useful for week-by-week reports but adds order/continuity bugs around `thread_ts`.
- **Cross-platform shape.** Telegram/Discord/Matrix have no equivalent. The current design ignores `slack_table` on non-Slack targets silently — keep this; resist the urge to add per-platform table renderers, they always look worse than bullets in those clients.

## Repository

- Working tree: `/home/ubuntu/.hermes/hermes-agent/`
- Origin: `NousResearch/hermes-agent` (upstream, do NOT push directly)
- Fork: `team-michael/hermes-agent` (our team, push here)
- Branch for this feature: `feat/slack-table-block-tarantino`
- Verifying live in a running gateway:
  ```bash
  ps -o pid,lstart,cmd -p $(pgrep -f 'profile tarantino gateway' | head -1)
  # Compare lstart against `git log -1 --format=%ci HEAD` — gateway must be newer.
  ```
