Notifly GitHub: share findings before PR unless direct push; Conventional Commits; assign `clix-so-bot`; verify reviews/checks; CF Preview non-blocking.
§
Remote/container tasks: never assume local Hermes is target; verify intended system first, and never destructively mutate home dirs like /ubuntu/home, /home/ubuntu, or $HOME.
§
User studies Notifly infra; wants mentor-style explanations with concrete flows/failures/verification, brief AWS terms, and “improved vs still to fix vs fixed?” splits. Avoid repetitive notes.
§
In DMs, user wants infra explanations tailored to Mobile/iOS+SDK Eng background: use analogies only when mechanisms match; flag SDK implications for contracts/retries/offline/telemetry/DX.
§
Slack/product/sales/planning: concise/high-signal, formal Korean tables for milestones; avoid verbose or overly colloquial phrasing.
§
MSP/Zendesk: show draft; no internal Slack refs.
§
API/CS prefs: REST nouns; no PII; users=`notifly_user_id`; PG/stats default; docs canonical; api-service JS/CJS+JSDoc+typecheck; CS/MCP minimal; MCP provider quirks belong in internal proxy/tools, not generic clients.
§
Post-session: expects proactive memory plus class-level umbrella skill/reference updates; avoid narrow one-off skills.
§
For Cognito Hosted UI visual refinements, user prefers updated CSS as an attachment for browser-console testing before Terraform.