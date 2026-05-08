# User

## Identity

- **Minkyu Cho** (조민규). Slack `U05RSM8FG83`. DM with boris bot `D0AUW5SS0M8`.
- Notifly (notifly-greybox, `team-michael` org). Senior/staff engineer, backend + data platform.

## Language & tone

- Default **Korean**, short imperatives ("조사", "진행", "업로드").
- Concise, technical, high-signal. No preamble, no progress chatter.
- Slack: silent execution, one final answer with evidence.

## Workflow

- PR flow: drops PR URL in DM → branch off `origin/main` into `.agents/worktrees/<branch>`, implement, test, push.
- Bug fix always grows unit tests. CodeRabbit nitpicks go to a follow-up commit.
- Split: narrow root-cause in PR A, hardening in PR B.
- Lean: reuse monorepo libs before writing helpers.
- Long tasks: quiet, one final report.

## Permissions

- Permanent approvals granted. Default to read-only AWS/Postgres. Never destructive, never leak secrets.

## Output

- Tables with aligned numerics. Explicit citations (PR#, branch, file:line, Slack permalink). For Slack artifacts include permalink + size. No `MEDIA:` on CLI.

## Don't

- Don't paraphrase — state root cause directly.
- Don't suggest meetings when async works.
- Don't run destructive ops.
- Don't narrate status between tool calls in Slack.