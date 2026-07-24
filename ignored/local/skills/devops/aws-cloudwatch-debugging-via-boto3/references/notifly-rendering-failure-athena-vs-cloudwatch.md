# Notifly `rendering_failure`: CloudWatch vs Kinesis/Athena

Use this when asked whether Notifly `rendering_failure` logs exist, especially during segment-publisher or message-builder investigations.

## Core lesson

Successful `rendering_failure` events are usually not CloudWatch application logs. Segment publisher writes them via `putRenderingFailureLogsForAnalytics()` to Kinesis `MESSAGE_EVENTS`, then they appear in analytics/Athena tables. CloudWatch only shows producer runtime logs or the error path, e.g. `Error while putting rendering failure logs...`.

## Investigation workflow

1. Search CloudWatch for explicit runtime errors only:
   - `rendering_failure`
   - `rendering failure`
   - `Error while putting rendering failure`
   - Liquid/rendering exception strings if relevant

2. Query Athena `notifly_analytics.notifly_message_events`:
   - filter `name = 'rendering_failure'`
   - group by `dt`, `project_id`, `campaign_id`
   - if the question is about a channel, verify the campaign channel from PG (`campaigns_${project_id}`) before attributing it to Kakao/Push/etc.

3. State the result precisely:
   - Avoid: “there are no rendering_failure logs.”
   - Prefer: “CloudWatch had no rendering_failure application logs; Athena message events did/did not show rendering_failure for the checked window/channel.”

## Related Kakao Alimtalk pitfall

When evaluating whether Alimtalk common-builder can drop legacy `sender_platform: 'nhncloud'`, also check current data rather than only code:

- DDB `project.kakao_sender_info` key counts: non-empty `nhncloud` means live sender-info compatibility risk.
- PG `campaigns_*`: `channel='kakao-alimtalk'` and `channel_metadata->>'sender_platform'='nhncloud'`; active status (`1`) is the important risk, old inactive/terminated rows are usually historical residue.
- PG `user_journey_nodes_*`: search `details::text LIKE '%nhncloud%'`.

Keep the provider implementation distinction clear: removing legacy `sender_platform: 'nhncloud'` from builder/producer contracts is not the same as removing the NHN Cloud API client used internally by `platform: 'notifly'` Alimtalk delivery.
