# Bracket-prefixed alarm names work fine with the helper's `--alarm-name`

## Correction to the earlier documented pitfall

SKILL.md previously warned that alarm names starting with `[` (e.g.
`[api-service] 4xx error response is greater than 300 in 5m`) would fail when
passed to the helper's `--alarm-name` flag, because the raw AWS CLI
`--alarm-names` parameter interprets a leading `[` as the start of a JSON
array and throws `ParamValidation: Invalid JSON`.

**Confirmed 2026-07-03: this failure mode does not affect the helper.**

Ran:

```bash
python /home/ubuntu/.hermes/profiles/hashimoto/skills/software-development/check/scripts/collect_notifly_alert_context.py \
  --text '[api-service] 4xx error response is greater than 300 in 5m' \
  --alarm-name '[api-service] 4xx error response is greater than 300 in 5m' \
  --region ap-northeast-2
```

and got back full alarm metadata: state `OK`, threshold `100.0`, exact
`StateReasonData` with the breaching datapoints, plus a complete 30d/7d/1d/10m
alarm-history breakdown. `can_answer_root_cause: true`, no
`missing_required_context`.

## Why

The helper resolves alarms internally via boto3
`describe_alarms(AlarmNames=[alarm_name])`, passing the string as a Python
list element, not through shell/CLI string interpolation. The JSON-array
mis-parse only happens when a human types
`aws cloudwatch describe-alarms --alarm-names '[api-service] ...'` directly
into a shell, where the AWS CLI's own param-file/JSON-shorthand detection
kicks in on a leading `[`.

## Practical rule

Try `--alarm-name` with the exact bracketed string first, always. Only fall
back to the raw-CLI workarounds (`--query` contains-matching, direct boto3,
or `--alarm-names file:///tmp/alarm.txt`) when you are running a **manual**
`aws cloudwatch` CLI command yourself outside the helper, or when the helper
itself genuinely returns `missing_required_context: alarm_metadata` for some
other reason (e.g. the alarm name is simply wrong/stale).

## Re-confirmed 2026-07-08

Same alarm, same flow: `--alarm-name '[api-service] 4xx error response is
greater than 300 in 5m' --region ap-northeast-2` (via the automated Slack
subscription path this time, not a manually pasted alert). Returned full
alarm metadata (`state: ALARM`, threshold `100.0`), 30d/7d/1d/10m history
(71/27/2/2), current-alarm-window `logs.current_top_signatures` with
`count_in_current_alarm_window: 300`, and `can_answer_root_cause: true` on
the first call — no `missing_required_context`, no manual CLI fallback
needed. This is now the third independent confirmation that the bracket
does not break the helper. SKILL.md's inline pitfall text for this topic is
stale (still describes the old workaround-first advice) but the file is
already over the 100KB soft cap, so this reference file is the authoritative
version — trust this file over the inline SKILL.md wording if they ever
appear to disagree.
