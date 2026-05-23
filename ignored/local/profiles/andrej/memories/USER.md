Notifly GitHub: share findings before PR unless direct push; Conventional Commits; assign `clix-so-bot`; verify reviews/checks; CF Preview non-blocking.
§
Remote/container tasks: never assume local Hermes is target; verify intended system first, and never destructively mutate home dirs like /ubuntu/home, /home/ubuntu, or $HOME.
§
User studies Notifly infra; wants mentor-style explanations with concrete flows/failures/verification, brief AWS terms, and clear “improved vs still to fix vs actually fixed?” splits. Avoid repetitive Notifly notes.
§
In DMs, user wants infra explanations tailored to their Mobile/iOS + SDK Eng background: use iOS/SDK analogies only when mechanisms truly match, and flag SDK-side implications for contracts, retries, offline behavior, telemetry, or DX.
§
Slack product/sales: exact concise. Notion/org reports: initial hypothesis, neutral tone, tables/bullets, Korean metric names/units, minimal color, source caveats.
§
MSP/Zendesk: show draft; no internal Slack refs.
§
API prefs: REST nouns; no PII; users=`notifly_user_id`; PG/stats default; docs canonical. api-service JS/CJS+JSDoc+typecheck. After compaction continue active task. For existing feature branches, build on that branch, not origin/main replay.
§
Post-session: expects proactive memory plus class-level umbrella skill/reference updates; avoid narrow one-off skills.