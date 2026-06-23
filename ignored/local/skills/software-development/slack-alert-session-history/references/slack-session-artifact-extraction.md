# Slack session-content review and artifact extraction

Use this when the user gives a Slack permalink and asks to 확인/복원/요약 a prior agent session, especially when the thread ended with a generated file or Slack table.

## Workflow

1. Parse the permalink:
   - `/archives/<channel>/p<digits>` → `channel=<channel>`
   - timestamp: first 10 digits + `.` + remaining 6 digits
   - example: `p1782104832148109` → `1782104832.148109`
2. Fetch the live thread first with `slack-thread-root-retrieval/scripts/fetch_slack_thread.py`.
   - This gives authoritative Slack message order, replies, file metadata, and cache paths.
3. If the user asks for “세션 내용”, recover Hermes session context too:
   - Try `inspect_slack_alert_session_history.py --channel-id ... --thread-ts ...`.
   - If it says `Session file not found`, do not stop. Use the printed session id with `session_search(session_id=..., role_filter="user,assistant,tool")` or search by durable artifacts/filenames from the Slack thread.
4. Summarize the evolution, not just the final answer:
   - original ask / attached file
   - important corrections from the user or teammates
   - final classification/decision
   - final artifact location/name
5. If a final artifact exists in Slack (`files[]`), inspect it, not only the message text:
   - read file metadata from cached raw thread JSON
   - use `url_private_download` with the Slack bot token loaded from the active profile env
   - save under the active profile cache, e.g. `~/.hermes/profiles/<profile>/slack_api_cache/`
   - verify row/line count or parse a sample before reporting what it contains

## Why this matters

Slack text often only says “CSV 파일로 준비했습니다” or “Slack table로 다시 올렸습니다”. The useful deliverable is in `files[]` or Slack Block Kit table payload, and the Hermes JSON archive may be missing even though the session DB still has the transcript.

## User-facing summary shape

Keep it short:

- thread title / purpose
- session id if useful
- final artifact name and size/rows if verified
- bullet list of major corrected decisions
- note any caveat, e.g. “session JSON was missing, recovered via session DB + Slack API”

Avoid dumping the whole table unless the user asks for the table itself.