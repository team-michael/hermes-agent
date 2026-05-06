---
name: hermes-integration-support-audit
description: Determine whether a third-party service is natively supported by Hermes Agent, supported only via skills/API calls, or available through MCP. Use when asked if Hermes 'supports X' or whether a dedicated service account/seat will work natively.
version: 1.0.0
author: Hermes Agent
license: MIT
---

# Hermes integration support audit

Use this when you need to answer questions like:
- "Does Hermes natively support Linear/GitHub/Service X?"
- "If we buy a seat or create a service account, will Hermes work as a first-class user there?"
- "Is this a built-in tool, a skill-only workflow, or an MCP integration?"

## Goal
Classify support into one of four buckets:
1. **Built-in native tool/integration**
2. **Skill-only support**
3. **Native MCP path**
4. **Not supported / custom work required**

Also separate:
- **identity/account support** (can Hermes act as a dedicated account?)
- **automation/trigger support** (will Hermes wake up automatically on assignment/events?)

These are often confused.

## Procedure

1. **Load relevant skills first**
   - Load the service skill if one exists (e.g. `linear`)
   - Load `native-mcp`
   - Load `hermes-agent` if the question is about Hermes platform capabilities

2. **Check whether the service is a built-in Hermes tool**
   - Search `tools/` for service-specific filenames or registrations.
   - Search the repo for service names, auth env vars, endpoints, and tool registrations.
   - Run `hermes tools list` to see whether a dedicated toolset appears.

3. **Check whether support exists only as a skill**
   - Search skills / release notes / docs for the service name.
   - If the service appears in skills but not in built-in tools, classify as **skill-only support**.

4. **Check MCP path**
   - Confirm Hermes has native MCP support:
     - inspect `model_tools.py` for `discover_mcp_tools()`
     - confirm CLI has `hermes mcp add/list/configure`
   - Run `hermes mcp list` to see whether any server is already configured.
   - If a service-specific MCP server is not configured, report that Hermes can still support it through MCP in principle, but it is not currently wired.

5. **Check live runtime state**
   - Verify whether relevant env vars are present (e.g. `LINEAR_API_KEY`).
   - If credentials are present, perform a minimal read-only API check (viewer/me query) rather than assuming they work.
   - Distinguish:
     - env var exists
     - credential is valid
     - integration is actually configured in Hermes

6. **Answer in two layers**
   - **Platform truth:** built-in vs skill vs MCP vs unsupported
   - **Operational truth:** what a dedicated seat/account actually buys you

## Important distinctions

### Native vs usable
Something can be **usable** without being **native**.
Example pattern:
- No built-in Hermes tool for the service
- But a skill can call the service API directly with a token
- Or Hermes can use a service MCP server via native MCP support

That means: **operationally possible, but not first-class native product support**.

### Identity vs automation
A dedicated seat/service account usually solves **identity/audit trail**:
- actions happen as that account
- comments/updates appear under that account
- permissions are isolated

It does **not** automatically solve **event-driven automation**:
- Hermes will not wake up on assignment by magic
- you still need Slack prompting, cron polling, webhooks, or another trigger loop

## Recommended response structure
1. Direct answer: native / not native / MCP-capable / skill-only
2. Evidence from repo + runtime checks
3. What a dedicated seat/account enables
4. What it does not enable
5. Recommended rollout path (pilot vs production)

## Example conclusion template
- Hermes does **not** have a built-in native `<service>` tool.
- Hermes **does** support `<service>` operationally through `<skill/API>` and/or via native MCP if an MCP server is configured.
- A dedicated seat/account lets Hermes act **as that account** for audit and ownership.
- It does **not** create automatic triggers; polling/webhooks/Slack are still needed.

## Competitive / adjacent-agent comparison
When the user asks whether **other agents** (e.g. OpenClaw, IronClaw) support the same pattern, extend the audit instead of answering from vibes.

1. **Pin down which product/repo is actually meant**
   - Names may be overloaded, renamed, or have migration history.
   - Verify the current public repo or docs before comparing.

2. **Separate channel-account identity from external-system seat identity**
   - Some agents support multiple Telegram/Discord/WhatsApp accounts per agent.
   - That does **not** imply first-class assignable identity in Linear/GitHub/Jira.
   - If docs say replies still come from the same channel account, treat that as evidence **against** per-agent external identity.

3. **Look for official wording about dedicated external accounts**
   - Strong positive evidence: docs that explicitly say things like
     - "create a new GitHub account for your agent"
     - "authenticate with this account/token"
     - examples using `@me`, "my PRs", or "assigned to me" tied to the authenticated credential owner
   - This supports **seat-like operation through an external account**, but still is **not** the same as product-native seat provisioning.

4. **For issue trackers, distinguish 3 levels**
   - **Native seat support**: product explicitly frames the agent as a first-class assignable user/seat in the external system
   - **Credential-backed operation**: agent acts as whatever user owns the API key/token
   - **Generic MCP/CLI bridge**: service is reachable, but only through an external integration layer

5. **Prefer official docs/repo evidence over blog copy**
   - README, docs, skills, manifests, auth setup, MCP registry, and examples are strongest.
   - If public evidence is weak, say so explicitly.

## Pitfalls
- Do not equate "env var exists" with "integration works" — verify with a live API call.
- Do not equate "MCP is native" with "service integration is already configured".
- Do not say Hermes supports a service natively just because a skill exists.
- Do not treat channel multi-account support as proof of Linear/GitHub/Jira seat support.
- Do not treat "use a separate GitHub/Linear account" guidance as proof of product-native seat provisioning; it only proves credential-backed operation through that account.
- Do not conflate account identity with autonomous workflow orchestration.
