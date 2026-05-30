# Slack permalink API-first retrieval with screenshots

Use when the user gives a Slack permalink and asks to check the content, thread, or screenshots.

## Durable lesson

Do not start with browser navigation. Slack web permalinks often land on a sign-in wall, which is not evidence that the content is inaccessible. Treat the permalink as structured Slack data and use the bot token first.

## Minimal flow

1. Parse the permalink:
   - `/archives/{channel}/p{10digits}{6digits}`
   - `channel = {channel}`
   - `ts = {10digits}.{6digits}`
2. Load `SLACK_BOT_TOKEN` from the active profile env if missing from process env. For Andrej profile this is usually `/home/ubuntu/.hermes/profiles/andrej/.env`.
3. Retrieve the exact message:
   - `conversations.history` with a tight window around `ts`, or
   - `conversations.replies(channel, ts)` if it may be a thread/root.
4. If the message/thread contains `files[]`, inspect `url_private_download` or `url_private` metadata.
   - For PDFs, download under `~/.hermes/workspace/<task>/`, run `pdfinfo`, `pdftotext -layout`, and `pdfdetach -list` to distinguish referenced attachments from embedded files.
   - If the PDF is slide-like or an exported email thread with screenshot evidence, run `pdfimages -list` or render pages with `pdftoppm` and OCR/vision only the relevant pages.
   - If the message also contains Google Docs/Sheets links or Google-native Drive files, follow with authenticated Google Workspace access rather than treating the Slack file metadata as the document content.
5. Download screenshot/image/PDF files with the Slack bearer token in the `Authorization` header, without printing or logging the token.
6. Run OCR/vision/local extraction on downloaded files before summarizing.
7. Only use browser Slack access as a last fallback, and only after Slack API failure codes are known.

## Evidence to include in final answer

- Message author and timestamp if relevant.
- Main message text and thread context.
- Screenshot-derived facts separately from message text.
- Any API limitation by exact Slack error code (`not_in_channel`, `missing_scope`, `channel_not_found`, etc.).

## Pitfall

If the first attempt hits a Slack browser login page, recover immediately by switching to the API path. Do not tell the user the content cannot be viewed until the bot-token API path has failed.