# Slack subscription alarm-name discovery

Session note: Amazon Q / AWS Chatbot subscription payloads may surface only a log-group path plus a human hint, while the actual CloudWatch alarm name is different.

## What happened in this session
- Pasted subscription text: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query | ap-northeast-2`
- Helper output: `detected.alarm_name = null`
- Direct CloudWatch lookup by service prefix revealed a different matching alarm name: `segment-publisher-triggerer lambda error`
- The `segment-publisher` log group also had related metric filters:
  - `segment-publisher-prod console error`
  - `segment-publisher-prod slow eic query`

## Reusable fallback
1. If the helper cannot parse `alarm_name`, search CloudWatch with `describe_alarms` using:
   - exact pasted string
   - service-name prefix
   - log-group stem
2. Inspect `StateReasonData` and `MetricAlarms[].MetricName/Namespace/Dimensions` for the actual alarm.
3. Do not assume the subscription text is the literal alarm name.
4. When a log group has multiple related filters, classify using the alarm’s concrete metric filter and the latest breaching datapoint, not the first human-readable hint.

## Useful command shape
```bash
aws cloudwatch describe-alarms --region ap-northeast-2 \
  --query 'MetricAlarms[?contains(AlarmName, `segment-publisher`) || contains(AlarmName, `slow eic`) || contains(AlarmName, `triggerer`)].{Name:AlarmName,Namespace:Namespace,MetricName:MetricName,State:StateValue,Reason:StateReason}' \
  --output json
```

## Related pitfall
This often coexists with alarm-name mismatches where a log group is reused across multiple Terraform alarms, so a subscription message can describe the symptom while a different alarm name carries the actual CloudWatch state transition.
