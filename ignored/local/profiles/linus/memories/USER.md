Slack prefs: thread replies when appropriate; no user-name prefix.
§
Korean tone: 반말 to user; 존댓말 to teammates/others.
§
User likes blunt, casual Korean tone.
§
User prefers concise, core-point-first answers by default; for CI/deploy incidents, they may want very short ticket-ready problem-only summaries, with detail only when asked.
§
For SDK/customer integration debugging, user expects confirmed facts vs suspicion backed by IPA/APK/code/docs/logs; include platform contrasts, min-version constraints, and customer-facing guidance.
§
User prefers hotfix/debug PRs narrowly scoped: smallest guard/fix or provider-boundary `code/message` logs only; avoid broad flow logging, lifecycle redesigns, retries, or deferred machinery unless requested.
§
For Notifly retention/privacy Tech Specs, user wants narrow scoped Korean Slack/Markdown with legal basis, caveats, fallback, observability, ops detail; include S3 when requested.
§
User expects PR/deploy work to honor saved Hermes host-safety constraints: avoid heavy local Notifly pnpm/deploy/zip on root EBS; use lightweight local checks plus CI/build-volume validation and state the caveat.
§
For engineering scoping, user wants practical code reuse/modification points and concise shareable Markdown artifacts.
§
For GitHub work, assign newly created items to the user as Assignee when applicable.