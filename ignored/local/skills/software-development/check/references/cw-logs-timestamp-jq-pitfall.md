# CloudWatch Logs Timestamps and jq Pitfalls

## Input APIs

`aws logs filter-log-events --start-time X --end-time Y`  
Expects **epoch milliseconds**.

`aws logs start-query --start-time X --end-time Y`  
Also expects **epoch milliseconds**. Using seconds (e.g. `1716652500`) produces `MalformedQueryException: Query's end date and time is either before the log groups creation time or exceeds the log groups log retention settings` because the value is interpreted as milliseconds (year 1970) and falls outside the log group's retention window.

## Output fields

| API | Field | Unit |
|-----|-------|------|
| `filter-log-events` | `.events[].timestamp` | milliseconds |
| `describe-log-streams` | `.logStreams[].lastEventTimestamp` | milliseconds |
| `get-log-events` | `.events[].timestamp` | milliseconds |

## jq conversion

`jq` `todate` expects seconds since epoch. Passing milliseconds produces wildly wrong dates (e.g. year 58353).

Correct patterns:

```bash
# Convert CW timestamp to ISO 8601
(.timestamp / 1000 | todate)

# In a full pipeline
aws logs filter-log-events ... \
  | jq -r '.events[] | [.eventId, (.timestamp / 1000 | todate), .message] | @tsv'
```

## Shell epoch conversion

```bash
# Convert a readable UTC time to CW start-time/end-time (ms)
date -d '2026-05-20 16:51:00 UTC' +%s          # seconds
date -d '2026-05-20 16:51:00 UTC' +%s | awk '{print $1"000"}'  # milliseconds
```

## Pitfall — manually appending "000" to an ISO string or mis-typed epoch produces a silently wrong window

When converting an alarm's `StateReasonData.startDate` (ISO 8601, e.g. `2026-07-02T07:20:00.000+0000`) to epoch milliseconds by hand for `filter-log-events --start-time/--end-time`, a manual arithmetic slip (off-by-days, wrong year component, or reusing a stale `date -d` substitution) produces a window that is silently wrong — the command returns `{"events": [], "searchedLogStreams": []}` with exit code 0, which looks identical to "no matching logs exist" rather than "wrong time range". This is easy to miss because there is no error.

**Fix — always compute epoch ms from the exact ISO string via `execute_code`/Python, not by hand**:
```python
from datetime import datetime
dt = datetime.fromisoformat("2026-07-02T07:20:00.000+0000".replace("+0000", "+00:00"))
start_ms = int((dt.timestamp() - 600) * 1000)   # 10 min before
end_ms   = int((dt.timestamp() + 900) * 1000)   # 15 min after
```
Then pass `start_ms`/`end_ms` straight into `aws logs filter-log-events --start-time $start_ms --end-time $end_ms`. If a `filter-log-events` call for a confirmed-breaching datapoint returns zero events, re-derive the window with this exact method before concluding the logs are absent or delayed.

## CWLI query syntax — `bin()` in `sort`

CloudWatch Logs Insights rejects `sort bin(1d) desc` with `MalformedQueryException: unexpected symbol found (`. The `bin()` expression is valid in `stats` but not in `sort`.

**Correct**: omit `sort` when grouping by `bin()`; the result is returned in ascending time order by default.

```bash
aws logs start-query --region ap-northeast-2 \
  --log-group-name '/aws/ecs/notifly-services-prod/api-service' \
  --start-time $(date -d 'YYYY-MM-DD HH:MM:SS UTC' +%s)000 \
  --end-time   $(date -d 'YYYY-MM-DD HH:MM:SS UTC' +%s)000 \
  --query-string 'fields @timestamp, @message
| filter @message like /error-response/
| stats count() by bin(1d)
| limit 10'
```

**Incorrect**:
```
| stats count() by bin(1d)
| sort bin(1d) desc
| limit 10
```

## `filter-log-events` `filterPattern` special-character rejection

`aws logs filter-log-events` rejects patterns containing `:` or `,` with `InvalidParameterException: Invalid character(s) in term ':'` or `InvalidParameterException: Invalid character(s) in term ','`.

**Failing examples**:
```bash
# Colon inside a term
aws logs filter-log-events ... --filter-pattern '?Status: timeout'

# Comma inside a JSON-like brace pattern
aws logs filter-log-events ... --filter-pattern '{ $.message = "error-response", $.path = "/authenticate" }'
```

**Safe alternatives**:
1. Use simple space-separated quoted literal terms for phrase matching:
   ```bash
   aws logs filter-log-events ... --filter-pattern '"error-response" "/authenticate"'
   ```
   This matches log lines containing both substrings without structural syntax.

2. Use `aws logs start-query` with Logs Insights `filter` syntax, which does not have the same character restrictions:
   ```bash
   aws logs start-query ... --query-string 'fields @message
| filter message = "error-response" and path = "/authenticate"'
   ```

3. Read the full stream with `get-log-events` and filter client-side when the exact phrase filter is not required.

## `filter-log-events --output json` escapes embedded quotes, breaking naive `grep`

When you pull message bodies with `--query 'events[].message' --output json` and then `grep`/`grep -o` for a literal JSON substring (e.g. `"outcome":"failure"`), the AWS CLI JSON-encodes each string for the array output, so embedded double quotes are backslash-escaped (`\"outcome\":\"failure\"`). A grep pattern written with plain `"..."` quotes will not match the escaped form and silently returns zero results — it will look like "no matches" instead of a tooling mismatch.

**Failing pattern** (returns nothing even when the field exists):
```bash
aws logs filter-log-events ... --query 'events[].message' --output json \
  | grep -o '"outcome":"[a-z]*"' | sort | uniq -c
```

**Fix — use `--output text` for raw, unescaped message content before grepping**:
```bash
aws logs filter-log-events ... --query 'events[].message' --output text \
  | grep -o '"outcome":"[a-z]*"' | sort | uniq -c
```

This came up while computing a success/failure ratio for a `BatchCompletion` EMF metric window (`kakao-delivery-result-poller`) — the `--output json` version returned an empty count, and only switching to `--output text` revealed the true 47 success / 1 failure split. Treat an unexpectedly-empty grep result after `--output json` as a possible escaping artifact, not proof the pattern is absent — re-run with `--output text` (or parse with `jq -r '.[]'` instead of grepping the JSON-encoded array) before concluding zero matches.

## Logs Insights `stats` field ordering

`get-query-results` returns `stats ... by ...` result fields in an order that does **not** match the query declaration. Do not rely on array index position (`results[0]` = first declared field) when parsing with `jq`.

**Query**:
```
stats count() as cnt by status, path, method, level, projectId
```

**Result field order in API response** (example):
`status` (0), `path` (1), `method` (2), `level` (3), `projectId` (4), `cnt` (5)

**Safe parsing** — use the `field` name from the nested objects:
```bash
aws logs get-query-results --region ap-northeast-2 --query-id <id> --output json \
  | jq '.results[] | {cnt: (.[] | select(.field=="cnt").value), status: (.[] | select(.field=="status").value)}'
```

**Fast inspection** — read one raw result row to reveal field order before writing the full parser:
```bash
aws logs get-query-results ... | jq '.results[0][] | {field, value}'
```

## Manual counting over wide windows — avoid `filter-log-events --next-token` pagination timeouts

When a manual (non-helper) 7d/30d count of a rare log signature is needed on a high-volume log group, do not hand-roll a bash loop over `aws logs filter-log-events --next-token`. On busy Lambdas this can exceed the foreground terminal timeout (60-180s) before finishing all pages, especially over a 7-day window. Observed: a `filter-log-events` pagination loop against `kakao-delivery-result-poller` timed out at 60s, while an equivalent Logs Insights query over the same 7-day range returned in ~5s after scanning ~7M records / ~2.8GB. Use `start-query`/`get-query-results` for counts on wide windows instead:

```bash
qid=$(aws logs start-query --region ap-northeast-2 \
  --log-group-name /aws/lambda/<function> \
  --start-time $(date -d '7 days ago' +%s) --end-time $(date +%s) \
  --query-string 'fields @message | filter @message like /<exact phrase>/ | stats count() as cnt' \
  --output json | jq -r '.queryId')
sleep 5
aws logs get-query-results --region ap-northeast-2 --query-id "$qid" --output json
```

To check whether a rare signature is spread out or clustered (this distinction matters for `no_action` vs `needs_fix` — a same-day cluster of many events within a couple of minutes is a materially different signal than the same count spread evenly across 7 days), swap `stats count() as cnt` for `sort @timestamp asc` and read `@timestamp` from each result row.
