# Memory

## Environment

- Profile `boris`. Bot `U0AUSNJQKJR`. Workspace `notifly-greybox.slack.com` (team `T03N2U9PATE`). DM with Minkyu: `D0AUW5SS0M8`.
- Profile dir `/home/ubuntu/.hermes/profiles/boris/` — `.env` holds `SLACK_BOT_TOKEN`, AWS, GitHub, Postgres, Cloudflare creds.
- Repos: `team-michael/notifly-event` (default) + `team-michael/notifly-event-data-pipeline`. Clones under `~/workspace/` or `~/.hermes/workspace/`.
- Git worktrees: `.agents/worktrees/<branch>` from `origin/main`. Always `git fetch origin && git worktree prune` first. Never work in primary checkout.

## Access & safety

- AWS + Postgres: read-only. Inspection only.
- GitHub: use `gh` or `hermes-github-api` (never leak `GITHUB_TOKEN`).
- Never echo tokens; redact before writing to `/tmp` or commits.
- Never create/delete files outside `~/.hermes` unless user names exact path.

## Slack quirks

- Scopes: `channels/groups/im:history`, `users:read`. **No `mpim:*`** → use `users.conversations`, not `conversations.list`.
- Uploads: `files.getUploadURLExternal` + `files.completeUploadExternal` with `thread_ts`. `files.upload` is deprecated.

## Skill pointers (don't duplicate here)

- Notifly alert triage → `check`
- ETIMEDOUT on event-proxy → `notifly-service-connect-etimedout-diagnosis`
- Cafe24 DLQ → `notifly-cafe24-worker-dlq-investigation`
- CloudWatch noise → `cloudwatch-alarm-noise-audit`
- Slack thread root recovery → `slack-thread-root-retrieval`, `slack-aws-chatbot-thread-context-debugging`
- Remotion MP4 + PptxGenJS deck (TIPS case study, palette, 6-scene) → `remotion-video-production`
- Profile recovery from Slack → `hermes-profile-slack-recovery`
§
- `team-michael/notifly-catalogs` repo: 고객사례 플레이북 PPTX(`notifly-playbook-pptx/build_deck.js`, React→PptxGenJS+PNG) + `notifly-pdf-insights` 가이드. 로컬엔 LibreOffice 없음 → `preview_png/` + `vision_analyze`로 QA. 카피 감사 체크리스트는 powerpoint 스킬 references/copy-audit-checklist.md.