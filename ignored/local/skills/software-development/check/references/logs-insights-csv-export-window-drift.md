# Ad-hoc CSV/time-series export from CloudWatch Logs Insights (follow-up requests)

Trigger: user asks a follow-up like "지난 N시간 호출 시간을 csv로 뽑아줘" /
"export the call timestamps as CSV" after an alert has already been triaged.
This is a different shape than the fixed `check` templates — it is an ad-hoc
extraction request, but it hits two real Logs Insights mechanics that will
burn you if you don't plan for them up front.

## Pitfall 1 — recomputing "now" between sequential AWS calls causes window drift

Do **not** write `END_TS=$(date -u +%s)` (or any `date` call) more than once
across a multi-step extraction/verification sequence. Each `aws logs
start-query` + `get-query-results` round trip takes real wall-clock seconds.
If you recompute `END_TS`/`START_TS` in every verification query "just to
double check", each query silently gets a different window, and you will see
contradictory counts (e.g. one query says 633 matches, a near-identical query
run 20 seconds later says 1524) that look like a CloudWatch bug but are just
window drift.

Fix: compute `START_TS`/`END_TS` (or a single fixed ISO/epoch pair) **once**
at the top of the investigation, store them in shell variables (or a small
script), and reuse the exact same literals for every sub-query, cross-check,
and the final export. Never call `date -u +%s` a second time mid-investigation
to "confirm" a window.

## Pitfall 2 — 10,000-row Logs Insights result cap on raw event dumps

`aws logs start-query` with a raw `sort @timestamp asc | limit N` query is
capped at 10,000 returned rows even if `recordsMatched` in `.statistics` is
much higher (e.g. 22,559 matched, only 10,000 returned, silently truncating
the tail of the window). Do not treat a `Complete` status with exactly 10,000
rows as "got everything" — always check `.statistics.recordsMatched` against
the row count returned.

Fix: split the fixed window into sub-windows small enough that each
sub-window's `recordsMatched` is comfortably under 10,000, run one query per
sub-window, and concatenate results. The splitting logic works for either raw
event export or `stats count() by bin(1m)` aggregation — per-minute
aggregation itself rarely hits the row cap since each sub-window only emits
one row per minute, but you still want the same sub-window loop so all
sub-queries share the one fixed START_TS/END_TS pair from Pitfall 1.

## Pitfall 3 — do not assume a `bin(1m)` gap at the start of a window is a tooling bug

If a `stats count() by bin(1m)` result starts later than the requested
`--start-time` (e.g. window requested at 01:23 UTC but first bucket is
01:40 UTC), do not immediately blame Logs Insights bucket-boundary alignment.
Verify first with a raw, unaggregated query anchored to the *exact same fixed
window* (`sort @timestamp asc | limit 5`, no `stats`) to see the true
timestamp of the first matching event. In the 2026-07-03 `regather`
`/track-event` 401 case, the gap was real — the alarm's dip-then-respike cycle
genuinely had zero matching events between 01:23-01:40 UTC, confirmed by the
raw dump showing the first event at exactly 01:40:00.776. Trust the raw dump
over any assumption about `bin()` alignment.

## Recommended flow for "export last N hours as CSV"

1. Fix `START_TS`/`END_TS` once (epoch seconds), print them for the log.
2. Decide raw-event export (user wants individual call timestamps) vs
   per-minute/per-hour aggregate (user wants a trend/volume view). Prefer raw
   export when the ask is literally "호출 시간"/"call times" — an aggregate
   is a lossy compromise, only fall back to it if raw rows would exceed the
   cap even after reasonable sub-window splitting.
3. Split into sub-windows sized so each chunk's `recordsMatched` is well under
   10,000 (start with 10-20 min chunks for services doing hundreds of
   matches/min; shrink further if `recordsMatched` still hits the cap).
4. Concatenate/merge, convert timestamps to both UTC and KST columns, write
   CSV via `execute_code` (never hand-roll CSV string concatenation in bash).
5. Report total row count and the true first/last timestamp actually covered,
   so the user knows if any part of the requested window had zero data vs.
   was silently dropped.
