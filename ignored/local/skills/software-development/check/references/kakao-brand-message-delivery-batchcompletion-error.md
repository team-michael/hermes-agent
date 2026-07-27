# KakaoBrandMessageDelivery BatchCompletion `outcome=error` Triage

Applies to alarms in namespace `Notifly/KakaoBrandMessageDelivery`:
- `KakaoBrandMessage-P1-BatchFailure` (`BatchCompletion`, `outcome=error`)

## Alarm shape

- EMF metric emitted from Lambda `kakao-brand-message-delivery` stdout.
- NOT a CloudWatch log metric filter; there is no metric filter to inspect.
- Trigger Lambda: `kakao-brand-message-delivery`.
- Alarm threshold: `Sum >= 1` over 5 minutes.

## Classification rule

When `AWS/Lambda` `Errors == 0` for `kakao-brand-message-delivery` during the alarm window, classify as `no_action`.

## Root cause pattern A: handled validation rejection (missing `channel_id`)

Log signature:
```
ERROR\tMissing required data: invalid kakao_bizmessage sender info from event data\n
ERROR\tInvalid event data. Skipping this record.\n
INFO\t{"_aws":{"Timestamp":...,"CloudWatchMetrics":[{"Namespace":"Notifly/KakaoBrandMessageDelivery",...,"Metrics":[{"Name":"BatchCompletion","Unit":"Count"}]}]},"channel":"kakao-brand-message","outcome":"error","BatchCompletion":1,"error_message":"Invalid event data","project_id":"...","campaign_id":"..."}\n
```

- Source: `services/lambda/kakao-brand-message-delivery/lib/utils.ts:51`
- Condition: `kakao_sender_info.channel_id` is missing or falsy in the SQS record body.
- Common when the message was **re-enqueued by `kakao-delivery-result-poller`** (check `SenderId` in SQS attributes).
- The Lambda catches the validation error, logs it, emits `BatchCompletion outcome=error`, and exits normally (`Duration` ~1-2 ms, no throw).
- `AWS/Lambda Errors` metric remains 0.

## Scope extraction

- `project_id` and `campaign_id` are present in the SQS body and in the EMF metric line.
- Map `project_id` via DynamoDB `project` table.
- If `resource_type` is present in the payload, use it (`campaign` or `user_journey`).

## Bounded manual trace commands

```bash
# 1. Lambda Errors / Throttles
aws cloudwatch get-metric-statistics --region ap-northeast-2 \
  --namespace AWS/Lambda --metric-name Errors \
  --dimensions Name=FunctionName,Value=kakao-brand-message-delivery \
  --start-time 'YYYY-MM-DDTHH:00:00Z' --end-time 'YYYY-MM-DDTHH:59:59Z' \
  --period 300 --statistics Sum

# 2. Bounding the log window around the alarm datapoint
# Use StateReasonData.startDate or metric timestamp -> epoch ms
start_ms=$(date -d 'START_UTC' +%s)000
end_ms=$(date -d 'END_UTC' +%s)000
aws logs filter-log-events --region ap-northeast-2 \
  --log-group-name /aws/lambda/kakao-brand-message-delivery \
  --start-time "$start_ms" --end-time "$end_ms" \
  --filter-pattern 'ERROR' \
  --output json | jq -c '.events | map({ts:(.timestamp/1000|todateiso8601),msg:.message})'

# 3. Identify SQS SenderId to confirm re-enqueued by poller
aws logs get-log-events --region ap-northeast-2 \
  --log-group-name /aws/lambda/kakao-brand-message-delivery \
  --log-stream-name 'YYYY/MM/DD/[$LATEST]...' \
  --output json | jq '.events[] | select(.message | contains("SenderId")) | .message' | jq -Rr 'fromjson? | .Records[0].attributes.SenderId // empty'
```

## Distinguishing from real bugs

| Signal | Handled rejection (Pattern A) | Real bug |
|--------|------------------------------|----------|
| `AWS/Lambda Errors` | 0 | > 0 |
| `Duration` | ~1-2 ms | Normal execution time or timeout |
| Log line | `Invalid event data. Skipping this record.` | Stack trace, unhandled exception |
| `SenderId` | `AROA...:kakao-delivery-result-poller` re-enqueue | Varies |

## Frequency baseline

As of 2026-06-04, single occurrence. Long-term trend should be checked with:
```bash
aws cloudwatch get-metric-statistics --region ap-northeast-2 \
  --namespace Notifly/KakaoBrandMessageDelivery --metric-name BatchCompletion \
  --dimensions Name=channel,Value=kakao-brand-message Name=outcome,Value=error \
  --start-time 'YYYY-MM-DDT00:00:00Z' --end-time 'YYYY-MM-DDT23:59:59Z' \
  --period 86400 --statistics Sum
```

## Remediation options

Downgrade `console.error` to `console.warn` at `lib/utils.ts:51` when validation rejection is expected (e.g., missing `channel_id` due to poller re-enqueue with incomplete metadata). The batch is skipped normally; emitting at ERROR level only trips the metric.
