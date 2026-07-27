# Noisy percentile/tail-latency alarm tuning

Use this reference when a CloudWatch p95/p99/p99.9 alarm is operationally noisy but still points at a meaningful latency boundary.

## Mental model

Separate two knobs:

- `threshold`: what value counts as bad, e.g. p99 FCM send latency > 3000ms.
- `datapoints_to_alarm` / `evaluation_periods`: how persistent the bad value must be before paging.

If the alert is noisy because of isolated tail spikes, prefer adding persistence before increasing the threshold. Raising the threshold changes the definition of “bad”; adding persistence changes when humans are interrupted.

## Recommended investigation

1. Read live alarm config:
   - `MetricName`, `Namespace`, dimensions
   - `ExtendedStatistic` / `Statistic`
   - `Threshold`, `Period`
   - `EvaluationPeriods`, `DatapointsToAlarm`
   - `TreatMissingData`
2. Pull 30-day alarm history:
   - count `OK -> ALARM` state transitions
   - count action publishes if Slack/SNS noise matters
   - capture entry datapoint values from state reason where possible
3. Pull 30-day metric data and compute distribution:
   - p50/p90/p95/p99/p99.5/p99.9/max
   - compare the threshold to the metric distribution
4. Simulate candidate alarm configs:
   - current threshold with `1/1`
   - higher thresholds with `1/1`
   - current threshold with `2/2`, `2/3`, `3/3`
5. Explain mismatch carefully:
   - CloudWatch percentile alarm history and `GetMetricData` replay can differ because of percentile evaluation and retention/resolution behavior.
   - Use history for actual user-visible frequency; use replay for relative comparison across candidate configs.

## Candidate interpretation

For a 5-minute p99 latency alarm where normal 30-day distribution is around:

- p50 ~ 1s
- p95 ~ 1.7s
- p99 ~ 2.2s
- p99.5 just above 3s
- occasional max 7s+

and current config is `threshold=3000ms`, `evaluation_periods=1`, no explicit `datapoints_to_alarm`, the alert likely fires on isolated external-API tail jitter.

A balanced production change is often:

```hcl
threshold            = 3000
period               = 300
evaluation_periods   = 3
datapoints_to_alarm  = 2
```

This means: alert if at least 2 of the last 3 five-minute windows breach, i.e. roughly 10 bad minutes within 15 minutes.

## Why not just raise threshold?

Raising from 3000ms to 4000/5000/6000ms can reduce pages, but it also redefines acceptable tail latency. If 3000ms remains the user-impact boundary, raising it hides the problem instead of filtering noise.

Use threshold increase only when the threshold is clearly inside normal healthy variation or not tied to user impact.

## Final-answer shape

Include:

- current alarm condition in plain language
- 30-day actual alarm transition count from history
- metric distribution
- candidate simulation table
- chosen config and rationale
- expected behavior change

A concise phrasing that works well:

> The threshold is “what counts as bad latency”; datapoints/evaluation periods are “how long it must stay bad before waking a human.” This alert’s problem is persistence, not the bad-latency definition, so keep 3000ms and move from 1/1 to 2/3.
