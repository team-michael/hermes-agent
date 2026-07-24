# web-console PostgreSQL audit-log batch 08P01 error

## Pattern

CloudWatch alarm `/aws/ecs/notifly-services-prod/web-console console error` fires with log signatures matching `%ERROR|Exception%`.
When the current trigger contains:

```
Failed to insert audit logs: error: insert into "audit_logs_<project_id>" as "audit_logs" ("action", "created_by", "resource_id", "resource_type") values ($1, $2, $3, $4), ($5, $6, $7, $8) ...
bind message has <N> parameter formats but 0 parameters
```

with `code: '08P01'` (`protocol_violation`), this is a **real service-side bug** triggered by a bulk audit-log write that exceeds PostgreSQL protocol limits.

## Root cause

The `@AuditLog` decorator (`services/server/web-console/src/decorators/AuditLog.ts:276-279`) wraps methods in a `finally` block that calls `createAuditLogs(projectId, logs)` at `src/models/auditLog.ts:103-105`. When the decorated method processes a large number of items (e.g. `UserRepository.deleteUsers` with ~985 user IDs), the generated audit-log array contains one row per item. With 4 bind parameters per row, a ~985-row batch produces ~3,940 parameters, exceeding PostgreSQL's bind parameter/protocol limits. The `node-postgres` driver then emits `08P01` with the cryptic message `bind message has N parameter formats but 0 parameters`.

The error is logged at `console.warn('Failed to insert audit logs:', error)` inside the decorator's catch block. Because the message contains the literal string `ERROR` (in the `severity: 'ERROR'` field from `node-postgres` error output), the broad `%ERROR|Exception%` metric filter matches it and triggers the alarm.

## Code path

```
UserRepository.deleteUsers (or any method with @AuditLog decorator)
  → finally block
    → AuditLog decorator: createAuditLogs(projectId, logs)
      → pg.rw(`audit_logs_${projectId}`).insert(auditLogs)  // knex raw insert
        → PostgreSQL: 08P01 protocol_violation
```

Files involved:
- `services/server/web-console/src/decorators/AuditLog.ts` (lines 276–280)
- `services/server/web-console/src/models/auditLog.ts` (lines 103–105)

## Triage guidance

- **Scope**: Project ID is embedded directly in the error message as the `audit_logs_<project_id>` table name.
- **Impact**: Audit log records are lost for the affected operation. The primary business operation (`deleteUsers`, etc.) has already completed because the decorator runs in `finally`.
- **Frequency**: Previously rare; tends to spike when a single console operation touches hundreds of users at once.
- **Immediate action**: `needs_fix` — this is a real data-loss path (audit logs dropped silently). The fix should be a code change, not a threshold adjustment.
- **Long-term fix**: Chunk large audit-log arrays into smaller batches (e.g. 100 rows / 400 parameters per insert) inside `createAuditLogs` or the decorator.

## Distinguishing from handled Kakao/provider rejections

This `08P01` signature is a **service bug**, not a handled external-provider rejection. Do not classify it as `no_action` alongside the Kakao BizMessage or Sentry pipeline patterns. The presence of:
- `Failed to insert audit logs`
- `audit_logs_<project_id>` table name
- `code: '08P01'`
- `bind message has ... parameter formats`

are collectively definitive for this pattern.

## Companion error: `TypeError: e[0].map is not a function` → `Invalid notifly user IDs`

In the same alarm window, the `deleteUsers` endpoint may also throw:

```
TypeError: e[0].map is not a function
at e.args (.../chunks/4066.js:1:21753)
...
Error: Invalid notifly user IDs
at p.deleteUsers (.../chunks/36870.js:44:289)
```

This is a **separate frontend→API contract bug** where the `DELETE /api/users` request body is malformed (`e[0]` is not an array), causing `deleteUsers` to throw before (or during) the main work. The `@AuditLog` decorator still fires in `finally` with the malformed arguments, which may compound the audit-log parameter count issue.

**Classification**: Both signatures in the same window indicate:
1. A frontend bug sending malformed `userIds` to the delete endpoint.
2. The decorator audit-log mechanism amplifying any large operation into a DB protocol error.

Address both: fix the frontend contract validation and chunk the audit-log insert.

## Verification commands

Bounded manual trace to confirm the `08P01` pattern:

```bash
# Identify active web-console log streams around the alarm window
aws logs describe-log-streams \
  --log-group-name /aws/ecs/notifly-services-prod/web-console \
  --order-by LastEventTime --descending --limit 5 \
  --region ap-northeast-2

# Read the stream matching the alarm datapoint minute
aws logs get-log-events \
  --log-group-name /aws/ecs/notifly-services-prod/web-console \
  --log-stream-name prod/web-console/<STREAM_ID> \
  --start-time $(date -d '2026-06-09T10:32:00Z' +%s)000 \
  --end-time $(date -d '2026-06-09T10:35:00Z' +%s)000 \
  --limit 100 \
  --region ap-northeast-2
```

Also cross-check Logs Insights for `08P01` frequency:

```sql
fields @timestamp, @message
| filter @message like "08P01" or @message like "bind message has"
| stats count() by bin(1d)
```

## Remediation

1. **Immediate** (code fix): In `src/models/auditLog.ts`, chunk `createAuditLogs` inserts into batches of ≤100 rows (≤400 parameters), or use `knex.batchInsert` if available.
2. **Secondary** (frontend/API contract): In `src/repositories/UserRepository.ts:604-612`, add stronger input validation at the API route layer (`DELETE /api/users`) to reject non-array `userIds` before reaching the repository.
3. **Tertiary** (logging): The `console.warn` in the decorator could be changed to `console.error` with a slimmer message (row count only, not full query) to keep audit-log failures observable without matching the broad `%ERROR%` filter through the `node-postgres` error object's `severity: 'ERROR'` field.
