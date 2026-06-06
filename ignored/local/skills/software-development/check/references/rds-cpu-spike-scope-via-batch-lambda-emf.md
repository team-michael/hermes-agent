# RDS CPU Spike Scope via Batch Lambda EMF Logs

## When to use this

- Aurora/RDS writer instance CPU alarm fires.
- `Performance Insights` returns `NotAuthorizedException` or the instance cannot be queried.
- The spike occurs during scheduled batch windows (typically top-of-the-hour KST when `scheduled-batch-delivery`, `scheduled-batch-kakao-alimtalk-delivery`, etc. run).
- You still need project scope attribution for the `범위` field.

## Principle

`Notifly/ScheduledBatchDelivery` EMF metrics emitted by `scheduled-batch-delivery` carry `project_id` and `campaign_id` in the log line, grouped by `table`. Even though CloudWatch metric dimensions only expose `channel`/`outcome`/`table`, the raw log entries contain the full project/campaign payload.

By running a Logs Insights query against `/aws/lambda/scheduled-batch-delivery` and parsing `project_id` where `table:"delivery_result"`, you can rank which `delivery_result_*` tables contributed the most INSERTs during the exact CPU spike window.

## Logs Insights query

```sql
fields @timestamp, @message
| filter @message like /"table":"delivery_result"/
| parse @message /"project_id":"(?<pid>[^"]+)"/
| stats count(*) as cnt by pid
| sort cnt desc
| limit 10
```

Set `start-time` and `end-time` to the exact alarm window (e.g. `00:58:00Z` to `01:08:00Z` for a 10:01 KST spike).

## Example result

| project_id                          | cnt   |
|-------------------------------------|-------|
| 560ac4c54db05db5bccc54788da901c5  | 53007 |
| 3ee6e5f95be353e48af47a7081f1716a  | 21885 |
| 02a3660e1b675689a0757409e5c1efaa  |  8949 |

Map `project_id` via DynamoDB `project` table to get product name.

## What this tells you

- The top projects by `delivery_result` INSERT volume during the spike window are the most likely CPU contributors on the writer.
- Combine with Lambda `Invocations` and `Duration` metrics to confirm the burst magnitude.
- If `Errors` is zero, the spike is a normal batch-completion surge, not a fault.

## Limitations

- Only works when the CPU spike is driven by scheduled-batch Lambdas (push, kakao, text). Not applicable for ad-hoc segment-publisher workloads or pure reader-replica load.
- `table` dimension is generic (`delivery_result`, `delivery_failure_log`, etc.), not the sharded table name. You must parse `project_id` from raw log text.
- If EMF logs are not present (older Lambdas, disabled EMF), this path cannot help.
