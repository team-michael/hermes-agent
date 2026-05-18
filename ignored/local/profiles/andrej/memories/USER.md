Notifly GitHub/DM: share findings before PRs unless direct push; Conventional Commits; assign `clix-so-bot`; check reviews/checks; Cloudflare Preview Worker Deploy non-blocking unless asked.
§
Remote/container tasks: never assume local Hermes is target; verify intended system first, and never destructively mutate home dirs like /ubuntu/home, /home/ubuntu, or $HOME.
§
User studies Notifly infra; prefers senior mentor explanations with mechanisms, concrete flows, failures, verification, brief terms. For timeout/SSE, separate app vs infra, finite vs disabled, complete-response vs idle, and whether Service Connect is live.
§
In DMs, user wants infra explanations tailored to their Mobile/iOS + SDK Eng background: use iOS/SDK analogies only when mechanisms truly match, and flag SDK-side implications for contracts, retries, offline behavior, telemetry, or DX.
§
Slack product/sales: exact concise. Notion/org reports: initial hypothesis, neutral tone, tables/bullets, Korean metric names/units, minimal color, source caveats.
§
For MSP/Zendesk support ticket creation, user wants the drafted ticket body shown for confirmation before creating the ticket.
§
API prefs: REST nouns; no PII; users=`notifly_user_id`; PG/statistics only; no Athena API. CloudCheckr/FinOps measurement: prefer range queries over per-day loops when supported.