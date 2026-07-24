# `[api-service] 4xx error response is greater than 300 in 5m` — `/set-user-properties` 401 "Invalid Authorization Token" per-project pattern

## Signature

Current-alarm-window dominant signature (not `/authenticate` noise):

```json
{"level":"warn","service":"api-service","projectId":"<project_id>","status":401,"method":"POST","path":"/set-user-properties","normalizedPath":"/set-user-properties","duration":0-1,"ip":"<varies>"}
```

Paired `console.warn` line: `4xx response: <project_id> Invalid Authorization Token`.

## Code path

`services/server/api-service/lib/api/set-user-properties.js`:
- line ~93-98: no token -> 401 `"No token provided"`
- line ~101-108: `verifyToken(token)` returns falsy -> 401 `"Invalid Authorization Token"`

No DB/queue/downstream call happens before this check — `duration` in the log is 0-1ms, confirming the request fails at the auth gate, not deeper in the handler. A recent `git log` on `set-user-properties.js` / `lib/api/auth.js` with no matching commits rules out a service-side auth regression; the token itself is bad on the caller's side (expired/rotated/leaked/misconfigured integration).

## How to size the incident (don't over/under-escalate)

1. Pull `logs.current_top_signatures[].count_in_current_alarm_window` — if this single 401 signature dominates the sample (e.g. 297/300) and other known noise (`/authenticate`) is down to single digits, this is the real current trigger, not the historical baseline.
2. Compare the alarm's 4xx `value` against the alarm's own `sampleCount` (visible per-datapoint in `history.latest_alarm_transition.state_reason_data.evaluatedDatapoints` join with the raw CloudWatch metric datapoints) — `sampleCount` on a `ConsoleErrors` log-metric-filter alarm reflects total matched-log volume for that filter's log group in the period, not literal total traffic, but a low 4xx/sampleCount ratio (single-digit %) is still useful signal that the failure is concentrated in one caller/project, not systemic.
3. Check `history.daily_alarm_counts` for a *sustained* baseline shift (not just today's spike): a jump from ~6-8K/day historical baseline to 40K-220K/day starting on a specific date and persisting for a week, even while decaying, means the issue is not yet resolved — do not classify as recovered spike just because the day-over-day trend is falling.
4. Check whether the CloudWatch datapoints are still climbing at alarm time (`http` metric latest value vs prior values in the same call) — a still-rising curve (e.g. 256 -> 4,538 -> 11,383 -> 15,643 across consecutive 5-min buckets) means the incident is active, not resolved, even if you can't yet tell how it ends.

## Classification

- Single project, isolated 401s from a bad/expired token, low % of total service traffic, no other project affected, no code regression found: this is a customer-side integration problem, not a Notifly service bug.
- Still use `needs_fix` (not `no_action`) when the daily volume has been elevated 5x+ above baseline for multiple days and is still climbing at alarm time — the customer's broken retry loop is real ongoing waste/impact even though Notifly's own service is healthy.
- Escalate to `urgent` only if the 4xx volume is large enough relative to total `api-service` request volume to threaten capacity for other tenants (e.g. >20-30% of total sampled requests), or if multiple unrelated projects show the same pattern simultaneously (suggesting a shared auth dependency failure, e.g. Cognito/JWT issuer outage) rather than one customer's bad token.
- Action item should target the customer-facing side: ask the project owner to verify/rotate the API token, and consider adding per-project rate limiting or exponential-backoff enforcement server-side (`lib/api/auth.js` middleware) as the durable fix, since the client is clearly not backing off on repeated 401s.
