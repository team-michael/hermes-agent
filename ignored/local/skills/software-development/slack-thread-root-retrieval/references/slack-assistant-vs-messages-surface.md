# Slack Assistant surface vs Messages tab for Hermes DMs

## When to use
Use this when a Hermes Slack bot keeps DM conversations as separate Slack `thread_ts` sessions internally, but the user says the UI is wrong: conversations appear under Slack Assistant **채팅/내역** instead of the app's **메시지 / Messages** tab.

## Symptom
- Hermes session keys are already thread-scoped, e.g. `agent:main:slack:dm:<D-channel>:<thread_ts>`.
- `channel_directory.json` shows DM entries like `<D-channel>:<thread_ts>`.
- Slack UI still shows the conversation under Assistant `채팅` / `내역`, not the normal App Home `Messages` tab.

## Root cause pattern
This is usually **not** `dm_top_level_threads_as_sessions` and not a Hermes session-keying issue. It is a Slack app surface/manifest issue.

Hermes' generated Slack manifest may enable both:

```json
"features": {
  "app_home": {
    "home_tab_enabled": false,
    "messages_tab_enabled": true,
    "messages_tab_read_only_enabled": false
  },
  "assistant_view": {
    "assistant_description": "Chat with Hermes in threads and DMs."
  }
}
```

When `assistant_view` is present and Assistant events/scopes are installed, Slack can show DMs in the Assistant `채팅/내역` surface. Other Hermes bots that appear under a separate `메시지` tab likely do not have the Assistant surface enabled.

## Fix direction
Do **not** set `dm_top_level_threads_as_sessions: false` if the user wants thread-specific DM sessions. That collapses DM session scoping and is the wrong fix.

Instead, keep message tab settings and remove Assistant-specific manifest pieces:

- Remove `features.assistant_view`.
- Remove bot scope `assistant:write`.
- Remove bot events:
  - `assistant_thread_started`
  - `assistant_thread_context_changed`
- Keep:
  - `features.app_home.messages_tab_enabled: true`
  - `features.app_home.messages_tab_read_only_enabled: false`
  - `message.im`
  - `im:history`, `im:read`, `im:write`, `chat:write`

After changing the Slack app manifest, save and reinstall the app to the workspace, then restart the Hermes gateway.

## Verification
Before concluding, inspect local session evidence:

- `sessions/sessions.json` should have Slack DM origins with non-empty `thread_id`.
- `channel_directory.json` should include entries like `<D-channel>:<thread_ts>`.
- If those are present, internal thread/session scoping is working; the remaining problem is Slack UI surface selection.

## User-facing explanation pattern
Say:

> 내부 Hermes 세션은 이미 DM `thread_ts`별로 분리되어 있습니다. 문제는 Slack 앱이 Assistant surface로 설치되어 있어서 `채팅/내역` UI로 보이는 것입니다. 다른 Hermes처럼 `메시지` 탭으로 보이게 하려면 Slack manifest에서 `assistant_view`, `assistant:write`, Assistant events를 제거하고 Messages tab만 유지해야 합니다.

