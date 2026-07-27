# Web-Console `08P01` Audit-Log Batch Error

Triage reference for CloudWatch `console error` alarms where the current
trigger log contains PostgreSQL error `08P01` with detail
`bind message has N parameter formats but 0 parameters`.

## Root cause

The `@AuditLog` decorator (`services/server/web-console/src/decorators/AuditLog.ts`)
batches audit logs into a single knex `.insert()` call. When a bulk operation
(e.g. `DELETE /api/users`) produces ~985+ audit rows (~3,940 bind params),
`pg-protocol` serialises the prepared-statement bind message incorrectly and
PostgreSQL rejects it with `08P01`.

This happens **below** the PostgreSQL parameter-limit ceiling (32,767); the
actual failure is a protocol-level message-formatting bug in very long
multi-row `VALUES` clauses.

Consequence: the bulk DELETE/UPDATE succeeds but the audit-log insert fails
silently (the decorator catches the error and continues), so the operation is
unaudited.

## Frequently paired signature

The same alarm window often also contains:

```
Invalid notifly user IDs
```

from `UserRepository.ts` (`removeUsersByNotiflyUserId`, `removeUsers`).
The client sends malformed user IDs to `DELETE /api/users`, which triggers a
cascade of per-row audit-log entries and exposes the batch-insert bug.

## Scope extraction

- `project_id` → from the `DELETE /api/users` access-log line or `@AuditLog`
  payload.
- The affected project is whatever bulk-delete target the console user selected.
- Not infra-wide.

## Classification
- **Severity**: real bug causing silent audit-log loss.
- **Status directive**: `needs_fix` (both the protocol bug and the route
  validation gap).

## Fix

**Short-term** – chunk the audit-log insert in `models/auditLog.ts`:

```ts
import chunk from 'lodash/chunk';
const AUDIT_LOG_BATCH_SIZE = 500; // 4 cols × 500 = 2,000 params, safe margin

export async function createAuditLogs(projectId: string, auditLogs: AuditLog[]): Promise<void> {
  if (auditLogs.length === 0) return;
  const batches = chunk(auditLogs, AUDIT_LOG_BATCH_SIZE);
  await Promise.all(batches.map(batch => AUDIT_LOGS(projectId).insert(batch)));
}
```

`lodash` is already a dependency of `web-console`; `chunk` is used elsewhere
in the service (`excludedUsers.ts`, `pages/api/excluded_users/index.ts`).

**Medium-term** – add request-body validation to `DELETE /api/users` so that
malformed `notiflyUserId` lists are rejected before the repository layer
(and before `@AuditLog` creates hundreds of rows).

## Related references
- `services/server/web-console/src/decorators/AuditLog.ts`
- `services/server/web-console/src/models/auditLog.ts`
- `services/server/web-console/src/repositories/UserRepository.ts`
- `services/server/web-console/src/pages/api/users/index.ts` (DELETE handler)
