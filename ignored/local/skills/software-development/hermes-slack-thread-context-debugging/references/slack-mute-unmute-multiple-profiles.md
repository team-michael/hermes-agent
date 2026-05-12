# Slack `/mute` / `/unmute` with multiple Hermes profiles in one thread

Session finding from a Notifly Slack thread where two Hermes profiles were both present and mute/unmute appeared broken.

## Symptom

A Slack thread can include mentions to more than one Hermes bot/profile, e.g. a CSM profile and an Andrej profile. Users may expect `/mute` or `/unmute` to affect “Hermes in this thread” globally, but the actual implementation is profile-local.

## Key mechanism

- Slack mute state is stored per profile in `<profile>/slack_muted_threads.json`.
- The key shape is `<channel_id>:<thread_ts>`.
- Session keys use the same thread identity, e.g. `agent:main:slack:group:<channel_id>:<thread_ts>`.
- Because each gateway/profile has its own `HERMES_HOME`, each profile has an independent muted-thread file.
- Muting one profile does not mute or unmute another profile.

## Command parsing gotcha

Slack user-visible messages may look like `<@BOT_ID> /mute` or `<@BOT_ID> /unmute`.

Relevant flow:

1. Slack adapter strips the addressed bot mention for the target bot/profile.
2. If the remaining text starts with `/`, it becomes a command event.
3. Group/shared sessions may store user-visible transcript text with a prefix like `[Minkyu Cho] <@BOT_ID> /mute`, which can make command messages look like ordinary chat in the saved session.
4. For the non-addressed Hermes profile, the same Slack message may remain a normal mention/text event instead of a command for that profile.

## Investigation recipe

1. Identify the Slack thread:
   - channel ID
   - parent/thread timestamp
   - exact bot user IDs mentioned in `/mute` and `/unmute` messages
2. Inspect every relevant profile, not just the active one:
   ```bash
   find ~/.hermes/profiles -name slack_muted_threads.json -print
   ```
3. Compare each muted file for the target key:
   ```text
   <channel_id>:<thread_ts>
   ```
4. Inspect profile logs around the command timestamps:
   - `inbound message: ... msg='<@BOT_ID> /mute'`
   - `Sending command '/mute' response ...`
   - `Sending response (62 chars)` often corresponds to `Muted...`
   - `Sending response (57 chars)` often corresponds to `Unmuted...`
5. Inspect `sessions/sessions.json` for the Slack session key and bound `session_id`.
6. Inspect the session JSON for `[user_name] <@BOT_ID> /mute` or `/unmute` transcript lines, but do not assume those lines mean command parsing failed.

## Interpreting common outcomes

### One profile muted, another still responds

Most likely expected-by-implementation behavior: mute is profile-local. The remaining responding profile has not been muted.

### `/unmute` appears ignored

Check whether the `/unmute` mention targeted the same bot/profile whose `slack_muted_threads.json` contains the thread key. If it targeted a different Hermes bot, it will not unmute the muted profile.

### `/mute` appears to work, then Hermes “comes back alive”

Check for a non-target inline command leak:

```text
<@other_bot> /unmute
```

A muted profile should not wake up for another bot's `/unmute`, but if the mute gate only checks the inline command name after stripping any leading mention, `<@other_bot> /unmute` can bypass `is_thread_muted()`. If the thread has an existing session, mention gating may then allow the message through as ordinary text, producing a normal model response. This is distinct from real unmute: the muted file may still contain the thread key while the profile nevertheless replied once.

Concrete diagnostic pattern from the Notifly multi-profile thread:

- `csm` / `@grae_yu` had the target thread key in `csm/slack_muted_threads.json`; `andrej` / `@andrej` did not.
- A session transcript line like `[Minkyu Cho] <@other_bot> /unmute` followed by `assistant: 언뮤트됨` was **not** proof that the command handler ran. It was a normal LLM response because the message still began with `<@other_bot>`, not `/unmute`, for the current profile.
- Real command-handler evidence is stronger in gateway logs: `Sending command '/mute' response ...` for active-session bypass commands, or a profile-local muted-file mtime/key change. Generic `response ready ... response=5 chars` / `assistant: 언뮤트됨` can be model text.
- Always compare the profile-local muted file before trusting UX text. In the observed case, a profile said “다시 응답 모드” while its `slack_muted_threads.json` still contained the target key.

### A command produced a normal model response

Likely causes:

- the mention targeted a different bot than the inspected profile;
- mention stripping did not leave a leading `/` for that profile;
- a muted-thread `/unmute` exception failed to verify that the command targets the current bot;
- the saved session transcript includes `[user_name]` prefix, making the command look non-command after persistence;
- the message went through the active-session bypass path and interrupted an existing run after sending the command response.

## Code locations

- `gateway/run.py`
  - command dispatch for `canonical == "mute"` / `"unmute"`
  - `_handle_mute_command()` / `_handle_unmute_command()`
  - active-session command bypass and run interruption
  - shared multi-user session text prefixing
- `gateway/platforms/base.py`
  - `MessageEvent.get_command()`
  - command bypass / response ordering
- `gateway/platforms/slack.py`
  - Slack mention stripping
  - command vs message classification
  - thread ID extraction from slash/message payloads
- `<profile>/slack_muted_threads.json`
  - persistent per-profile muted thread state

## Product implication

If users expect mute/unmute to control all Hermes profiles in a Slack thread, the implementation needs either:

1. a shared muted-thread registry across profiles; or
2. fan-out command handling that applies the command to all configured Hermes profiles in that workspace/thread; or
3. explicit UX copy: “Muted this Hermes profile only.”

Until then, always report mute state profile-by-profile.