# web-console: Missing user_journey_session_statistics table (42P01)

## Trigger signature

CloudWatch Logs show:

```
code: '42P01',
error: select "metric_name", SUM(CASE WHEN collected_from >= $1 THEN value ELSE 0 END)::bigint AS in_range_value, SUM(value)::bigint AS cumulative_value from "user_journey_session_statistics_<project_id>" ...
routine: 'parserOpenTable'
```

## Root cause

The project has a `user_journeys_<project_id>` table (so it uses the user-journey feature) but is **missing the `user_journey_session_statistics_<project_id>` table**.
The `web-console` API (`UserJourneySessionStatisticsRepository.ts`) always queries that stats table by constructing the name dynamically with `getTableName(projectId)`, so when the shard is absent the query fails.

## Scope / project mapping

- Table suffix `<project_id>` is the project ID itself.
- Map via DynamoDB `project` table as usual.
- The current alarm logs typically do **not** contain an explicit `projectId` field because the error is thrown by `pg` client before any higher-level log wrapper. The project ID comes from parsing the table name in the log line.

## How to verify

Check whether the table exists in Postgres:

```sql
SELECT EXISTS (
  SELECT 1 FROM information_schema.tables
  WHERE table_schema = 'public'
    AND table_name = 'user_journey_session_statistics_<project_id>'
);
```

Count missing tables across all projects that have `user_journeys`:

```sql
WITH uj_projects AS (
  SELECT SUBSTRING(table_name FROM 'user_journeys_([a-f0-9]+)$') AS pid
  FROM information_schema.tables
  WHERE table_schema = 'public' AND table_name LIKE 'user_journeys_%'
),
ujss_projects AS (
  SELECT SUBSTRING(table_name FROM 'user_journey_session_statistics_([a-f0-9]+)$') AS pid
  FROM information_schema.tables
  WHERE table_schema = 'public' AND table_name LIKE 'user_journey_session_statistics_%'
)
SELECT uj.pid
FROM uj_projects uj
LEFT JOIN ujss_projects ujss ON uj.pid = ujss.pid
WHERE ujss.pid IS NULL AND uj.pid IS NOT NULL;
```

## Classification / alert status

- **Not a transient spike** — the error reproduces every time a user opens the user-journey statistics page for that project.
- When the project count is small (e.g. one or two projects), classify as `needs_fix` with the DDL migration target.
- When many projects are affected in one alarm window, the bug may be a broader migration/creation failure; escalate urgency accordingly.

## Code locations

- Query builder: `services/server/web-console/src/repositories/UserJourneySessionStatisticsRepository.ts:59-61` (`getTableName`)
- DDL definition: `services/server/web-console/queries/create_tables.sql:877-904`

## Action item

- Run the `create_tables.sql` DDL block for the affected `projectId`(s).
- Consider adding a defensive `CREATE TABLE IF NOT EXISTS ...` wrapper in a migration so new projects always get both the `user_journeys` and the `user_journey_session_statistics` tables atomically.
