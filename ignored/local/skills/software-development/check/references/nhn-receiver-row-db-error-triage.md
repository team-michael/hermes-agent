# `nhn-receiver-row-db-error` — DeliveryResultWebhookReceiver `db_error` Aurora Replica Conflict

Alarm family for the `delivery-result-webhook-receiver` Lambda's EMF `RowOutcome` metric when Aurora reader replica recovery conflicts surface as `db_error` outcomes.

## Alarm shape

- **Alarm name**: `nhn-receiver-row-db-error`
- **Type**: CloudWatch Metric Insights query alarm (not log metric filter)
- **Query**: `SELECT SUM(RowOutcome) FROM SCHEMA("Notifly/DeliveryResultWebhookReceiver", outcome, channel) WHERE outcome = 'db_error'`
- **Threshold**: `0`, `EvaluationPeriods: 1`, `Period: 300`
- **Namespace**: `Notifly/DeliveryResultWebhookReceiver`
- **Metric**: `RowOutcome` with dimensions `outcome=db_error`, `channel` varies
- **Underlying service**: `/aws/lambda/delivery-result-webhook-receiver` (Lambda, not ECS)

## Helper gap

The helper script does **not** auto-resolve Metric Insights alarms to their underlying service or log group. For this alarm it typically returns:
- `"metric": { "namespace": null, "name": null }`
- `"log_groups": []`
- `"scope_kind": "unknown"`

Do not halt when the helper output is thin. Immediately run the bounded manual trace below.

## Bounded manual trace

### 1. Confirm Lambda ERROR log family and count

```bash
start_ms=$(date -d '20 minutes ago' +%s)000
end_ms=$(date +%s)000
aws logs filter-log-events --region ap-northeast-2 \
  --log-group-name /aws/lambda/delivery-result-webhook-receiver \
  --start-time "$start_ms" --end-time "$end_ms" \
  --filter-pattern 'ERROR' --output json | \
  jq -r '.events | length'
```

### 2. Identify the dominant error signature

```bash
aws logs filter-log-events --region ap-northeast-2 \
  --log-group-name /aws/lambda/delivery-result-webhook-receiver \
  --start-time "$start_ms" --end-time "$end_ms" \
  --filter-pattern 'ERROR' --output json | \
  jq -r '.events[].message' | grep -c 'canceling statement due to conflict with recovery'
```

If the count from step 2 equals (or nearly equals) the count from step 1, the alarm is a pure Aurora replica conflict.

### 3. Extract project scope from EMF metric lines

The `db_error` events are also emitted as EMF metrics at `INFO` level. Extract `project_id` and `channel`:

```bash
aws logs filter-log-events --region ap-northeast-2 \
  --log-group-name /aws/lambda/delivery-result-webhook-receiver \
  --start-time "$start_ms" --end-time "$end_ms" \
  --filter-pattern 'db_error' --output json | \
  jq -r '.events[].message' | \
  grep -oP '"project_id":"[a-f0-9]+"' | sed 's/"project_id":"//;s/"$//' | \
  sort | uniq -c | sort -rn
```

Also extract `channel` distribution:

```bash
... | grep -oP '"channel":"[^"]+"' | sort | uniq -c | sort -rn
```

Map top `project_id` values through DynamoDB `project` table.

### 4. Cross-check Lambda health metrics

```bash
aws cloudwatch get-metric-statistics --region ap-northeast-2 \
  --namespace AWS/Lambda --metric-name Errors \
  --dimensions Name=FunctionName,Value=delivery-result-webhook-receiver \
  --start-time ... --end-time ... --period 300 --statistics Sum \
  --output json | jq -r '.Datapoints | sort_by(.Timestamp)[] | "\(.Timestamp): \(.Sum)"'
```

Also check `Duration` (Average, Maximum). A spike with `Errors == 0` confirms the Lambda completed (or was retried by the pg driver) despite the replica conflict.

### 5. Verify RDS recovery

```bash
aws cloudwatch get-metric-statistics --region ap-northeast-2 \
  --namespace AWS/RDS --metric-name ReadLatency \
  --dimensions Name=DBClusterIdentifier,Value=notifly-db-prod-cluster \
  --start-time ... --end-time ... --period 300 \
  --statistics Average Maximum --output json | \
  jq -r '.Datapoints | sort_by(.Timestamp)[] | "\(.Timestamp): avg=\(.Average) max=\(.Maximum)"'
```

Return to normal (`ReadLatency` < 0.005 s) confirms transient recovery.

### 6. Check for cluster-wide correlation

A replica conflict affecting the webhook receiver often also hits `api-service` simultaneously. Verify:

```bash
aws logs filter-log-events --region ap-northeast-2 \
  --log-group-name /aws/ecs/notifly-services-prod/api-service \
  --start-time "$start_ms" --end-time "$end_ms" \
  --filter-pattern 'canceling statement due to conflict with recovery' \
  --output json | jq -r '.events | length'
```

High counts in `api-service` at the same time strongly support the infra-wide transient Aurora hiccup hypothesis.

## Scope attribution

- **Primary**: Extract `project_id` from EMF metric lines (`"project_id":"..."`).
- **Secondary**: Extract `project_id` from the sharded table suffix in ERROR lines (`delivery_result_<project_id>`).
- **Channel**: EMF `channel` dimension (`kakao-alimtalk`, `kakao-friendtalk`, `push`, `sms`, `email`, etc.).
- **Campaign/user journey**: The `delivery_result` table carries `resource_type` and `event_name`, but the alarm window is usually too narrow to reliably aggregate campaign IDs. Prefer reporting the affected projects and channels; mark campaign/user journey as specific 불가 unless further Postgres/Athena lookup yields a clear top contributor.

## Classification

| Condition | Status | Rationale |
|---|---|---|
| All ERROR lines are `canceling statement due to conflict with recovery`; Lambda `Errors == 0`; ReadLatency recovered to normal within 10–15 min; 30-day recurrence ≤ 1–2 | `no_action` | Aurora transient replica conflict. Messages were already sent by Kakao/NHN; DB sync retry usually succeeds on next webhook batch. |
| Same signature but sustained > 1 hour, or daily recurrence at same clock time | `needs_fix` | Chronic reader-replica pressure. Consider log-level downgrade or DBA review. |
| Mixed with other ERROR patterns (unhandled exception, `relation does not exist`, network timeout) | `needs_fix` | The db_error may be masking or compounding another issue. |
| Lambda `Errors > 0` or `Duration` consistently near timeout after recovery | `needs_fix` | Indicates retry exhaustion or a hang beyond the replica conflict itself. |

## Distinctive fields for final answer

- Mention `delivery-result-webhook-receiver` Lambda explicitly.
- Mention `Notifly/DeliveryResultWebhookReceiver` EMF namespace and `RowOutcome` metric.
- Mention `canceling statement due to conflict with recovery` with PG code `40001`.
- Note that Lambda `Errors == 0` means the invocation completed (or driver-retried), distinguishing this from a Lambda crash.
- Note that the messages were already delivered by the external provider (Kakao/NHN); the `db_error` is a post-delivery webhook callback sync failure, not a delivery failure.
