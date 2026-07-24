# Ambient/vague load query with no pasted alarm text

## Trigger

The user makes a vague ambient observation with no pasted CloudWatch alarm
text, no alarm name, no Slack thread root, and no log snippet — e.g. "DB 부하
가 지금 꽤 있나보네요" ("DB load seems pretty high right now"). There is no
concrete alert artifact to anchor the investigation on. This differs from
every other recipe in this skill, which all assume the user handed you an
alarm name, alert text, or log line.

## Do not guess from conversational tone alone

A vague statement like this is not evidence. Do not assume it reflects a real
incident just because the user said it, and do not assume it's baseless just
because there's no alarm text either. Verify directly against live metrics
before answering.

## Recipe

1. `session_search` for recent alarm context in this thread/session in case
   the vague comment is a follow-up to something already investigated. Watch
   out for false-positive matches — FTS5 can match skill *documentation text*
   containing example alarm strings (e.g. `notifly-db-prod-cluster
   CPUUtilization too high` appears verbatim in this skill's own usage
   examples) rather than an actual delivered alert. If the "match" is just the
   skill body being quoted back, treat it as no real alert context found.
2. Pull currently active alarms: `aws cloudwatch describe-alarms --state-value
   ALARM`. Filter out the noisy baseline: `TargetTracking-*-AlarmLow-*` /
   `TargetTracking-*-AlarmHigh-*` entries are ECS/RDS autoscaling housekeeping
   alarms that sit in ALARM state for long stretches under normal load — they
   are not incidents by themselves. Only alarms with a **recent**
   `StateUpdatedTimestamp` and a metric that is not a scaling target are
   candidate real signals.
3. For the specific resource named in the vague comment (e.g. RDS cluster),
   pull live per-instance metrics directly — don't wait for an alarm to exist.
   For an Aurora cluster: `describe-db-clusters` to list writer/readers, then
   `get-metric-statistics` (`CPUUtilization`, 5-min period, last 2-3h) per
   instance.
4. Compare the current reading against a 7-day baseline (hourly `Maximum`,
   sorted descending, top 5) for the same instances. If current load is at or
   below the recent baseline ceiling, there is no elevation to explain — the
   vague comment does not correspond to an actual anomaly.
5. Cross-check the actual High/Low threshold alarm's history for real
   `OK -> ALARM` transitions in the lookback window (see the
   `describe-alarm-history` HistoryData-JSON extraction pipeline in the main
   SKILL.md). Zero transitions + current-below-baseline is strong evidence
   for `no_action`.
6. Answer with the standard five-field Korean shape. Make explicit in the
   `원인:` line that no alarm/alert artifact triggered this — the investigation
   was a direct live-metric check prompted by the user's observation, and state
   the actual current vs. baseline numbers.

## AWS CLI pitfalls hit during this flow

- `--query` field names from `get-metric-statistics` are case-sensitive:
  `Datapoints[].Maximum` / `.Average`, not `.max`/`.avg`. A lowercase field
  name silently returns an empty result (exit 0, no error) — easy to
  misread as "no data" when it's actually a query typo.
- `describe-alarm-history` does **not** support `--alarm-name-prefix` (only
  exact `--alarm-name`), while `describe-alarms` **does** support
  `--alarm-name-prefix`. Discover the exact alarm name via `describe-alarms
  --alarm-name-prefix '<partial>' --query 'MetricAlarms[].AlarmName'` first,
  then feed the exact name into `describe-alarm-history`.
