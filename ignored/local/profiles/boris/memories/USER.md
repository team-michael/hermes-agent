# User

## Identity

- Name: **Minkyu Cho** (조민규).
- Slack: `@Minkyu Cho`, user_id `U05RSM8FG83`, DM channel with boris bot `D0AUW5SS0M8`.
- Employer: Notifly (notifly-greybox Slack workspace, `team-michael` GitHub org).
- Role: senior/staff-level engineer driving Notifly backend and data platform work. Primary user of the `boris` Hermes profile.

## Language & tone

- Default to **Korean**. Minkyu instructs in short Korean imperatives (e.g. "조사", "진행", "업로드해줘").
- Keep replies concise, technical, high-signal. Cut preamble.
- Avoid progress chatter in Slack — do the work, deliver one final answer with evidence and next step.

## Working style

- Direct PR flow: drops a PR URL and expects the agent to branch off `origin/main` into `.agents/worktrees/<branch>`, implement, run tests, push, handle CodeRabbit feedback.
- Grants **permanent approvals** to bot tool calls (`permanent` mode) for Hermes — does not want to rubber-stamp every shell command. Respect that trust by defaulting to read-only inspection, never destructive AWS/Postgres operations, and never leaking secrets.
- Prefers **yolo-style execution** on scoped tasks (just do it, report back) but expects clear final summaries with evidence.
- Lean stack preference: reuse existing libraries in the monorepo before introducing new ones. Ask/choose existing utility (e.g. `async-retry`) over writing a new helper.
- Explicit unit test growth expected alongside any bug fix (add cases for new edge paths).
- Okay with multi-PR split: fix the root cause narrowly in PR A, address broader hardening nitpicks in follow-up PR B.
- Does not mind long-running async tasks — prefers quiet work and one clean report, not status pings.

## Domain expectations

- Owns/knows deeply: `notifly-event` monorepo, `api-service`, `payment-executor`, event ingestion pipeline, Athena `notifly_analytics`, Sentry tunnel setup.
- Comfortable with AWS ECS Service Connect, Envoy sidecars, Node undici internals, Lambda runtimes.
- Cares about observability: if a failure does not show up in a metric, he will want an EMF/CloudWatch alarm added.
- Uses data from Athena (178 projects / 566M events / 11.8M users / 18.5k event types over 7d) as live reference when scoping.

## Output preferences

- Tables with aligned numerics for rankings, metrics, PR status.
- Explicit citations: PR numbers (`#3556`), branch names, thread timestamps, file paths with line numbers.
- When uploading artifacts to Slack, include permalink and file size.
- Do not emit `MEDIA:/path` markers on CLI — only on messaging platforms.

## Do not

- Do not paraphrase or soften findings. State the root cause directly.
- Do not suggest meetings when an async note is enough.
- Do not run destructive AWS, Postgres, or git operations.
- Do not narrate thinking or status between tool calls in Slack.
