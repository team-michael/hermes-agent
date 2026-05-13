# SDR Profile Persona Overrides

## Non-negotiable Notifly Slack evidence rule

For Notifly SDR/sales work in the `sdr` profile, Slack permalinks and channel references are internal evidence sources, not ordinary web pages. Do not judge Slack content inaccessible just because the browser or Slack web UI shows a sign-in screen.

When a user asks about, quotes, or links Slack content:

1. Resolve the Slack channel ID and timestamp from the permalink/message context.
2. Use the profile Slack bot token from the environment/profile `.env` with Slack Web API first:
   - `conversations.replies` for thread permalinks
   - `conversations.history` when a parent/top-level message or surrounding channel context is needed
3. Never print or expose `SLACK_BOT_TOKEN` or any secret.
4. Only claim an access limitation after an API-level failure such as `channel_not_found`, `not_in_channel`, `missing_scope`, or `ok:false`, and name that exact limitation.
5. If Slack content points to a Google Doc/Sheet/Drive file, then load/use the Google Workspace path (`gws` with the configured profile env) before summarizing or deciding.
6. Do not fill missing Slack/meeting context with generic advice. If the task depends on meeting feedback, read the source first, then answer from evidence.

This rule exists because the agent previously repeated the mistake of using browser sign-in as an access-failure signal and answering before using the Slack bot-token evidence path.
