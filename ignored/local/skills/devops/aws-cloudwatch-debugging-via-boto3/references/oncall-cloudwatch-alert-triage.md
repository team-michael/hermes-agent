# OnCall: CloudWatch Console Error Alert Triage

## Goal
Turn a raw CloudWatch console-error alarm into a concrete judgment (spike / recurring / needs_fix / urgent) with evidence from logs and infrastructure metrics.

## Prerequisites
- AWS CLI configured for the correct region (`ap-northeast-2` for prod)
- Read-only access to CloudWatch Logs and CloudWatch Metrics
- Alert `message_ts` (Slack) for precise time correlation

## Workflow

### 1. Parse the alert
- Identify: service, log group, region, alarm name, `message_ts`
- Convert `message_ts` to human UTC:
  ```bash
  python3 -c "import datetime; print(datetime.datetime.fromtimestamp(<message_ts>, tz=datetime.timezone.utc))"
  ```

### 2. Scan recent ERROR logs (last 1–2 hours)
Build a window around the alert to see what actually happened.

```bash
START=$(python3 -c "import time; print(int((time.time()-7200)*1000))")
END=$(python3 -c "import time; print(int(time.time()*1000))")
aws logs filter-log-events \
  --region <region> \
  --log-group-name <log-group> \
  --start-time "$START" --end-time "$END" \
  --filter-pattern "ERROR" \
  --limit 100 --output json
```

Extract sample messages to identify the error signature.

### 3. Count exact error occurrences (last 24–48h)
Once you know the exact error text, count it to judge severity.

```bash
START=$(python3 -c "import time; print(int((time.time()-86400)*1000))")
END=$(python3 -c "import time; print(int(time.time()*1000))")
aws logs filter-log-events \
  --region <region> \
  --log-group-name <log-group> \
  --start-time "$START" --end-time "$END" \
  --filter-pattern '"EXACT ERROR TEXT"' \
  --limit 100 --output json | jq '.events | length'
```

> **Pitfall**: `filter-pattern` rejects colons (`:`) and some special characters in unquoted terms. Always wrap the search phrase in **single-quoted double quotes**: `'"Some error text"'`.

### 4. Historical frequency check (7d and 30d)
```bash
# 7 days
START=$(python3 -c "import time; print(int((time.time()-7*86400)*1000))")
END=$(python3 -c "import time; print(int(time.time()*1000))")
aws logs filter-log-events ... --start-time "$START" --end-time "$END" ... | jq '.events | length'

# 30 days (if signal is sparse)
START=$(python3 -c "import time; print(int((time.time()-30*86400)*1000))")
END=$(python3 -c "import time; print(int(time.time()*1000))")
aws logs filter-log-events ... --start-time "$START" --end-time "$END" ... | jq '.events | length'
```

- If 7d == 0 and today >> 0 → likely new spike.
- If 7d ≈ 30d and low → chronic low-grade issue.
- If 30d shows clusters on specific dates → periodic / batched job side effect.

### 5. Check client-facing impact (5xx)
Find the prod target group name (it may not match the ECS service name exactly):
```bash
aws elbv2 describe-target-groups --region <region> \
  --query 'TargetGroups[*].[TargetGroupName,TargetGroupArn]' --output text | grep <service>
```

Pull target 5xx counts:
```bash
aws cloudwatch get-metric-statistics \
  --region <region> \
  --namespace AWS/ApplicationELB \
  --metric-name HTTPCode_Target_5XX_Count \
  --dimensions Name=TargetGroup,Value=targetgroup/<name>/<suffix> \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 300 --statistics Sum --output json
```

Empty datapoints usually means the error is logged but not returned to clients (internal noise / non-fatal).

### 6. Form a judgment
Map findings into the response framework:

| Evidence | Judgment | Status directive |
|----------|----------|------------------|
| 5xx == 0, low historical count, no recurrence | Spike / monitor | `[[hermes:processing_status=no_action]]` |
| Recurring, no 5xx, fixable in code/config | Needs fix | `[[hermes:processing_status=needs_fix]]` |
| 5xx > 0, rapid increase, data-loss risk, cascading | Urgent | `[[hermes:processing_status=urgent]]` + `@engineers` |

Use `@engineers` only for genuine emergencies (active outage, data loss, severe customer impact, cascading failures).

## Report format
1. **Current judgment**: emergency / needs investigation / spike / monitor
2. **Evidence**: what was checked and what changed
3. **Frequency**: 7-day and 30-day counts with timestamps
4. **Likely root cause**: concise technical explanation
5. **Short-term mitigation**: immediate buffer (restart, scale, suppress if FP)
6. **Long-term fix**: code/config change required
7. **Escalation status**: who should act and when

## Common gotchas
- AWS `filter-log-events` has a 1 MB response limit; use `--next-token` or CloudWatch Logs Insights for very large windows.
- `filter-pattern` silently fails on unquoted special characters. Quote aggressively.
- Target group ARNs need the `targetgroup/<name>/<suffix>` form, not the ECS service name.
- Historical log retention: standard groups keep 2+ weeks, but verify before relying on 30-day checks.
