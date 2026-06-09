# AI-agent token-budget incidents from Slack alerts

Use this reference when a Slack thread reports Notifly AI-agent streaming failures, `finishReason: length`, client disconnects, or `TokenLimiterProcessor` errors and the user asks whether a PR/branch really addresses the issue.

## Separate the failure planes

Do not treat all streaming failures as one bug. First classify the failing plane:

1. **Output-side length**
   - Model response ended with `finishReason: 'length'` or `max_tokens`.
   - Continuation/retry logic may help.
2. **Transport close/abort**
   - Browser/web-console connection closed, SSE drain/abort behavior matters.
   - Implicit close should generally drain upstream; explicit Stop may abort.
3. **Input-side context budget**
   - Input processor fails before the next model call, e.g.
     `TokenLimiterProcessor: No messages fit within the remaining token budget. Cannot send LLM a request with no messages.`
   - Output continuation and web-console close handling do **not** directly solve this.

## Evidence workflow

- Retrieve the Slack thread root and prod logs for the actual failure window before judging the PR.
- Inspect `internal-api-service` first for AI-agent processor/tool/model errors.
- Inspect `web-console` to confirm whether client close behavior is causal or just adjacent.
- In `internal-api-service` logs, correlate:
  - `AI_AGENT_METRIC` `tool_started` / `tool_finished`
  - tool name and result size fields such as `originalChars` / `previewChars`
  - processor errors from the Mastra input workflow
  - unhandled promise / process termination evidence if ECS tasks restarted
- Distinguish telemetry truncation from model-input compaction. A log wrapper that shortens previews may still return enough tool content to pressure the next LLM input context.

## Typical root cause pattern

A large tool result can fit the tool call itself but poison the next LLM turn by consuming context budget. One observed pattern:

- `api_get_statistics_summary` returned a very large raw statistics result.
- Telemetry wrapper logged that the result was truncated for preview.
- The next `TokenLimiterProcessor` step failed because no messages fit in the remaining input budget.
- The user-visible symptom was AI-agent streaming failure, but the root cause was input-side context bloat.

## Preferred remediation

- Preserve public/customer REST response contracts unless the user explicitly asks to change them.
- Compact only AI/MCP tool responses before they enter model context:
  - bounded summaries
  - top-N resources/metrics
  - totals and omitted counts
  - next-query hints
  - no raw heavy payload fields such as nested `message` blobs
- Add RED→GREEN regression tests at the tool boundary:
  - MCP tool response is compact and excludes raw heavy fields.
  - REST/shared service response remains unchanged.
- Treat unhandled stream rejection / ECS task crash as a separate stability fix, even if it was triggered by the same incident.

## Review conclusion template

When reporting back, make the distinction explicit:

- “This PR helps output continuation / close handling.”
- “It does/does not address the input-side `TokenLimiterProcessor` root cause.”
- “A direct fix is to compact the specific tool response before it is reinserted into model context while preserving REST API behavior.”
