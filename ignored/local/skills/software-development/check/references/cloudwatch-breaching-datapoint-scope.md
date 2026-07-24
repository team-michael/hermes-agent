# CloudWatch breaching-datapoint scope for log-derived alerts

## When to use

Use this for Notifly Slack/Amazon Q / CloudWatch log-derived alarms where the helper or manual triage risks mixing unrelated logs from the same log group/stream into the final answer.

## Problem pattern

CloudWatch alarm transition time is not always the same as the log-event timestamp that breached the metric. If triage queries a broad window such as `ALARM transition ±15~30m`, a busy log group can contain unrelated events. Those unrelated events can pollute:

- root-cause summary
- project/campaign/user-journey scope
- severity/status decision
- suggested action item

Typical contaminated fields:

- `logs.recent_trigger_contexts`
- `logs.top_signatures`
- 7d/30d sample rows
- neighboring `surrounding_lines` in the same stream

These are useful for baseline/frequency, not for current root cause.

## Correct boundary

For the current alert, prefer CloudWatch `newState.stateReasonData.evaluatedDatapoints` from alarm history.

Use the evaluated breaching datapoint timestamp and period as the primary window:

```text
start = min(evaluatedDatapoints[].timestamp)
end   = max(evaluatedDatapoints[].timestamp) + period
```

For a 60s metric alarm with `evaluatedDatapoints[0].timestamp = 2026-06-22T05:42:00Z`, query only:

```text
2026-06-22T05:42:00Z <= log timestamp < 2026-06-22T05:43:00Z
```

Only fall back to a broader transition-relative window if `stateReasonData` is missing or unparsable.

## Scope rules

- Treat `logs.current_error_details` and the exact breaching datapoint trigger line as current evidence.
- Treat `logs.recent_trigger_contexts`, `logs.top_signatures`, and 7d/30d samples as historical baseline only.
- Do not promote project/campaign/user-journey IDs from broad samples or neighboring `surrounding_lines` unless the actual trigger is generic (`ERROR`, `severity: ERROR`) and the neighboring line is part of the same error block.
- If the exact trigger line contains no project/campaign evidence, say scope is unknown rather than borrowing IDs from nearby invocations.
- Filter nullish placeholders such as `campaign_id: undefined`; they are not real campaign IDs.

## Concrete examples

### segment-publisher slow eic query

Before narrowing, a broad window could mix a batch-duration Pattern B or historical campaign evidence into a slow-EIC alert.

Correct current evidence came from the exact breaching datapoint window:

```text
current_alarm_window.basis = latest_alarm_state_reason_data
start = 2026-06-22T05:42:00Z
end   = 2026-06-22T05:43:00Z
trigger = EventCounterCteManager.extract:<project_id> took too long: 156472ms
```

If that trigger has no concrete project ID after sanitization, report project/campaign as unknown instead of using historical `NX5iRi`/munice or Pattern B context.

### kakao-brand-message-delivery lambda error

The exact breaching minute may contain metric-filter matches inside request payload or URL text. Neighboring SQS/event logs in the same stream can include many campaign IDs. Do not use those neighboring campaign IDs as scope unless they are on the actual breaching trigger line.

## Regression-test shape

Add/keep tests that prove:

- alarm history preserves `newState.stateReasonData`
- `alarm_trigger_window()` uses the breaching datapoint period when available
- recent sample scope is not promoted to current scope
- neighboring `surrounding_lines` do not become scope for concrete trigger lines
- concrete trigger lines do not re-anchor to nearby lower-scored but unrelated context
