For Notifly GitHub/DM work, share findings or patch direction first and wait for explicit approval before opening PRs; when PRs are opened, assign `clix-so-bot`, check reviews and GitHub checks, and treat Cloudflare Preview Worker Deploy as non-blocking unless requested.
§
Remote/container tasks: never assume local Hermes is target; verify intended system first, and never destructively mutate home dirs like /ubuntu/home, /home/ubuntu, or $HOME.
§
User is studying Notifly infra and is AWS/ECS Service Connect–unfamiliar; prefers senior-engineer mentor explanations with mechanisms, concrete flows, failure modes, verification steps, and brief term definitions. For timeout/SSE topics, separate app vs infra fixes, finite vs disabled tradeoffs, complete-response vs idle timeout, and whether Service Connect is live.
§
In DMs, user wants infra explanations tailored to their Mobile/iOS + SDK Eng background: use iOS/SDK analogies only when mechanisms truly match, and flag SDK-side implications for contracts, retries, offline behavior, telemetry, or DX.
§
Slack product/sales: concise exact-question answers; no broad frameworks. Notion docs: medium-density; sample before bulk changes. Investigations: evidence-tight, exact resource IDs.
§
For MSP/Zendesk support ticket creation, user wants the drafted ticket body shown for confirmation before creating the ticket.