# CloudWatch Logs Timestamps and jq Pitfalls

## Input APIs

`aws logs filter-log-events --start-time X --end-time Y`  
Expects **epoch milliseconds**.

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
