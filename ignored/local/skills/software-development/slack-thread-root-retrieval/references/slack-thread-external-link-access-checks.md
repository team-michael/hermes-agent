# Slack thread external link access checks

Use this when the user asks whether links embedded in a Slack thread are accessible.

## Pattern

1. Parse the Slack permalink and fetch the thread with `conversations.replies` first. Do not rely on Slack unfurl text alone; extract every raw URL from message text/blocks/attachments.
2. For each external URL, do a cheap HTTP probe first:
   - `curl -sS -L -A 'Mozilla/5.0' -o /dev/null -w 'final=%{url_effective} status=%{http_code} content_type=%{content_type}\n' '<url>'`
   - Record redirects/authwalls separately from transport success. `200 text/html` can still be a login wall.
3. For pages where content matters, open representative URLs in the browser and inspect rendered text. Some sites render public content behind a dismissible sign-in modal.
4. Classify access by what content is actually visible, not by status code alone:
   - `accessible`: full/meaningful page body visible without login.
   - `partially accessible`: body visible, but full comments/media/downloads require login.
   - `login/authwall`: redirected to sign-in/join page or only login prompt visible.
   - `unreachable`: non-2xx/blocked/network failure.
5. Summarize per link/type with caveats around logged-out limitations.

## LinkedIn-specific notes

- Individual public post URLs often return `200 text/html` and may show a “Sign in to view more content” modal; dismissing it can reveal the post body and some comments.
- Company listing pages such as `/company/<slug>/posts/` may redirect to an authwall/login even when individual company post permalinks are viewable.
- LinkedIn logged-out access is inconsistent by object type and time. Do not claim a post is inaccessible until checking the rendered page, not just the Slack unfurl.
- DM-only artifacts promised in comments (PDFs, Notion links, prompt files) are not accessible from the public post unless they are explicitly linked in visible text.

## User-facing answer shape

Keep it short and answer the central yes/no first:

> 네, 대부분 접근 가능합니다. 스레드의 개별 LinkedIn 공개 포스트 N개는 본문을 볼 수 있었고, 회사 게시글 목록/댓글 전체/DM 자료는 로그인 또는 별도 권한이 필요했습니다.

Then include a compact table: `link/type | access | note`.
