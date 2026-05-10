# Bulk Slack channel Q/A dataset export notes

Session learning from building an LLM training CSV dataset from a Slack CS channel.

## When this applies

Use this reference when the user asks for a dataset of Slack 문의/답변, FAQ, support Q/A, or LLM training examples from a channel over a long time range.

## Recommended workflow

1. **Export channel history by channel ID**
   - Use `conversations.history` with `channel`, `oldest`, `latest`, `inclusive`, and paginated `cursor`.
   - For private channels, rely on known channel IDs from the Hermes channel directory if `conversations.list` lacks scope but history access works.
   - Do not print Slack tokens; load from the active profile `.env` or environment.

2. **Fetch complete threads for Q/A reconstruction**
   - For each history message with `reply_count > 0`, call `conversations.replies(channel=<id>, ts=<root ts>)`.
   - Treat `messages[0]` as the question/root and `messages[1:]` as the answer sequence.
   - Persist raw history and raw threads as JSONL under `~/.hermes/...` so the CSV build step can be rerun without re-calling Slack.

3. **Plan for timeout/rate-limit resumability**
   - Long one-year exports can exceed a 600s command timeout and Slack can rate-limit.
   - Write append/resume logic that detects the oldest exported history `ts`, then continues with `latest=<oldest exported ts - epsilon>` down to the target `oldest`.
   - Track existing thread root timestamps so resumed runs do not duplicate thread records.
   - Slack history pagination is newest-to-oldest; reaching the exact requested `oldest` may not happen if the channel has no messages before a few hours later. Validate by checking the oldest message timestamp, not by assuming failure.

4. **Build category CSVs from raw JSONL**
   - Keep file count low by grouping threads into coarse categories rather than exact duplicate detection.
   - Good Notifly-style categories: push/in-app/popup, SDK/events/users, Kakao messaging, error/delivery/logs, console/settings/permissions, analytics/export, docs/onboarding/sales, segment/audience, webhook/API, SMS/email/LINE, billing/payment, security/compliance, general/other.
   - Create `index.csv` with category ID, category name, file name, relative path, row count, date range, description, keywords, and example question.
   - Each category file should contain rows like `qa_id`, `category_id`, `category_name`, `source_channel_id`, `thread_ts`, `root_datetime_utc`, `question_text`, `answer_text`, `message_count`, `reply_count`, and notes.

5. **Privacy/safety defaults**
   - Pseudonymize Slack users/authors as `user_###`.
   - Replace Slack mentions with pseudonyms.
   - Convert unlabeled URLs to host-only placeholders when possible.
   - Warn that customer names and message body content may still need review before external training or sharing.
   - Keep raw JSONL out of the final share zip unless explicitly requested.

6. **Validate and package**
   - Verify every category file exists and has rows.
   - Verify the sum of category CSV rows equals the total Q/A row count.
   - Generate a manifest with source range, counts, category counts, privacy notes, and validation status.
   - Package only `index.csv`, `manifest.json`, and `csv/` into the share zip.
   - Use `sha256sum` and `stat` to report integrity and size.

## Pitfall discovered

If pseudonymized authors are named `user_001`, keyword classification that includes English keywords like `user` or `id` can accidentally push most rows into `SDK / Event / User Properties`. Remove pseudonym patterns such as `@?user_\d+` from the classification text before scoring, and avoid overly broad keywords like bare `user` and `id`.

## Verification checklist

- `wc -l raw/history.jsonl raw/threads.jsonl` confirms raw export volume.
- A small script checks min/max timestamps in both raw files.
- CSV build summary reports `qa_row_count`, `category_file_count`, `category_counts`, and `validation.ok=true`.
- `index.csv` is inspected after classification to catch skewed categories before packaging.
