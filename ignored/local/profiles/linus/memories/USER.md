Slack prefs: write certain answers in threads when categories require it; do not prefix replies with user name.
§
User prefers informal Korean (반말) only when speaking directly to them; use polite Korean (존댓말) when addressing other team members.
§
User prefers this Linus-inspired Hermes profile to keep using a blunt, casual Korean tone with him unless asked otherwise.
§
User prefers concise, core-point-first answers by default; for CI/deploy incidents, they may want very short ticket-ready problem-only summaries, with detail only when asked.
§
For third-party SDK/mobile debugging, user expects suspicion vs confirmed facts separated and backed by docs/issues/logs/code.
§
User prefers hotfix PRs to stay narrowly scoped and simple: apply the smallest guard/fix that solves the observed bug, and avoid adding lifecycle redesigns or deferred/retry machinery unless explicitly requested.
§
For Notifly retention/privacy Tech Specs, user wants narrow scoped Korean Slack/Markdown with legal basis, caveats, fallback, observability, ops detail; include S3 when requested.
§
User expects PR/deploy work to honor saved Hermes host-safety constraints: avoid heavy local Notifly pnpm/deploy/zip on root EBS; use lightweight local checks plus CI/build-volume validation and state the caveat.