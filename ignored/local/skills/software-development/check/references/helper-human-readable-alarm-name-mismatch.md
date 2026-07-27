# Helper Constructs Wrong Alarm Name from Human-Readable Alert Description

## Problem

When Amazon Q / AWS Chatbot delivers alert text like:

```
CloudWatch Alarm | notifly-db-prod-cluster CPUUtilization too high | ap-northeast-2 | Account: 702197142747
```

The phrase `CPUUtilization too high` is a human-readable description injected by the Amazon Q alert template, not the actual CloudWatch alarm name. The helper text parser constructs `notifly-db-prod-cluster CPUUtilization too high` as `detected.alarm_name`, which does not match any CloudWatch alarm.

## Symptoms

- Helper returns `alarm.name: null`, `alarm.state: null`
- `missing_required_context` includes `alarm_metadata` with reason "CloudWatch describe_alarms did not return usable alarm metadata"
- `can_answer_root_cause: false`
- `history.alarm_count_30d: 0`, `history.alarm_count_7d: 0` (all zero because no alarm was found)

## Workaround

Inspect the `code` section of the helper output. The helper's Terraform source search uses keyword tokens (e.g., `cpuutilization`) and typically matches the actual Terraform `aws_cloudwatch_metric_alarm` resource, revealing the real `alarm_name` field.

Example helper `code` output:
```json
{
  "token_preview": "cpuutilization",
  "file": ".../infra/terraform/prod/ap-northeast-2/rds/dynamic_alarms.tf",
  "match": "alarm_name = \"notifly-db-prod-instance-high-cpu-usage\""
}
```

Extract the `alarm_name` value from the Terraform match and run `describe_alarms` manually:

```bash
aws cloudwatch describe-alarms --region ap-northeast-2 \
  --alarm-names 'notifly-db-prod-instance-high-cpu-usage' \
  --output json
```

Then proceed with alarm history, metric datapoints, and scope attribution as normal.

## When this pattern occurs

- Any Metrics Insights or dynamic alarm whose CloudWatch name differs from the human-readable label in the Amazon Q alert text
- Alarms named with kebab-case resource identifiers (e.g., `notifly-db-prod-instance-high-cpu-usage`) when the alert text uses prose (e.g., `CPUUtilization too high`)
- Not limited to RDS/CPU alarms; can affect any alarm where the SNS notification subject or Amazon Q template uses a description rather than the literal alarm name

## Related

- `references/aurora-writer-cpu-batch-lambda-spike.md` — the specific alarm (`notifly-db-prod-instance-high-cpu-usage`) that triggered this pitfall
- SKILL.md pitfall "CloudWatch Metrics Insights `metric_query` alarms return null metric fields" — companion issue where the same alarm type also has null metric fields
