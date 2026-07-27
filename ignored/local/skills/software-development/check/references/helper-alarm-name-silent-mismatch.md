# Helper can silently return data for the wrong alarm

## Symptom

Running the helper with an explicit `--alarm-name` can return a fully
populated, confident-looking bundle (`can_answer_root_cause: true`, complete
`alarm`, `history`, `logs` sections) — but the `alarm.name` field in that
output does not match the alarm name you requested. There is no error, no
warning, and no `missing_required_context` flag raised for this condition.

## Concrete case (2026-07-08)

Requested:
```bash
python collect_notifly_alert_context.py \
  --text '🚨 CloudWatch Alarm | /aws/ecs/notifly-services-prod/web-console console error | ap-northeast-2' \
  --alarm-name '/aws/ecs/notifly-services-prod/web-console console error' \
  --region ap-northeast-2
```

Returned `alarm.name: "user-journey-node-runner lambda error"` — a
completely unrelated Lambda alarm in a rapid-recurrence state, with its own
full history and evaluated datapoints. Nothing in the JSON flagged the
mismatch. If the `alarm.name` field had not been manually compared against
the requested name, the investigation would have produced root cause and
scope for the wrong alarm entirely.

The actual `/aws/ecs/notifly-services-prod/web-console console error` alarm
had already recovered to `OK` and required a completely separate manual
trace (`describe-alarms` with the exact name, `describe-alarm-history`, then
`get-log-events` on the active log streams for the breach window) to recover
the real root cause: a `JSON.parse("[object Object]")` double-parse bug in
`services/server/web-console/src/pages/api/kakao/alimtalk/templates.ts`.

## Root cause (suspected)

Likely a leftover/stale detection result or CLI arg-parsing collision inside
the helper's text detector — when both `--text` and `--alarm-name` are
passed and the free-text alarm name detector also finds a plausible (but
different) alarm-name-shaped token elsewhere in the pasted text, the
detector's result may win over the explicit `--alarm-name` flag. Not yet
root-caused inside the helper package itself; flagging behaviorally for now.

## Mandatory workaround

Treat every helper JSON result as **provisional** until you check
`alarm.name` against the alarm name you intended to query:

1. After running the helper, read `alarm.name` from the output.
2. Compare it character-for-character against your intended alarm name.
3. If they differ (or `alarm.name` is null while you expected a match),
   discard the `alarm`, `history`, `metric`, and `logs` sections and verify
   directly:
   ```bash
   aws cloudwatch describe-alarms --region ap-northeast-2 \
     --alarm-names '<exact alarm name>' --output json
   ```
   then pull `describe-alarm-history` and (if log-derived) `get-log-events`
   on the streams active during the breach window manually.
4. Do not trust `can_answer_root_cause: true` as proof the alarm resolved
   matches your request — that flag only reflects internal completeness of
   whatever alarm the helper actually resolved.

## Practical note on log-derived alarm log lookup when `filter-log-events` is empty

`filter-log-events` can legitimately return `[]` for a breach window even
when the triggering log line exists, due to Logs Insights ingestion lag (see
existing `ecs-log-manual-trace.md` and the CW-logs-timestamp pitfalls). The
reliable fallback is:

1. `describe-log-streams --order-by LastEventTime --descending` to find the
   streams active in the breach window (`firstEventTimestamp` /
   `lastEventTimestamp` straddle the window).
2. `get-log-events` on each active stream with `--start-time`/`--end-time`
   bounding the window (both in epoch **milliseconds**).
3. Scan the returned `events[].message` for `error`/`exception`
   case-insensitively rather than relying on a `filter-log-events`
   `--filter-pattern`, since multi-line stack traces often log each frame as
   a separate event and simple filter patterns can miss the first line.

This is how the `web-console console error` root cause (`JSON.parse` bug)
was actually recovered in the 2026-07-08 session after the helper mismatch
above made its own log-derived evidence unusable.
