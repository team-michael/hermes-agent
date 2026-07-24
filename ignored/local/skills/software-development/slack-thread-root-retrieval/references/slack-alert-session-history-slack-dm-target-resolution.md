# Slack DM Target Resolution from Hermes Session Archives

Use this when a Slack group/channel response fails with `not_in_channel`, or when the user says to continue work in a named person's DM and the messaging target list only shows opaque Slack DM IDs.

## Goal

Map a human Slack display name (for example, `Minkyu Cho`) to a Slack DM conversation ID already known to Hermes, then send the handoff/follow-up to that DM instead of the inaccessible group thread.

## Workflow

1. List available messaging targets first if the user named a person/channel rather than a bare platform:
   - `send_message(action='list')`
   - Note candidate `slack:D...` DM IDs, but do not guess if several are possible.
2. Resolve the name from Hermes session archives:
   - Inspect the current profile's `sessions/sessions.json` for `origin.user_name`, `origin.user_id`, `origin.chat_id`, and `chat_type: dm`.
   - If needed, search gateway logs for `inbound message: platform=slack user=<name>` to find the associated `chat=<D...>`.
3. Prefer the DM whose `origin.user_name` matches the requested human and whose `chat_type` is `dm`.
4. Send to `slack:<DM_ID>` with a short context-setting message.
5. In the original thread, only state that the DM handoff was done; do not continue privileged details in a channel where the bot cannot post/read reliably.

## What to avoid

- Do not retry sending to a group/channel after Slack returned `not_in_channel`; membership is the blocker.
- Do not assume the most recent `slack:D...` target belongs to the requested user; verify via `sessions.json` or logs.
- Do not expose raw tokens, credentials, or secret-bearing request dumps while resolving the route.

## Minimal evidence to collect

A correct resolution has all three:

- `origin.user_name` equals the requested person.
- `origin.chat_type` is `dm`.
- `origin.chat_id` matches the `slack:D...` target used for `send_message`.
