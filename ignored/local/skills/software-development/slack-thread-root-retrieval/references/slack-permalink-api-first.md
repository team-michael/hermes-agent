# Slack permalink API-first retrieval

Use when a Notifly Slack permalink is provided and browser access shows a login wall or incomplete context.

## Required sequence

1. Parse the permalink:
   - channel from `/archives/<channel>`
   - timestamp from `/p<digits>` by converting to Slack `ts` form, e.g. `1779356063863879` -> `1779356063.863879`
2. Use the active profile Slack bot token from the Hermes environment/profile; never print or persist the token.
3. Fetch the message via Slack Web API, usually:
   - `conversations.history` with `channel`, `latest=ts`, `inclusive=true`, `limit=1`
   - `conversations.replies` when thread context is needed
4. For Slack file attachments, use `url_private_download` or `url_private` with the bot token. Save downloaded media only under the allowed Hermes profile/cache path.
5. If the attachment is an image, run vision analysis on the downloaded file and summarize both message text and screenshot contents.
6. Use browser navigation only as a last fallback; a Slack login wall is not evidence that the message is inaccessible.

## Pitfall

Do not ask the user to re-upload screenshots or paste the message until the API-first path has been attempted. Browser login walls are expected in agent runtimes and should not stop the retrieval flow.
