For Notifly GitHub PR work, the user prefers PRs to be assigned to `clix-so-bot`; after creating or updating a PR, review comments and GitHub check results should be checked, while Cloudflare Preview Worker Deploy can be treated as non-blocking unless explicitly needed.
§
User explicitly corrected that home directories such as /ubuntu/home, /home/ubuntu, or $HOME must never be deleted or destructively mutated, whether on a remote container or local system.
§
User corrected that remote/container tasks must never be executed against the local Hermes runtime by assumption; establish and verify the intended target system first, and never destructively mutate home directories.
§
User is studying Notifly infra and is AWS/ECS Service Connect–unfamiliar; prefers senior-engineer mentor explanations with mechanisms, concrete flows, failure modes, verification steps, and brief term definitions. For timeout/SSE topics, separate app vs infra fixes, finite vs disabled tradeoffs, complete-response vs idle timeout, and whether Service Connect is live.
§
In DMs, user wants infra explanations tailored to their Mobile/iOS + SDK Eng background: use iOS/SDK analogies only when mechanisms truly match, and flag SDK-side implications for contracts, retries, offline behavior, telemetry, or DX.
§
User's Cloudflare 2FA is in iOS Passwords/암호 app.