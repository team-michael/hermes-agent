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

## Notes

- This is a scope-recovery aid, not a root-cause change.
- Keep the final user-facing alert response honest: if the current alarm can only support a user journey, print one user journey and do not also add a campaign.
- If the alarm is already infra-wide by design and the table family cannot identify a single journey with confidence, leave the scope as infra-wide.
