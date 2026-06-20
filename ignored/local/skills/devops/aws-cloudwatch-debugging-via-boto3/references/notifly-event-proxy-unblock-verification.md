# Notifly event-proxy unblock verification

Use this when a PR changes `services/server/event-proxy/task-definitions-*.json` blocklist/env config and the user asks whether project events are flowing again after merge/deploy.

## Evidence chain

1. **ECS deployed config**
   - Service: cluster `notifly-services-prod`, service `event-proxy`.
   - Confirm active task definition revision, deployment `rolloutState`, running/desired count.
   - Inspect active task definition container env:
     - `ENV=prod`
     - `BLOCKED_PROJECT_IDS=""` or the target project IDs absent from the value.

2. **Drop metric stopped**
   - Namespace: `ECS/Micrometer/event-proxy-prod`
   - Metric: `event_proxy.dropped.count`
   - Dimension: `projectId=<project_id>`
   - Query before/after rollout. Look for nonzero drops before rollout and zero drops after the new tasks are running.

3. **Downstream event-log evidence**
   - Athena DB/table: `notifly_analytics.notifly_event_logs`
   - Partitions: `project_id`, `dt`, `h`, `pre_conversion`
   - `time` is microseconds. Use partition predicates first, then `time >= <rollout_epoch_seconds>000000` for precise post-rollout cutoff.

Example query:

```sql
SELECT
  project_id,
  count(*) AS event_count,
  from_unixtime(CAST(min(time) AS double) / 1000000) AS first_event_utc,
  from_unixtime(CAST(max(time) AS double) / 1000000) AS last_event_utc,
  array_join(slice(array_agg(DISTINCT name), 1, 10), ', ') AS sample_event_names
FROM notifly_event_logs
WHERE project_id IN ('<project_id_1>', '<project_id_2>')
  AND dt = '<YYYY-MM-DD>'
  AND h = '<HH>'
  AND time >= <rollout_cutoff_epoch_seconds>000000
GROUP BY project_id
ORDER BY project_id;
```

## Interpretation

- Post-rollout rows in `notifly_event_logs` prove event-proxy -> Kinesis/Firehose/Athena flow for that project.
- Zero post-rollout rows plus zero drops is not a failure by itself; it may mean no observed input traffic for that project.
- Drops continuing after rollout usually means an old task definition is still running or the active env still contains the project ID.
- API 200 alone is insufficient because api-service can fake-200 around event-proxy failures; use CloudWatch drop metric + Athena rows.
