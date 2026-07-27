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

parse @message '"status":*' as status raises MalformedQueryException:
Ephemeral field is already defined: status when the log line has "status" as
a top-level JSON key. Remove the parse clause or rename the alias.

## Correction — bin() is usable in stats ... by when aliased; the real trap is repeating it in sort

Live testing (2026-07-02, api-service 401 baseline check) showed bin(1h) does
**not** always raise MalformedQueryException in a stats ... by clause. The
actual failure mode is narrower: CloudWatch Logs Insights rejects a raw function
call like bin(1h) when it appears again in a **sort** clause.

```
# Fails: MalformedQueryException "unexpected symbol found ( at line N and position M"
# (position points at the '(' inside bin(1h) on the sort line)
stats count() as cnt by bin(1h)
sort bin(1h) asc

# Works: alias the bin() result in the stats clause, sort by the alias
stats count() as cnt by bin(1h) as hr
sort hr asc
```

Practical rule: whenever a stats ... by <func>(...) clause is used, give it an
explicit as <alias> and refer to <alias> in every later clause (sort,
filter, display) instead of repeating the function call. This applies to
bin() specifically confirmed working when aliased — re-test datefloor()
before assuming it behaves identically.

Also confirmed: passing the query string as a single line (no literal newline
characters inside the shell single-quoted string) avoids ambiguity about which
line/position the parser reports — prefer building multi-clause queries with
| separators on one line over multi-line heredoc-style strings when debugging
a MalformedQueryException, since the reported line number is otherwise easy
to miscount.
