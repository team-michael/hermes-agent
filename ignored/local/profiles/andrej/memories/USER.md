Notifly GitHub: share findings pre-PR unless direct push; Conventional Commits; assign `clix-so-bot`; verify checks/reviews; ops mitigation may close PR.
§
Remote/container tasks: never assume local Hermes is target; verify intended system first, and never destructively mutate home dirs like /ubuntu/home, /home/ubuntu, or $HOME.
§
User studies Notifly infra; incidents/perf need scope/denominator, observed-vs-inferred, code-grounded semantics, full access-pattern coverage, and live-metric-backed ops timing.
§
In DMs, user wants infra explanations tailored to Mobile/iOS+SDK Eng background: use analogies only when mechanisms match; flag SDK implications for contracts/retries/offline/telemetry/DX.
§
Slack/incidents: concise formal KR; non-dev-friendly handoffs; current evidence/problem only unless asked; fixed-width tables. Linear: reuse thread bot ticket; no dups.
§
MSP/Zendesk: show draft; no internal Slack refs.
§
API prefs: REST nouns/no PII/users=`notifly_user_id`; PG/docs canonical. PR validation: local stage OK; matrix explicit. CS eval: source-only, tool-use not prose, no over-call; compact row# layout, OOS/GTO colors.
§
Post-session: proactive memory + umbrella skills.
§
For Cognito Hosted UI visual refinements, user prefers updated CSS as an attachment for browser-console testing before Terraform.