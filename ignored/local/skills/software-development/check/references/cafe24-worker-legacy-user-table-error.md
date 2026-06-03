# cafe24-worker "relation does not exist" ConsoleErrors false positive

## Symptom

CloudWatch alarm `cafe24-worker lambda error` (ConsoleErrors namespace, metric filter `%ERROR|Status: timeout%`) fires with a log line like:

```
ERROR  Failed to delete <mallId> from notifly, error: error: relation "user_<project_id>" does not exist
Query: DELETE FROM device_<project_id> WHERE notifly_user_id IN (
    SELECT notifly_user_id FROM user_<project_id> WHERE source = 'cafe24'
)
```

## Why it is a false positive

- Lambda runtime `Errors = 0`, `Throttles = 0`.
- The failure is caught in `deleteMall` (`lib/jobs/delete.js`) inside a `try...catch` block, logged with `console.error`, and the Lambda returns normally.
- The `%ERROR%` metric filter catches the literal string `ERROR` in the logged message, not an invocation failure.

## Root cause

`lib/db.js` `deleteCafe24Users` executes two DELETE queries in parallel:

1. User deletion: uses `@notifly/userdb`'s `executeWriteQueryToUserTable`, which rewrites `user_${projectId}` → `users_${projectId}` (dual-write to the encrypted table).
2. Device deletion: uses `@notifly/common`'s `db.executeQuery` directly, bypassing the dual-write layer.

The device-deletion query contains a subquery referencing `user_${projectId}`:
```sql
DELETE FROM device_<project_id> WHERE notifly_user_id IN (
    SELECT notifly_user_id FROM user_<project_id> WHERE source = 'cafe24'
)
```

Since this raw query bypasses `@notifly/userdb`, the actual table name sent to Postgres is `user_${projectId}` instead of `users_${projectId}`.

Projects created **after** the encryption migration (`users_` table introduction) do not have the legacy `user_${projectId}` table. Therefore the subquery fails with `42P01` (`relation does not exist`).

## Scope

Extract `project_id` from the table suffix in the ERROR log line. Map via DynamoDB `project` table.
Projects with `notifly-` prefix are internal test/demo projects and should be flagged as internal/not customer-facing.

## Classification

- `no_action` for sporadic isolated occurrences.
- `needs_fix` if recurrence is frequent, because the code bug should be fixed (route device cleanup through `@notifly/userdb` or use `users_${projectId}` explicitly).

## Fix target

File: `services/lambda/cafe24-worker/lib/db.js`
Function: `deleteCafe24Users`
Change the device-deletion query to reference `users_${projectId}` or route it through `executeWriteQueryToUserTable` so the dual-write transformation applies.
