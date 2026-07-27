# RDS VolumeReadIOPs scope recovery via user-journey aggregate

Use this when a `High VolumeReadIOPs` alert is clearly a benign Aurora batch-workload spike, but the helper still leaves the final scope field incomplete because it cannot name a single campaign or user journey from Performance Insights alone.

## When it applies

- Alarm shape: `AWS/RDS` → `VolumeReadIOPs`
- Cluster: `notifly-db-prod-cluster`
- PI shows the current focus window dominated by a project-specific sharded table family, especially `user_journey_sessions_<project_id>`
- The helper already identifies the dominant project(s), but `campaign_scope_hints` cannot narrow to a single campaign

## Read-only recovery pattern

1. Take the dominant `project_id` from PI focus load.
2. Run a narrow aggregate against the campaign-capable table family around the alarm window.
3. Prefer `user_journey_sessions_<project_id>` when the dominant SQL family is session-count lookups.
4. Use `user_journey_id` as the final scope when the table family has no campaign column.
5. If the top contributor is ambiguous across several journeys, keep the alarm scope as infra-wide rather than inventing a campaign.

## Example outcome from this session

- Dominant project: `stepup` (`32d8d9d6294d52e7a5427c036b471f91`)
- Top user journey in `user_journey_sessions_32d8d9d6294d52e7a5427c036b471f91`: `UL1T00`
- `campaign_id` was not present in the table family used for the scope recovery query
- Final classification stayed `no_action` because the alert remained a recurring batch-workload spike

## Suggested aggregate shape

```sql
SELECT user_journey_id, count(*)
FROM user_journey_sessions_<project_id>
GROUP BY user_journey_id
ORDER BY count(*) DESC
LIMIT 10;
```

**Pitfall — `current_node_update_time` is epoch-millisecond `bigint`, not a timestamp column**: `user_journey_sessions_<project_id>` has no native `timestamp` column for session activity; the only time-bounding column is `current_node_update_time`, stored as epoch milliseconds. A `WHERE current_node_update_time BETWEEN '2026-07-02 11:43:00' AND ...` fails with `invalid input syntax for type bigint`. Convert alarm-window bounds to epoch-ms first:

```bash
START_MS=$(date -d '2026-07-02 11:43:00 UTC' +%s%3N)
END_MS=$(date -d '2026-07-02 12:15:00 UTC' +%s%3N)
psql ... -c "SELECT user_journey_id, count(*) FROM user_journey_sessions_<project_id> WHERE current_node_update_time BETWEEN $START_MS AND $END_MS GROUP BY user_journey_id ORDER BY count(*) DESC LIMIT 10;"
```

Full column set for `user_journey_sessions_<project_id>`: `id`, `notifly_user_id`, `user_journey_id`, `current_node_id`, `current_node_update_time`, `exit_time`, `exit_type`, `created_at`, `updated_at`, `user_journey_session_params`.

**Resolving the human-readable journey name**: once a dominant `user_journey_id` is found, look it up in `user_journeys_<project_id>` (not the sessions table) to get the name and status for the final answer:

```sql
SELECT id, name, status FROM user_journeys_<project_id> WHERE id = '<user_journey_id>';
```

**`psql` invocation pitfall — `PGPASSWORD` is not auto-populated from `POSTGRES_PASSWORD`**: sourcing the `.env` file only exports `POSTGRES_*` vars; `psql`/`PGPASSWORD` needs an explicit assignment in the same shell before connecting:

```bash
source /home/ubuntu/.hermes/profiles/hashimoto/.env
export PGPASSWORD="$POSTGRES_PASSWORD"
psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -F'|' -c "..."
```

Never paste a literal `***` placeholder or truncate the variable name (e.g. `$POS...`) into the command — write the full real `$POSTGRES_PASSWORD` variable reference so the shell expands it. A truncated/placeholder variable produces either a bash "unexpected EOF" parse error or a wrong-password auth failure, both of which look like credential problems but are actually copy-paste mistakes.

## Notes

- This is a scope-recovery aid, not a root-cause change.
- Keep the final user-facing alert response honest: if the current alarm can only support a user journey, print one user journey and do not also add a campaign.
- If the alarm is already infra-wide by design and the table family cannot identify a single journey with confidence, leave the scope as infra-wide.
