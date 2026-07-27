# Missing session file recovery

Use this when `sessions/sessions.json` maps a Slack thread to a `session_id`, but `sessions/session_<session_id>.json` is absent.

## Pattern

A Slack thread can have a session registry entry before or without an archived transcript file. Do not stop at `Session file not found` if the user asks for the conversation history.

## Recovery workflow

1. Verify the registry mapping in `sessions/sessions.json`:
   - `session_key`
   - `session_id`
   - `origin.chat_id`
   - `origin.thread_id`
   - `created_at` / `updated_at`
2. Check the live/cache Slack thread files under the active profile, especially:
   - `slack_api_cache/thread_<channel>_<thread_ts_with_underscores>.json`
   - `slack_api_cache/thread_<channel>_<thread_ts_with_underscores>_summary.json`
3. If the transcript file is missing, search session archives by durable alert identifiers rather than by the missing `session_id`:
   - Sentry issue id, e.g. `7497304931`
   - distinctive error class, e.g. `TokenLimiterProcessor`
   - Slack permalink timestamp, e.g. `1780900141.141229`
   - CloudWatch alarm name or service name
4. Use `session_search` discovery results to find the actual analysis session and parent session. The real discussion may live in a later/continued session, while the original Slack thread session only has cache/registry state.
5. In the final answer, clearly distinguish:
   - registry session id exists but transcript file is missing
   - Slack cached thread messages found
   - actual analysis conversation session id(s) found via archive search

## Reporting shape

Keep it concise:

```text
매핑된 세션: <session_id> — registry에는 있으나 transcript 파일 없음.
Slack cache: <channel>/<thread_ts> summary found.
실제 분석 대화: <session_id> (parent: <parent_session_id>)
핵심 대화 요약: ...
```

## Pitfall

Do not claim “대화내역 없음” merely because `session_<id>.json` is absent. In Slack alert investigations, the same alert often reappears in follow-up PR review / CloudWatch investigation sessions, and those sessions contain the useful conversation history.