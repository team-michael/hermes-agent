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
