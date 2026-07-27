# Notifly `rendering_failure` telemetry checks

Use this when investigating whether scheduled-message rendering failures occurred, especially for `segment-publisher` paths.

## Key distinction

`rendering_failure` is usually not a CloudWatch application log line.

In `services/task/segment-publisher/lib/kinesis.ts`, successful rendering-failure recording goes through:

- `putRenderingFailureLogsForAnalytics(...)`
- `convertToMessageEvent(...)`
- Kinesis `StreamName.MESSAGE_EVENTS`
- Firehose / Athena table `notifly_analytics.notifly_message_events`

CloudWatch only sees errors around the logging path, e.g. `Error while putting rendering failure logs...`, not the successful `rendering_failure` events themselves.

So if CloudWatch Logs Insights returns no `rendering_failure` matches, that does **not** prove there were no rendering failures. It only means the ECS task did not log that string.

## Code evidence to check

- `services/task/segment-publisher/lib/kinesis.ts`
  - `putRenderingFailureLogsForAnalytics()` emits `eventName: 'rendering_failure'`.
- Channel handlers such as:
  - `services/task/segment-publisher/lib/message/push_notification.ts`
  - `services/task/segment-publisher/lib/message/kakao_friendtalk.ts`
  - legacy / pre-refactor `services/task/segment-publisher/lib/message/kakao_alimtalk.ts`
  call `putRenderingFailureLogsForAnalytics()` after accumulating failed recipients.

## Investigation workflow

1. **Check CloudWatch for logging-path failures, not for the event itself**

   Query `/aws/ecs/notifly-services-prod/segment-publisher` for strings like:

   - `Error while putting rendering failure`
   - `rendering_failure`
   - `rendering`

   Interpret empty results narrowly: no app log evidence, not no analytics events.

2. **Query Athena `notifly_message_events` for the real events**

   Prefer partition-pruned daily queries. A broad 30-day grouped scan can run too long.

   ```sql
   SELECT project_id, campaign_id, count(*) AS cnt
   FROM notifly_message_events
   WHERE dt = '<YYYY-MM-DD>'
     AND name = 'rendering_failure'
     AND resource_type = 'campaign'
   GROUP BY project_id, campaign_id
   ORDER BY cnt DESC
   LIMIT 50;
   ```

   For a single known campaign:

   ```sql
   SELECT dt, count(*) AS cnt
   FROM notifly_message_events
   WHERE dt >= '<YYYY-MM-DD>'
     AND project_id = '<project_id>'
     AND campaign_id = '<campaign_id>'
     AND name = 'rendering_failure'
     AND resource_type = 'campaign'
   GROUP BY dt
   ORDER BY dt DESC;
   ```

3. **Map candidate campaigns back to channel**

   `notifly_message_events` has `project_id` and `campaign_id` but not necessarily channel. Join mentally or query Postgres:

   ```sql
   SELECT id, channel, type, timing_type, status, contains_liquid_template, name
   FROM "campaigns_<project_id>"
   WHERE id IN ('<campaign_id_1>', '<campaign_id_2>');
   ```

   This matters because seeing `rendering_failure` events globally does not prove the target channel (e.g. Kakao Alimtalk) had them. In one investigation, recent `rendering_failure` events existed, but the campaigns mapped to `push-notification`, not `kakao-alimtalk`.

## Reporting guidance

Be precise:

- Bad: “No rendering_failure logs exist.”
- Better: “CloudWatch segment-publisher logs did not contain rendering_failure strings, but that path emits successful failures to Kinesis/Athena, not CloudWatch.”
- Best: “Athena has rendering_failure events for the checked window; after mapping campaign IDs to PG, the observed events are channel X. I do / do not see evidence for Kakao Alimtalk specifically.”

When using this evidence to justify a refactor decision, phrase it as “no recent telemetry evidence for preserving partial-skip rendering_failure behavior on this channel,” not “rendering_failure never happens.”
