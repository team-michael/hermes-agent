# CloudWatch `describe-alarm-history` MaxRecords=100 undercounts high-frequency alarms

## Symptom

When computing `빈도:` (30일/7일/1일/10분) OK→ALARM transition counts from
`describe_alarm_history`, a single unpaginated call defaults to
`MaxRecords=100`. Both `OK` and `ALARM` (and `INSUFFICIENT_DATA`) history
items count against this shared cap — not just the transitions you care
about. For any alarm that fires more than roughly 50 times inside the
requested window, one call only returns the most recent ~100 items, which
may cover just the last few days of a 30-day window.

Concrete example (`[api-service] 4xx error response is greater than 300 in 5m`,
2026-07-03 triage): a naive 30d query with `MaxRecords=100` returned exactly
100 items truncated to roughly the last 3.5 days, undercounting the true
30-day OK→ALARM transition total. The reported "30d" number ended up close
to or even lower than a separately-queried, tightly-scoped "7d" number —
that inversion is the tell that pagination was needed.

## Fix

- For any window likely to exceed ~50 alarm state changes, either:
  1. Paginate with `NextToken` until `describe_alarm_history` stops
     returning one, then filter transitions client-side, or
  2. Run separate `describe_alarm_history` calls scoped exactly to each
     window (7d, 1d, 10m) with tight `StartDate`/`EndDate` — these rarely
     hit the 100-item cap on their own. Only the 30d call typically needs
     pagination.
- Do not derive 7d/1d/10m counts by re-filtering a single possibly-truncated
  30d result; each window should be queried (or paginated) independently.
- When reporting `빈도:` for a known noisy/daily-firing alarm and pagination
  wasn't done, say the 30d count is a floor/approximate rather than
  presenting it as exact.

## Minimal pagination snippet

```python
def full_alarm_history(cw, alarm_name, start, end):
    items = []
    kwargs = dict(AlarmName=alarm_name, HistoryItemType='StateUpdate',
                  StartDate=start, EndDate=end, MaxRecords=100)
    while True:
        resp = cw.describe_alarm_history(**kwargs)
        items.extend(resp['AlarmHistoryItems'])
        token = resp.get('NextToken')
        if not token:
            break
        kwargs['NextToken'] = token
    return items
```
