# Slack permalink PDF attachments → document summary

Use this when a user points at a Slack permalink and asks to inspect attached PDFs/checklists/guidelines.

## Pattern

1. Parse the permalink:
   - `/archives/{channel}/p{10digits}{6digits}` → `channel`, `message_ts={10}.{6}`
   - query `thread_ts` if present, otherwise use `message_ts`.
2. Load the Slack bot token from the active Hermes profile env if it is not ambient. Never print the token.
3. Fetch Slack data API-first:
   - `conversations.replies(channel, ts=thread_ts)` for thread context and target message.
   - Also run a tight `conversations.history` window around `message_ts` when the permalink points at a specific reply; this verifies exact message/file metadata even if the thread is long or odd.
4. Inspect the target `message.files[]`; treat files as PDFs when any of these match:
   - `mimetype == application/pdf`
   - `filetype == pdf`
   - `name/title` ends with `.pdf`
5. Download each PDF using `url_private_download` or `url_private` with `Authorization: Bearer <SLACK_BOT_TOKEN>`. Save under `~/.hermes/workspace/...`, not `/tmp`.
6. Extract text:
   - Prefer `pdftotext -layout` plus `pdfinfo` when available; it is fast and works well for text-based checklists/decks.
   - Use PyMuPDF/pymupdf4llm when installed or when page-level/search extraction is needed.
   - If extracted text is sparse for a slide-like PDF, render pages with `pdftoppm` and OCR/vision the visible text.
7. Summarize by artifact and then map against the user’s active doc/task. For checklist + guideline pairs, separate:
   - required evidence list from the checklist
   - interpretation/acceptance criteria from the guideline deck
   - gaps/risks in the current working doc

## Output shape

For Notifly certification/support docs, a useful concise shape is:

- Attachment inventory: PDF count, names, page counts.
- PDF 1 checklist: required evidence by section.
- PDF 2 guideline: review criteria and important caveats.
- Cross-check against the current Google Doc: concrete 보완 필요 / 충돌 가능 / 오탈자.

## Pitfalls

- Browser access to Slack usually lands on login and is not evidence of inaccessibility. Use Slack Web API first.
- Slack messages can have mixed files: PDF plus Google Doc link/attachment. Do not treat the Google Doc as another PDF.
- `search.messages` may be unavailable for bot tokens; exact permalink retrieval via `conversations.replies`/`history` is enough.
- File names often contain `+`, Korean, parentheses, or `&`; use argv-based subprocess calls or careful quoting.
- Do not preserve one-off downloaded PDFs as memory. Keep the reusable workflow here only.
