# Athena campaign/project mapping — bounded polling budget

## Symptom

When falling back to Athena `notifly_analytics.notifly_campaign_events` to map a
`campaign_id` (e.g. `WJ3ovG`) to its owning `project_id` because the sharded
Postgres `campaigns_<project_id>` lookup is impractical (1,500+ tables), a query
scoped only by `dt = '<day>'` and `campaign_id = '<id>'` can run 60-90+ seconds
without a `SUCCEEDED` state, because Athena still scans the full day partition
before filtering.

## Fix — bounded polling, then give up cleanly

1. Cap total polling time. Use at most 5 polls at ~10s intervals (~50s total)
   before abandoning the Athena lookup for that response.
2. Narrow the query maximally before submitting: filter on the tightest
   possible `dt` value (single day, not a range) and add any other available
   predicate (e.g. `event_name = 'campaign_published'`) to reduce scan cost —
   don't rely on `campaign_id` alone to prune.
3. If the query has not reached `SUCCEEDED`/`FAILED` after the bounded budget,
   do **not** block the Slack final answer on it. State plainly in the answer
   that project attribution for that campaign is "확인 불가 (Athena 조회 시간
   초과)" and finalize with the rest of the evidence chain. A slow lookup is
   not a reason to delay or skip the mandatory 5-field response.
4. Do not retry the same unbounded query shape a second time in the same
   session — if it didn't finish in the budget once, it won't reliably finish
   in a Slack-response time window. Prefer Postgres-side narrowing (if a
   candidate `project_id` is already suspected from other evidence, check that
   one shard directly) over re-running the full Athena scan.

## Related

- `references/kinesis-record-dispatcher-queue-throughput.md` — the alarm class
  this fallback is most commonly used for (segment-publisher batch bursts).
- Do not use a bare campaign/project ID as a `filter-log-events` pattern on
  `segment-publisher` logs — see the credential-dump pitfall already documented
  in `references/kinesis-record-dispatcher-queue-throughput.md` § "Pitfall —
  never filter-log-events... on segment-publisher logs". The same caution
  applies when tempted to grep ECS logs instead of using Athena/DynamoDB.
