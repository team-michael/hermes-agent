# api-service `console error` — PostgreSQL deadlock in `set-user-properties` upsert

## Signature
- Alarm: `/aws/ecs/notifly-services-prod/api-service console error` (namespace `ConsoleErrors`, filter pattern is the bare literal `ERROR`).
- Actual triggering lines (not JSON, raw pg error object dump across multiple log events):
  ```
  deadlock detected
  Query: INSERT INTO "users_<project_id>" (notifly_user_id, external_user_id, encrypted_email, encrypted_phone_number, encrypted_user_properties, random_bucket_number) VALUES ($1,$2,...), (...), ...
  Values: undefined
  Params: <redacted>
  Failed to upsert users:  error: deadlock detected
      at async setUserProperties (/app/services/server/api-service/lib/api/set-user-properties.js:176:18)
      ...
    length: 381,
    severity: 'ERROR',
    code: '40P01',
    detail: 'Process <pid> waits for ShareLock on transaction <xid>; blocked by process <pid2>.\n' +
      'Process <pid2> waits for ShareLock on transaction <xid2>; blocked by process <pid>.',
    hint: 'See server log for query details.',
  ```

## Pitfall — reconstructing raw (non-JSON) pg error object dumps from CloudWatch
A raw Node `console.error(pgError)` object dump is NOT one log line — each property (`length:`, `severity:`, `code:`,
`detail:`, `hint:`, the `Query:`/`Values:`/`Params:` lines, and the `at async ...` stack frames) is emitted as its
own separate CloudWatch log event. The helper's `current_error_details[].trigger` may show only a bare fragment like
`severity: 'ERROR',` with no surrounding context.

- A single `get_log_events` call with default `limit` will NOT reach the matching line inside a busy stream
  (e.g. `api-service` SSE/heartbeat traffic can produce 1,700+ events/minute — far more than one page).
- `filter_log_events` with `filterPattern='"ERROR"'` will find the one matching line but returns **zero** surrounding
  context lines — it only returns matching events, not their neighbors.
- **Fix**: paginate `get_log_events` with `nextForwardToken` across the full alarm-datapoint minute until the token
  stops advancing, collect everything into one ordered list, find the index of the fragment (`"ERROR" in message`),
  then slice ±10 to ±45 items by **list index**, not by timestamp (many lines share the same millisecond timestamp
  so timestamp-based windowing over-collapses or misses lines). This reconstructs the full error object plus the
  preceding `Query:`/stack-trace lines needed for root-causing.

## Root cause
`SetUserProperties.upsertUsersByExternalUserId` (`services/server/api-service/lib/db/Users.js`) builds a single multi-row
`INSERT INTO user_<project_id> (...) VALUES (...), (...), ... ON CONFLICT (notifly_user_id) DO UPDATE ...`.
When two concurrent SDK/API `/set-user-properties` requests for the same project touch overlapping `notifly_user_id`
rows in different input order, PostgreSQL can deadlock acquiring row locks (`40P01`).

**This is already handled**: `isRetryableUserUpsertError` treats `PgErrorCode.DEADLOCK_DETECTED` as retryable and
`upsertUsersByExternalUserId` retries the exact same query once on deadlock. In observed cases the retry succeeds and
the original HTTP request still returns `200` (check the `NotiflyExternalApi` EMF metric line for
`NormalizedPath: "/set-user-properties"` with `StatusCode: "200"` a few hundred ms after the deadlock log — request
duration reflects the extra roundtrip, e.g. ~3000ms).

## Classification
- Steady low-volume background pattern: roughly 1–7 occurrences/day across 30 days, no day-over-day worsening trend.
  Check with the Logs Insights query below before assuming this specific occurrence is novel.
- `no_action` when: daily count is within the historical 1–7/day band, and the same request's `/set-user-properties`
  EMF metric line shows `StatusCode: 200` shortly after (confirms the built-in retry worked).
- Escalate to `needs_fix` only if: daily count rises sharply above the ~7/day baseline, or the retry also fails
  (no matching `200` `/set-user-properties` metric line follows within a few seconds — check for a `500` response
  instead, which means `upsertError` survived the retry and was returned to the caller).

## Verification query (Logs Insights, 30d daily trend)
```
fields @timestamp, @message
| filter @message like /deadlock detected/
| stats count() as cnt by bin(1d)
```

## Non-urgent improvement (do not treat as required action)
Sorting the batch's `notifly_user_id` values before building the multi-row `VALUES` list (so all callers acquire
row locks in the same order) would reduce deadlock *frequency* further, but the current 1-retry behavior already
makes this self-healing. Do not raise `needs_fix` for this alone.
