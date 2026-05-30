Notifly GitHub: share findings pre-PR unless direct push; Conventional Commits; assign `clix-so-bot`; verify checks/reviews; ops mitigation may close PR.
§
Remote/container tasks: never assume local Hermes is target; verify intended system first, and never destructively mutate home dirs like /ubuntu/home, /home/ubuntu, or $HOME.
§
User studies Notifly infra; wants exact user/project/device timelines and strict observed-vs-inferred splits; verify QA/prod app separation before claiming SDK/env mixing.
§
In DMs, user wants infra explanations tailored to Mobile/iOS+SDK Eng background: use analogies only when mechanisms match; flag SDK implications for contracts/retries/offline/telemetry/DX.
§
Slack: concise formal KR, fixed-width milestone tables. Linear: reuse thread bot ticket; no duplicates.
§
MSP/Zendesk: show draft; no internal Slack refs.
§
API prefs: REST nouns/no PII/users=`notifly_user_id`; PG/docs canonical. Campaign/Journey create detail must include editable fields; no draft endpoint. CS eval: source→intent, tools+params, Answer flow, no keyword lists, 10-row batches.
§
Post-session: proactive memory + umbrella skills. Sheets QA: new tabs, compact columns, color split rows, avoid over-splitting/context blocks.
§
For Cognito Hosted UI visual refinements, user prefers updated CSS as an attachment for browser-console testing before Terraform.