# Lambda Kinesis Consumer: DB Read Timeout Silent Data Loss

Class-level reference for Lambda alarms in the `ConsoleErrors` namespace where a Kinesis consumer Lambda logs `ERROR` due to DB read timeout, but the invocation completes normally (`AWS/Lambda Errors == 0`) because the code catches the error and returns an empty result. The Kinesis checkpoint advances, causing the failed records to be silently skipped without retry.

## Quick classification

- `AWS/Lambda Errors == 0` and `Throttles == 0`
- Log lines contain `Query read timeout` and a sharded table name (e.g., `user_journey_nodes_<project_id>`, `user_journeys_<project_id>`)
- Lambda `Duration` is elevated (e.g., 240s–480s) but under `Timeout`
- Kinesis iterator age remains near zero, because the Lambda returns normally and the batch is checkpointed
- This is a **real data-loss signal**, not a false positive, because the failed records are not retried
- Classification: `needs_fix` because the error-handling policy silently drops records instead of surfacing failure for retry

## Known pattern: user-journey-node-runner

### Trigger signatures

- `ERROR Error fetching user journey nodes: Error: Query read timeout Query: select * from "user_journey_nodes_<project_id>" where "id" in (...)`
- `ERROR Error fetching user journey by id <id>: Error: Query read timeout Query: select "abnormal_exit_node_id" from "user_journeys_<project_id>" where "id" = '<id>' limit 1`

### Code paths

- `services/lambda/user-journey-node-runner/lib/repositories/UserJourneyNodeRepository.ts:23-26`
  ```ts
  } catch (error) {
      console.error('Error fetching user journey nodes:', error);
      return [];
  }
  ```
- `services/lambda/user-journey-node-runner/lib/repositories/UserJourneyRepository.ts:57-60`
  ```ts
  } catch (error) {
      console.error(`Error fetching user journey by id ${userJourneyId}:`, error);
      return undefined;
  }
  ```

### Why it is data loss

`user-journey-node-runner` is a Kinesis consumer. When `getUserJourneyNodes` or `getAbnormalExitNodeId` returns `[]`/`undefined` due to a caught DB timeout, the calling code in `ContextSetupService.ts` (and `ExitHandlerService.ts`) treats the failure as "node not found" and skips the record. The Lambda continues processing the remaining batch and returns normally. Because there is no unhandled exception, the Kinesis checkpoint advances and the failed records are never retried.

### Impact

- The affected user-journey node records are skipped silently.
- No messages are sent for those records.
- No DLQ or retry is triggered because the Lambda returns successfully.

### Scope extraction

- Extract `project_id` directly from the table suffix in the ERROR log (e.g., `user_journey_nodes_8172b3a8b8fe57ad9cc41a03646b0947`).
- Map via DynamoDB `project` table.
- Also look for `user_journey_id` in the same log line (e.g., `id = 'RBdAj8'`).

### Correlation checks

1. **EventSourceMapping `LastModified`**: Check `aws lambda get-event-source-mapping` for the consumer. If `LastModified` falls within hours of the alarm onset, a recent ESM configuration change (batch size, starting position, etc.) may have destabilized the consumer.
2. **DB metrics**: Check `AWS/RDS` `ReadLatency` and `CPUUtilization` on the cluster during the alarm window. If `ReadLatency` is normal (< 5 ms) but the Lambda still times out, the issue may be connection-pool exhaustion or query-level locking, not general DB overload.
3. **Kinesis iterator age**: `GetRecords.IteratorAgeMilliseconds` should be near zero. If it is elevated, the consumer is falling behind; if it is zero, the consumer is checkpointing successfully while silently dropping records.
4. **Lambda `Duration`**: Compare `p99` or `Maximum` Duration against the `Timeout`. Values near 240s or 480s (exact multiples of statement_timeout) strongly suggest a query-level timeout rather than a Lambda-level timeout.

### Remediation

1. **Immediate**: Do not restart the Lambda or purge the Kinesis stream. The failed records are already lost; focus on preventing further loss.
2. **Short-term**: Increase the `statement_timeout` or query-level timeout for the affected repository functions, or add a circuit breaker.
3. **Structural fix**: Change the error-catching policy in `UserJourneyNodeRepository.ts` and `UserJourneyRepository.ts` so that DB timeout failures throw an unhandled exception (or return a batch-item failure for Kinesis), causing the Lambda to fail and Kinesis to retry the record. Do not return `[]`/`undefined` on a timeout.
4. **TF/code target**: `services/lambda/user-journey-node-runner/lib/repositories/UserJourneyNodeRepository.ts:23-25` and `UserJourneyRepository.ts:57-59`.

### Bounded log check

```bash
python3 -c "
import boto3, datetime
session = boto3.Session(region_name='ap-northeast-2')
logs = session.client('logs')
start = int(datetime.datetime(YYYY, MM, DD, HH, MM, tzinfo=datetime.timezone.utc).timestamp() * 1000)
end   = int(datetime.datetime(YYYY, MM, DD, HH, MM, tzinfo=datetime.timezone.utc).timestamp() * 1000)
resp = logs.filter_log_events(
    logGroupName='/aws/lambda/user-journey-node-runner',
    startTime=start, endTime=end,
    filterPattern='Query read timeout',
    limit=20
)
for e in resp.get('events', []):
    print(e['message'].strip()[:400])
"
```

### Pitfall — connection-pool timeout vs query timeout

A `Query read timeout` with `Duration` under `Timeout` but over `statement_timeout` (usually 120s or 240s) indicates the query was killed by the server-side `statement_timeout`, not by the Lambda runtime. In this case the pg client receives an error and rejects the promise, which the code catches. If the `Duration` equals the Lambda `Timeout` (e.g., 900s) and the last log line is `REPORT ... Status: timeout`, the Lambda itself timed out before the query finished. The former is a handled error (silent data loss); the latter is an unhandled timeout (Kinesis will retry). Distinguish them by checking whether `REPORT` shows `Status: timeout` or a normal completion.

### Pitfall — large daily log counts on a single bad day

Check `logs.daily_counts_30d`. A single day with thousands of ERROR logs (e.g., 2026-05-15: 6,316) may be caused by an Aurora reader-replica conflict (`canceling statement due to conflict with recovery`) rather than the current DB read timeout pattern. Always inspect the current trigger context before assuming the historical high-volume day is the same cause as the current alarm.
