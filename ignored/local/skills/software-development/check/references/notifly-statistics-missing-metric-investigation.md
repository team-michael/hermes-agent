# Notifly 통계/지표 "안 보임" 조사 (campaign & user journey)

Use when a CS/Slack complaint is **not** a CloudWatch alarm but a data-quality
question: "캠페인/유저여정에서 X 지표가 안 보인다", "팝업 노출만 보이고 클릭/전환이 없다",
"통계가 안 맞는다". Inputs are usually `projectId` (+ `campaignId` or `userJourneyId`).

This reuses the `check` skill's live data plumbing (Postgres/DynamoDB/Athena creds,
sharded table naming) but the investigation shape is different from alarm triage.

## The 3-layer rule (always separate these before answering)

A metric "not showing" can fail at exactly one of three layers. Diagnose in order,
never conflate:

1. **RAW** — did the client/server event even fire?
   Table: `message_events_<project_id>` (client-side + server-side rows).
   Filter by `event_params->>'user_journey_id'` / `campaign_id` / `event_params->>'campaign_id'`.
   Group by `event_name, channel`. If the event isn't here, nothing downstream can show it.

2. **AGGREGATED** — did the hourly Glue job roll it up?
   Tables: `campaign_statistics_<pid>` (campaigns) / `user_journey_statistics_<pid>` (journeys).
   Cols: `metric_type` (`standard`|`conversion`), `metric_name`, `value`, `collected_from/to`
   (time buckets `YYYY-MM-DD_HH`). The newest 1 hour is normally *not* yet aggregated,
   so RAW=10 / AGG=9 is expected lag, NOT a bug. `lastCollectedAt` null ⇒ fallback mode.

3. **DISPLAY** — does the web-console render this metric_name for THIS surface?
   Campaign stats and User-Journey node stats use DIFFERENT whitelists. A metric can be
   in RAW+AGG yet dropped by the UI because the surface's categorizer omits it.
   - Label map (both surfaces resolve names through this):
     `web-console/src/models/campaignStatistics.ts` `METRIC_LABELS` +
     `web-console/src/utils/campaign_stats_utils.ts` `getMetricLabel` / `isMetricToDisplay`.
   - UJ node surface categorizer (the one with the narrower whitelist):
     `web-console/src/domains/user-journey/components/UserJourneyBuilder/nodes/MessageNode/MessageStatsSheet.tsx`
     `categorizeMetrics` — engagement bucket is an explicit `.includes([...])` array.
     Anything not in a bucket is silently dropped (no fallthrough render).

## In-app / in-web popup metric taxonomy (what CAN exist)

Emitted only when the popup template actually has the corresponding action:
- `in_app_message_show` / `in_web_message_show` — always (앱/웹 팝업 노출)
- `main_button_click` (팝업 메인버튼 클릭) — only if template has a URL/deeplink action button
- `link_open` (링크 오픈) — only if a tracking link is present
- `close_button_click` (팝업 닫기 버튼 클릭) — emitted on close
- `hide_in_app_message_button_click` (다시 보지 않기) — emitted on hide-for-days
- conversion (total/direct/sales) — only if the campaign/journey has `conversion_events` set

### Popup template action wiring (why "노출만" is often correct behaviour)
The rendered popup HTML (`cdn.notifly.tech/popup-templates/<pid>/<id>.app.html`) encodes
actions as `data-action-type="close|url|deeplink|hide"`. If the "주요 액션" button AND the
overlay are BOTH `data-action-type="close"` (the default starter template), there is no
URL/deeplink CTA — so `main_button_click`/`link_open` are physically impossible and only
show/close events occur. This is a config limitation, not a pipeline bug. `grep` the
template for `data-action-type=` + `main_button` to confirm.

## Known DISPLAY-layer bug (open as its own PR when it bites)
`MessageStatsSheet.tsx` `categorizeMetrics` engagement whitelist (in-app-message node)
historically OMITS `close_button_click` and `hide_in_app_message_button_click`, even though
the campaign-stats screen renders them via `METRIC_LABELS`. Result: UJ popup nodes show
"노출만" while the raw+aggregated close-click data exists. Fix = add those two names to the
engagement `.includes([...])` array. Cross-surface asymmetry is the tell — verify by
confirming the campaign screen DOES show the metric while the UJ node screen does not.

## Journey definition tables (for scoping the node)
- `user_journeys_<pid>` — cols incl. `conversion_events` (jsonb, `[]` ⇒ no conversion ever),
  `conversion_window_days`, `in_app_message_nodes`, `status`, `start_node_id`.
  NB: there is no `title`/`nodes` column — journey name is `name`; nodes live in a separate table.
- `user_journey_nodes_<pid>` — one row per node: `id, user_journey_id, type, details(jsonb)`.
  `details.message.html_url` is the popup template URL; `channel` = `in-app-message` etc.

## Verification queries (read-only)
```sql
-- RAW events for a journey (last N days)
SELECT event_name, channel, COUNT(*) cnt, MIN(created_at), MAX(created_at)
FROM message_events_<pid>
WHERE created_at >= now() - interval '3 days'
  AND event_params->>'user_journey_id' = '<UJID>'
GROUP BY event_name, channel ORDER BY cnt DESC;

-- AGGREGATED metrics for the journey
SELECT user_journey_node_id, metric_type, metric_name, SUM(value) total,
       MIN(collected_from), MAX(collected_to)
FROM user_journey_statistics_<pid>
WHERE user_journey_id = '<UJID>'
GROUP BY 1,2,3 ORDER BY 1,2,3;
```

## psql invocation pitfall (env-var, not literal)
Postgres creds are in env (`POSTGRES_HOST/PORT/DB/USER/PASSWORD`). In `terminal`, ALWAYS
reference the env var — `PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" ...`.
Do NOT type the password as a literal; the tooling masks pasted secret-shaped literals to
`***`, which then reaches psql verbatim and fails with `FATAL: password ... is wrong`.
Prefer `psql -f file.sql` with `\echo === section ===` separators over long `-c` one-liners
(avoids shell quoting EOF errors on multi-statement SQL). Write the .sql via write_file.

## Scope note
DynamoDB `project`/`GetItem` may be AccessDenied for the EC2 role (`EC2CloudWatchAgentRole`).
When project→product mapping is denied, proceed with Postgres shard-table existence as the
scope signal (`pg_tables LIKE '%<pid>%'`) and state the mapping gap in the final answer.
