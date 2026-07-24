# Checking Cloudflare Workers AI / AI Gateway Status During Incidents

When investigating `api-service` 4xx/5xx spikes, Lambda AI-worker errors, or any alert where Notifly's Cloudflare Workers AI dependency may be involved, verify external AI gateway health before concluding server-side root cause.

## When to use

- User explicitly asks whether the incident was caused by a Cloudflare Workers AI outage or rate limit.
- `api-service` 4xx spike coincides with AI-related routes or the `notifly-ai-worker` Lambda.
- Any alert where the suspected root cause is "external AI provider rejected / timed out / rate-limited."

## Fast status check

Query Cloudflare's public status API (no auth required) and filter for Workers AI:

```bash
curl -fsS 'https://www.cloudflarestatus.com/api/v2/summary.json' -o /tmp/cfstatus.json
```

Inspect:
- `components` with names containing `Workers AI` or `AI Gateway`
- `incidents` within last 7 days with `impact` != `none`
- `scheduled_maintenances` that overlap the incident window

Convert timestamps to KST in the final answer.

## Account-scoped probes (requires `CLOUDFLARE_API_TOKEN`)

If the public status page is green but you suspect account-level rate limiting, use the CF REST API:

```bash
# List account
curl -fsS 'https://api.cloudflare.com/client/v4/accounts' \
  -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}"
```

```bash
# List Workers scripts to verify AI worker exists
curl -fsS "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/workers/scripts" \
  -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}"
```

```bash
# List AI Gateways
curl -fsS "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/ai-gateway/gateways" \
  -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}"
```

**Known gaps**: As of May 2026, the documented per-gateway request/analytics endpoints (e.g., `/ai-gateway/{gateway_id}/requests`, `/ai-gateway/analytics`) returned `404` for the Notifly account. Use the public status page as the primary signal; treat missing gateway analytics as "unavailable, no evidence of outage" rather than confirmation of health.

## Interpretation

- Public status page shows Workers AI `operational` + no incidents in the alarm window → no evidence of CF-side outage.
- Status page shows `degraded_performance`, `partial_outage`, or an active incident matching the window → cite the incident name/impact and treat it as a strong external-cause signal.
- If CF is green but the AI worker logs show 429/rate-limit errors → the limit is account-level or plan-level, not a global CF outage. Distinguish "provider down" from "our quota exceeded."

## Pitfalls

- Do not conflate "Cloudflare operational" with "our AI Gateway quota not exhausted." The status page covers global CF health, not per-account billing/rate limits.
- Do not block the alert response on CF API calls if the public status page already gives a clear answer. Run the status check in parallel with AWS helper output when possible.
