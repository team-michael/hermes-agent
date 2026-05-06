---
name: cloudwatch-alarm-noise-audit
description: Triage noisy CloudWatch alarms — trace metric filters back to source code log statements, classify severity, and recommend ERROR→WARN downgrades to reduce false-positive alert fatigue.
tags: [aws, cloudwatch, alarms, logging, noise-reduction, observability, incident-response]
trigger: User asks to audit CloudWatch alarm noise, reduce false-positive alerts, review console error alarms, or downgrade log severity from ERROR to WARN. Also when Amazon Q / AWS Chatbot alert channels are too noisy.
related_skills: [aws-sqs-dlq-investigation]
---

# CloudWatch Alarm Noise Audit

## When to Use

- Alert channel (Slack/Teams via Amazon Q or AWS Chatbot) is noisy with console error alarms
- User asks which ERROR logs can be downgraded to WARN
- Reviewing metric filter → alarm → log → code chain for optimization
- Reducing alert fatigue without losing visibility on real incidents

## Investigation Order

### Phase 1: Identify the Alarm Sources

List all alarms, filter for "console error" or custom error metric alarms:

```bash
aws cloudwatch describe-alarms --region ap-northeast-2 \
  --query 'MetricAlarms[*].{Name:AlarmName,Metric:MetricName,Namespace:Namespace,State:StateValue}' \
  --output table
```

Check alarm history for firing frequency (last 30 days):

```bash
aws cloudwatch describe-alarm-history \
  --alarm-name "<alarm-name>" \
  --history-item-type StateUpdate \
  --start-date $(date -d '30 days ago' -Iseconds) \
  --region ap-northeast-2 \
  --query 'AlarmHistoryItems[?contains(HistoryData, `ALARM`)].{Time:Timestamp}'
```

### Phase 2: Trace Metric Filters

For each alarmed log group, find the metric filter that feeds the alarm:

```bash
aws logs describe-metric-filters \
  --log-group-name "<log-group>" \
  --region ap-northeast-2
```

Common filter patterns:
- `ERROR` (case-sensitive) — matches pino `"level":"error"` or any line containing ERROR
- `%[Ee][Rr][Rr][Oo][Rr]|Exception%` — case-insensitive error OR Exception
- Custom patterns like `took too long`

**Important**: Understand what the pattern actually matches. `ERROR` case-sensitive won't match `"level":"error"` from pino unless the output also includes a `severity: 'ERROR'` field (pino 10+ adds this for GCP/Cloud Logging compatibility).

### Phase 3: Query Actual Error Logs

Use CloudWatch Logs Insights for pattern analysis (much better than filter-log-events for aggregation):

```
filter @message like /(?i)error|exception/
| stats count(*) as cnt by @message
| sort cnt desc
| limit 30
```

For structured JSON logs, parse fields:

```
filter @message like /error-response/
| parse @message "\"message\":\"*\"" as errMsg
| parse @message "\"status\":*," as statusCode
| stats count(*) as cnt by errMsg, statusCode
| sort cnt desc
| limit 30
```

For specific timestamps around alarm firing:

```
fields @timestamp, @message
| filter @message like /ERROR|Exception/
| sort @timestamp desc
| limit 20
```

**Note**: Logs Insights queries are async. Start with `start-query`, wait 10-15s, then `get-query-results`. Check status field — may still be "Running".

### Phase 4: Cross-Reference Source Code

Search the codebase for each error pattern found:

```bash
# Find console.error calls (primary source of unstructured error logs)
grep -rn 'console\.error' --include='*.ts' --include='*.js' | \
  grep -v node_modules | grep -v dist

# Find structured logger error calls
grep -rn "logStructured('error'" --include='*.js' --include='*.ts'
grep -rn "logger\.error" --include='*.ts' --include='*.js'
```

### Phase 5: Classify and Recommend

For each error log pattern, evaluate:

| Question | If YES → | If NO → |
|----------|----------|---------|
| Does it indicate data loss risk? | Keep ERROR | Continue |
| Does it cause user-visible failure? | Keep ERROR | Continue |
| Does it mean a system is down? | Keep ERROR | Continue |
| Is it a client input validation failure? | → WARN | — |
| Is it an external service throttle/rate limit? | → WARN | — |
| Is it a transient network timeout to non-critical service? | → WARN | — |
| Is it informational diagnostic logging? | → WARN | — |
| Does the code already handle it gracefully (returns null, fallback, etc.)? | → WARN | — |

## Common Patterns That Should Be WARN, Not ERROR

1. **AWS Throttling** — `TooManyRequestsException` from Athena, DynamoDB, etc. These are operational backpressure, not code failures.
2. **Input validation** — Malformed user input, missing required fields, unsupported platforms. These are expected data quality issues.
3. **External service timeouts** — ETIMEDOUT to Sentry, analytics endpoints, etc. Non-critical path failures.
4. **Gracefully handled errors** — Code catches the error, returns null/fallback, and continues. The catch is working as designed.
5. **Diagnostic logging with fake-200** — When code intentionally swallows errors and returns success to the client, the log is for debugging, not alerting.
6. **Template rendering errors** — LiquidJS parse failures on user-authored templates. User content issue, not system failure.
7. **Cache not initialized** — Returns undefined as fallback. Equivalent to a cache miss.
8. **Next.js Sentry tunnel proxy failures** — `@sentry/nextjs` `tunnelRoute` config (e.g., `tunnelRoute: '/monitoring'` in `next.config.js`) creates a Next.js rewrite that proxies browser Sentry SDK envelope calls through the server to bypass ad-blockers. On ECS Fargate, the server→Sentry connection can intermittently ETIMEDOUT (IPv4) or ENETUNREACH (IPv6), producing `"Failed to proxy https://...ingest.sentry.io/.../envelope/..."` as `console.error`. This `console.error` is **hardcoded in Next.js** (`packages/next/src/server/lib/router-utils/proxy-request.ts`) with a 30s timeout — no configuration for timeout, retry, or error handling exists. `--dns-result-order=ipv4first` in NODE_OPTIONS only fixes DNS ordering; if IPv4 itself times out, the error persists. **Solution: Replace `tunnelRoute` with a custom API route + Sentry `tunnel` client option** — preserves same-origin proxying (ad-blocker bypass, no CORS) with full control:
   - Remove `tunnelRoute` from `withSentryConfig()` in `next.config.js`
   - Add `tunnel: '/api/monitoring'` to `Sentry.init()` in `sentry.client.config.js`
   - Create `src/pages/api/monitoring.ts` that parses envelope DSN, validates against allowlist, forwards with `fetch()` + `AbortSignal.timeout(5000)`, retries once (500ms backoff), logs failures as `console.warn`, returns 202 on failure
   - Derive host/project from a shared DSN constant (e.g., `sentry.shared.js`) — no hardcoding in the tunnel endpoint

## Pitfalls

- **`console.error` override trap**: Some services (e.g., segment-publisher in notifly-event) override `console.error` to prefix output with `[ERROR]`. If the metric filter matches `ERROR`, then even downgrading to `console.warn` in upstream packages won't help — the override turns ALL console.error into `[ERROR]`-prefixed console.log. Check for overrides before recommending changes.

- **Multiline log matching**: CloudWatch metric filters match per log event. A multiline stack trace may match `ERROR` on a different line than expected. The `severity: 'ERROR'` line from pino structured logging is a separate log event from the JSON payload.

- **pino severity field**: pino 10+ outputs a `severity` field alongside `level` for GCP Cloud Logging compatibility. `logger.error()` produces both `"level":"error"` and potentially `"severity":"ERROR"`. The uppercase `ERROR` in severity is what case-sensitive metric filters match.

- **client-side vs server-side**: In Next.js apps, `console.error` in React components runs in the browser — it won't hit CloudWatch. Only `pages/api/` and server-side code produces CloudWatch logs. Focus on server-side files.

- **Metric filter pattern syntax**: `%pattern%` is CloudWatch's wildcard syntax (like SQL LIKE). `%[Ee][Rr][Rr][Oo][Rr]%` is case-insensitive via character classes. Plain `ERROR` is exact substring match, case-sensitive.

## Phase 6: Implement the Fix — Error Type Hierarchy Over Hardcoded Checks

When downgrading errors in a shared middleware (e.g., Express/Next.js error handler), **do not hardcode domain-specific message strings** in the middleware. This creates tight coupling and scales poorly.

Instead, introduce an error type hierarchy:

```typescript
// src/errors/ExpectedError.ts
import { CustomError } from './CustomError'; // or your base error class

export class ExpectedError extends CustomError {
  constructor(message: string, statusCode: number = 400) {
    super(message, statusCode);
  }
}
```

Then in the middleware, classify by type alone:

```typescript
// middleware.ts — ONE line, zero domain knowledge
if (error instanceof ExpectedError) {
  console.warn(`[Expected] ${error.message}`);
  res.status(error.statusCode).json({ error: error.message });
} else {
  console.error(error);
  Sentry.captureException(error);
  res.status(500).json({ error: 'Internal server error' });
}
```

Each throw site decides its own classification:

```typescript
// CampaignService.ts
throw new ExpectedError('Campaign was updated by another user', 409);

// nhncloud.ts
throw new ExpectedError(response.data.header.resultMessage, 400);
```

**Why this works**:
- Middleware stays generic — no domain strings to maintain
- Adding a new expected error = changing one throw site, zero middleware changes
- Type check is robust across refactors (no string matching fragility)
- `instanceof` survives minification (unlike checking `error.constructor.name`)

**Pitfall**: Ensure `ExpectedError` import ordering satisfies project linters (prettier/eslint import-sort). Run `eslint --fix` after adding imports in multiple files.

## Output Format

Provide a table with:
1. **File path** and line numbers
2. **Current log pattern** (the console.error or logger.error call)
3. **What it logs** (error type/message)
4. **Recommended change** (ERROR→WARN or keep ERROR)
5. **Rationale** (why it's safe or unsafe to change)

Separately list items that should REMAIN at ERROR level with clear justification.

## Notifly-Specific Notes

- ConsoleErrors is the custom CloudWatch metric namespace for ECS service console error alarms
- api-service uses pino via `logStructured()` in `lib/utils/logger.js`; only `app.js:353` calls `logStructured('error',...)` for uncaught exceptions
- segment-publisher overrides `console.error` → `console.log('[ERROR]',...)` in `index.ts`
- segment-helper package has ~30 `console.error` calls that are all input validation — strong WARN candidates
- web-console metric filter uses case-insensitive pattern, catching AWS SDK error strings in stack traces
