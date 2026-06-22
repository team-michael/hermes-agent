# Logs Insights `bin()` / `datefloor()` MalformedQueryException

## Problem

`bin(1d)` and `datefloor(@timestamp, 1d)` both raise `MalformedQueryException`
in `stats ... by` group-by clauses for structured JSON log groups:

```
MalformedQueryException: unexpected symbol found ( at line N and position M
```

This affects both forms:

```
# Fails
stats count(*) as cnt by bin(1d)

# Also fails
stats count(*) as cnt by datefloor(@timestamp, 1d)
```

## Workaround

Fetch one row per matching event via `count(*) by @timestamp` (capped at 10,000
rows by Logs Insights) and aggregate by day in Python:

```python
from collections import defaultdict
daily = defaultdict(int)
for row in r['results']:
    d = {f['field']: f['value'] for f in row}
    day = d.get('@timestamp', '')[:10]   # "2026-06-21T..." → "2026-06-21"
    daily[day] += 1
for day in sorted(daily):
    print(f"{day}: {daily[day]}")
```

**Limit**: the 10,000-row Logs Insights result cap means this is only reliable
for low-to-moderate volume queries (e.g., error logs, alarm-window samples).

## Alternatives for High-Volume Daily Aggregation

- `get_metric_statistics` with `Period=86400` on the relevant CloudWatch metric
  (e.g., `ConsoleErrors` Sum) — no row cap, direct daily bucket.
- Alarm history `OK→ALARM` transition counts per day — already computed by the
  `check` helper and free of the Logs Insights cap.

## Related Pitfall

`parse @message '"status":*' as status` raises `MalformedQueryException:
Ephemeral field is already defined: status` when the log line has `"status"` as
a top-level JSON key. Remove the `parse` clause or rename the alias.
