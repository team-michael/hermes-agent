# integration-service `console error` — PostgreSQL deadlock in Mixpanel cohort sync

## Signature
- Alarm: `/aws/ecs/notifly-services-prod/integration-service console error` (namespace `ConsoleErrors`, metric name
  `integration-service-prod console error`, `Threshold: 1.0`, `Period: 60`, dimensionless).
- Triggering lines (Kotlin/Exposed, Ktor):
  ```
  HH:MM:SS.mmm [eventLoopGroupProxy-N-N] WARN Exposed -- Transaction attempt #<n> failed: ERROR: deadlock detected
  org.postgresql.util.PSQLException: ERROR: deadlock detected
  Detail: Process <pid> waits for ShareLock on transaction <xid>; blocked by process <pid2>.
  Where: while locking tuple (<page>,<n>) in relation "users_<project_id>". Statement(s): null
  ```
- Preceding context lines usually show two concurrent `[Mixpanel] Received: action=remove_members` (or
  `add_members`) requests for **different cohortIds of the same project** within ~3 seconds of each other.

## Root cause
`MixpanelService.removeCohortFromUsers` / `assignCohortToUsers` →
`UserRepository.removeCohortFromUsers`/`addCohortToUsers`
(`services/server/integration-service/src/main/kotlin/tech/notifly/integration/repositories/UserRepository.kt`).

- `addCohortToUsers` chunks `userIds` by `CHUNK_SIZE = 5000` before each `transaction {}`.
- `removeCohortFromUsers` does **not** chunk — it runs a single `UPDATE users_<project_id> ... WHERE
  external_user_id = ANY(?::text[])` in one transaction regardless of list size.
- When two Mixpanel cohort-sync requests for the same project (different `cohortId`s) execute concurrently and their
  `userIds` sets overlap, PostgreSQL can grant row locks in opposite order across the two transactions → classic
  deadlock (`ERROR: deadlock detected`, no PG error code surfaced in the Kotlin log, but this is `40P01` from
  Postgres).
- **This is already self-healing**: Exposed's `transaction {}` has a default repetition/retry count (observed
  attempts `#0` then `#1` in the same window, both failing with deadlock, before eventually succeeding — Exposed's
  default max retry is higher than 2). The Mixpanel `[Mixpanel] Success: projectId=...` / HTTP 200 response follows
  normally; no data loss, no customer-visible error.

## Classification
- Daily signature volume over 30d is sporadic: single digits most days, occasional spikes (seen: 110/day on two
  separate days, 12/day on the alarm day). This is within an already-known recurring baseline, not a new pattern.
- `no_action` when: the alarm is isolated (1 ALARM transition), the deadlock retries and the request still completes
  (no error response propagated to the Mixpanel webhook caller), and daily signature count stays within the
  historical spread (single digits to low hundreds/day).
- Escalate to `needs_fix` only if: retries start failing (check for `[Mixpanel] Failed: action=...` ERROR log with
  the same cohortId/sessionId following the deadlock — that means the retry budget was exhausted and the caller got
  a 500), or the daily signature count trends up sharply beyond the historical spread.

## Non-urgent improvement (do not treat as required action)
`UserRepository.removeCohortFromUsers` could adopt the same `CHUNK_SIZE = 5000` chunking pattern already used by
`addCohortToUsers`, and/or both could sort `userIds`/`notifly_user_id` before building the `ANY(?::text[])` array so
concurrent transactions acquire row locks in a consistent order — this reduces deadlock *frequency* but is not
required because Exposed's automatic retry already makes individual occurrences self-healing.

## Scope attribution pitfall
The helper's `scope_attribution` aggregator can report `scope_kind: "unknown"` / `project_ids: []` even when
`logs.current_error_details[].table_refs[].project_id` already contains a valid project_id extracted from the
`relation "users_<project_id>"` deadlock detail line. This is the same class of aggregator gap documented for
`current_trigger_contexts[].project_ids` (see the "helper scope aggregator misses project_ids" pitfall in
SKILL.md) — it also applies to `table_refs` inside `current_error_details`. Always check
`current_error_details[].table_refs` for a `project_id` before declaring scope unknown, and map it via DynamoDB
`project` directly (`get_item` with `ProjectionExpression='id, product_id, #n'`, `ExpressionAttributeNames={'#n':'name'}`)
when `scope_attribution.projects` is `null`.
