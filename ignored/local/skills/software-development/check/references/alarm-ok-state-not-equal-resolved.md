# Pitfall: "alarm state is OK" is not the same as "issue resolved"

## The mistake

Threshold-and-period CloudWatch alarms (e.g. `Sum > 100 in 5m`,
`GreaterThanThreshold` over a handful of 5-min datapoints) evaluate a short,
noisy window. A bursty client, retry storm, or intermittently-failing
dependency does not send at a constant rate — the metric naturally dips below
threshold between bursts, flipping the alarm back to `OK`, even while the
underlying condition (invalid token, broken integration, degraded upstream
dependency) is still active and still causing customer-facing failures or
data loss.

Concrete case: `[api-service] 4xx error response is greater than 300 in 5m`
alarm for project `regather` (`b57754a9497a545ab9b0e4aadd6f53b6`). A single
client (`43.200.115.9`, `undici`) was retry-storming `/track-event` with an
invalid auth token. The alarm had already fired and been documented twice
earlier the same day with escalating same-day cumulative totals (20,491 →
59,183). On the third check, the discrete 5-min datapoints had just dropped
below threshold and `describe-alarms` reported `State: OK`. The check was
classified `no_action` on the strength of that `OK` state alone — but the
day-cumulative count had actually kept climbing to 90,644 (still the same
unresolved token, same customer, same client). The correct classification per
the escalation-tracking guidance already on record for this incident was
`needs_fix` or `urgent`, not `no_action`. See
`api-service-track-event-401-invalid-verifytoken.md` for the full incident
timeline.

## The rule

Before classifying `no_action` on the strength of a recovered/OK discrete
alarm state:

1. Check whether this alarm/project/signature combination has an existing
   reference file with a documented same-day timeline. If so, treat this as a
   probable continuation, not a fresh evaluation.
2. Re-run (or reuse from the helper output) the same-day cumulative count
   for the specific project/path/status/error signature, and compare it
   against the known multi-day baseline (7d/30d daily averages) — not just
   the current 5-minute datapoints.
3. If the day-total is still far above baseline and still climbing versus
   any prior same-day check already on record, classify by the trend, not by
   the momentary alarm state:
   - still escalating, no engineering/customer contact evidence yet →
     `needs_fix` (or `urgent` on a 2nd+ same-day repeat with tens of
     thousands of cumulative failures and no sign of flattening).
   - flat or declining since the last documented check, and comfortably
     within historical baseline → `no_action` is fine.
4. This applies generally to any bursty/retry-storm-shaped alarm, not just
   the `/track-event` 401 case — SQS age alarms, Lambda error-rate alarms,
   and other `Sum`/`Average`-over-a-short-period alarms all share this
   noisy-recovery characteristic.
