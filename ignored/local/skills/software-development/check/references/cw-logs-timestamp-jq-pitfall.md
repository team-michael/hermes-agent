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
