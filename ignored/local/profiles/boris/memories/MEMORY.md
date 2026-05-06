# Memory

Durable engineering context for the `boris` Hermes profile at Notifly. Recovered from Slack evidence (2026-04-23 → 2026-05-06) after the profile's memory was lost.

## Environment

- Hermes profile: `boris`. Bot Slack user_id `U0AUSNJQKJR`, display name "Boris Cherny" / `boris`.
- Slack workspace: `notifly-greybox.slack.com`, team_id `T03N2U9PATE`. Bot is a member of ~17 channels/DMs (including `#monitoring`, `#engineering`, `#incidents`, private `notifly-tips`, private `cs`).
- Main working directory: `/home/ubuntu/.hermes/profiles/boris/` for profile artifacts; repos live under `~/workspace/`.
- Primary repos: `team-michael/notifly-event` (service monorepo) and `team-michael/notifly-event-data-pipeline` (Glue ETL). `notifly-event` is the default source of truth.
- Git worktree convention: every task branch lives under `.agents/worktrees/<branch-name>`, created from `origin/main` (never from possibly-stale local `main`). `git fetch origin && git worktree prune` before creating. Clean up merged-branch worktrees.
- Session model recently running as `us.anthropic.claude-opus-4-6-v1` / `claude-opus-4-7` on Bedrock.
- Hermes quirk: preflight compression triggers near ~136k tokens. `/model` is a slash command and agent cannot switch models itself. Occasional `Failed to initialize OpenAI client: [Errno 2] No such file or directory` error is harmless noise.

## Notifly product surface

- `api-service` is the primary Node 20+ ingestion service for `trackEvent` / `setUserProperties`. Runs in ECS with a Service Connect sidecar (Envoy). Talks to `event-proxy` over `http://event-proxy:80/records` (loopback VIP, not public). Downstream chain: api-service → event-proxy → KPL → Kinesis.
- `payment-executor` is a Node 22 Lambda. `packages/pricing` pulls `tr46@0.0.3`, which hits Node 22's `punycode` DEP0040 deprecation warning. CloudWatch filters `%ERROR%` in `#monitoring` catch this as a false alarm — the warning is not an error. See Linear/PR thread around 2026-04-24.
- `#monitoring` Slack channel is fed by Amazon Q alerts off CloudWatch `%ERROR%` metric filters. Many alarms are noise; audit patterns before paging (see `cloudwatch-alarm-noise-audit` skill).
- Athena analytics sit in `notifly_analytics` database, region `ap-northeast-2`, workgroup `primary`. Core tables: `notifly_event_logs`, `notifly_message_events`. Partitions: `dt, h, project_id, pre_conversion`. IAM user `notifly-internal-agent` has read + write to `s3://raw-events-query-logs/athena-query-results/`.
- 7-day scale reference (2026-04-17 → 2026-04-23): 178 active projects, 566.3M events, 11.82M Notifly users, 6.15M signed-in (52.1%), 18,520 event types, 95.1% signed-in event ratio, 12.9% server-side ratio, avg 3.18M events/project, avg 47.9 events/user. Q1 messaging send: 141M (Jan) + 117M (Feb) + 165M (Mar) = 423.5M.
- `track-event.js:138-145` uses a catch-and-drop + fake-200 strategy on downstream failures. The SDK client sees success but the record is actually lost. `fake-200` is a placeholder until the ETIMEDOUT root cause is fixed; when fixed, replace with retry + DLQ fallback.
- Sentry tunnel proxy issue: `next.config.js` sets `tunnelRoute: '/monitoring'`. ETIMEDOUT bursts to `34.160.81.0:443` came from this tunnel trying to reach Sentry from inside VPC networking. Root cause was TCP-connect, not application code.

## Engineering conventions (Minkyu's preferences)

- PR workflow: Minkyu drops a PR URL in DM. Agent creates a fresh worktree, runs e2e tests, commits, pushes. Never work in the primary checkout.
- "Lean" style: reuse existing libraries/helpers before writing new ones. Example: ETIMEDOUT retry uses `async-retry` already in the workspace rather than a bespoke loop.
- Always pair a bug fix with a unit test expansion (19 → 21 cases pattern seen on PR #3556).
- CodeRabbit nitpicks: address them in a separate follow-up commit after the first review pass, not in the initial PR.
- After pushing a second commit, watch for GitHub `pulls/<n>.head.sha` sync lag. Safe forcing function: `git commit --allow-empty -m "ci: re-trigger"`.
- Never log tokens/keys. Redact before writing evidence to `/tmp` or committing.

## Tooling notes

- Slack: bot token is in `/home/ubuntu/.hermes/profiles/boris/.env` as `SLACK_BOT_TOKEN`. Scopes include `channels:history`, `groups:history`, `im:history`, `users:read` but **not** `mpim:*` — `conversations.list` default types fails with `missing_scope`. Use `users.conversations` to enumerate bot-member channels (cheaper and scope-safe).
- Slack file upload: use `files.getUploadURLExternal` + `files.completeUploadExternal` with `thread_ts`. The old `files.upload` is deprecated.
- AWS access in the environment is read-only. Treat it as a debugging lens, not a mutation tool.
- Postgres creds exist but are read-only too. Inspection only.
- GitHub token is scoped wide enough for normal PR/issue/review flow. Use `gh` CLI or REST directly.
- Cloudflare creds (account id + API token) exist for preview Worker debugging.

## Recurring incidents (learned patterns)

- `AggregateError [ETIMEDOUT]` on `fetch(event-proxy)` is Node 20 happy-eyeballs + Envoy CDS hiccup, not a downstream failure. Fix = undici dispatcher `autoSelectFamily: false`, family 4, plus retry wrapper. See skill `notifly-service-connect-etimedout-diagnosis`.
- `DEP0040 punycode` warnings from `payment-executor` are Node 22 deprecation noise via `tr46@0.0.3`. Not an incident.
- Paywall "계속" button missing on overseas payments — known `#engineering` bug thread 2026-04-xx, fix went through PR review.
- Cafe24-worker SQS DLQ spikes — see skill `notifly-cafe24-worker-dlq-investigation`.

## Filesystem state

- `/tmp/hermes_slack_threads_boris.json` — 28 threads, evidence of this profile's activity.
- `/tmp/hermes_slack_threads_boris_digest.md` — 358 KB readable digest.
- `/tmp/collect_boris_targeted.py` — targeted Slack collector (uses `users.conversations`, reply prefilter, secret redaction). Keep for the next recovery.
