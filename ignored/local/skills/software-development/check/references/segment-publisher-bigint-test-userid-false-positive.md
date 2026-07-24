# Segment-Publisher BigInt Test User ID False Positive

Session: 2026-05-20
Alarm: `/aws/ecs/notifly-services-prod/segment-publisher console error`
Metric filter: `ERROR` on `/aws/ecs/notifly-services-prod/segment-publisher`
Metric: `ConsoleErrors` / `segment-publisher-prod console error`

## Error signature

```
[ERROR] SyntaxError: Cannot convert 0xtest_80 to a BigInt
```

Stack trace:
```
at BigInt (<anonymous>)
at encode3 (/app/dist/index.js:67776:22)
at shortenNotiflyUserId3 (/app/dist/index.js:68293:36)
at prepareRenderParams (/app/dist/index.js:205256:69)
at _getRenderParams (/app/dist/index.js:208332:37)
at _buildWebhookMessage (/app/dist/index.js:208304:24)
at Array.map (<anonymous>)
at _buildSqsMessagePayload (/app/dist/index.js:208268:14)
```

Root cause: `shortenNotiflyUserId3` calls `encode3`, which passes a user ID string into `BigInt()`. When the user ID contains a non-numeric hex prefix such as `0xtest_80`, `0xtest_20`, `0xsdfsdf`, etc., `BigInt()` throws `SyntaxError`.

## Scope

- Project: `michael` (`a0d696d1aba7535fad6710cddf3b1cab`) — DynamoDB `project` table maps to product `michael`.
- Campaign/user journey: unknown (webhook message build path is service-common).
- Table refs visible in logs: `device_a0d696d1aba7535fad6710cddf3b1cab`, `users_a0d696d1aba7535fad6710cddf3b1cab`.

## Why it is a false positive

1. The failing IDs are clearly synthetic test data: `0xtest_80`, `0xtest_20`, `0xtest_1`, `0xtest_76`, `0xtest_47`, `0xtest_28`, `0xtest_26`, `0xsdfsdf`.
2. The `michael` project is Notifly's internal test/demo project.
3. The alarm fires only when a segment-publisher batch happens to include these test user records; normal production user IDs do not trigger this path.
4. The segment-publisher invocation continues after the ERROR log emission (the error is caught in `_buildSqsMessagePayload` map), so the batch itself does not fail.
5. Cross-check ConsoleErrors metric: the spike is a single 1-minute burst (e.g., Sum=201 at 09:09 UTC) followed by immediate recovery at 09:10 UTC.

## Frequency

- 30-day OK→ALARM transitions for this alarm: 2 total (as of 2026-05-20).
- Daily ERROR log count from `segment-publisher` is dominated by other patterns (e.g., `RenderError: message is aborted` for liquid template failures), not this BigInt signature.
- This specific BigInt error appears only sporadically (~2 hits per recent sample window).

## Triage

**Classification:** `no_action` (no immediate engineering work required).

Rationale:
- No real customer impact (test data only).
- Already recovered within 1 minute.
- 30-day recurrence is very low (2 transitions).

**Non-urgent improvement (not `needs_fix`):** consider sanitizing or filtering out synthetic test user IDs with non-numeric `0xtest_*` prefixes in `shortenNotiflyUserId3`, or pre-validating user IDs before passing to `BigInt()`. The fix target is `packages/*/dist/index.js` / `shortenNotiflyUserId3` in the segment-publisher build output. Because this fires on internal test data only, priority is low.

## Bounded manual trace commands

When the helper fails for this alarm (e.g., `detected.alarm_name: null` because of the trailing `console error` suffix):

1. Find alarm metadata:
   ```bash
   aws cloudwatch describe-alarms --region ap-northeast-2 \
     --query 'MetricAlarms[?contains(AlarmName, `segment-publisher`) && contains(AlarmName, `console`)].{Name:AlarmName,State:StateValue,Threshold:Threshold,Period:Period,EvaluationPeriods:EvaluationPeriods,MetricName:MetricName,Namespace:Namespace,StateReasonData:StateReasonData}' \
     --output json
   ```

2. Get metric datapoints around the breach:
   ```bash
   aws cloudwatch get-metric-statistics --region ap-northeast-2 \
     --namespace ConsoleErrors \
     --metric-name "segment-publisher-prod console error" \
     --start-time 'YYYY-MM-DDTHH:MM:SSZ' \
     --end-time 'YYYY-MM-DDTHH:MM:SSZ' \
     --period 60 --statistics Sum --output json
   ```

3. Get trigger context from CloudWatch Logs:
   ```bash
   aws logs filter-log-events --region ap-northeast-2 \
     --log-group-name /aws/ecs/notifly-services-prod/segment-publisher \
     --filter-pattern "ERROR" \
     --start-time $(date -d 'YYYY-MM-DD HH:MM:SS UTC' +%s)000 \
     --end-time $(date -d 'YYYY-MM-DD HH:MM:SS UTC' +%s)000 \
     --limit 100 \
     --output json | jq -r '.events[] | [.timestamp, .message] | @tsv'
   ```
