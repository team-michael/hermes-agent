---
name: check
description: Investigate Notifly Slack/Amazon Q/CloudWatch alerts from live data sources using the bundled deterministic helper, then return one concise Korean triage result.
version: 1.3.2
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [notifly, alerts, cloudwatch, aws, dynamodb, github, postgres, slack, investigation]
---

# Notifly Alert Check

Use this for Slack/Amazon Q/CloudWatch alerts, alarm names, CloudWatch log links, and Redis/SQS/RDS/ECS/Lambda error snippets.

This is a **helper-first, bounded investigation**. Do not replay archived Hermes sessions as evidence and do not reconstruct helper-covered AWS queries manually.

## Critical fast path

Run the bundled helper before any manual AWS query.

### Path rule — mandatory

Use the fully resolved absolute path shown for `scripts/collect_notifly_alert_context.py` in this skill's injected `linked_files`/`[Skill directory]` metadata. Copy it verbatim.

Invoke the exact absolute script path copied from the injected metadata:

```bash
python <absolute path to scripts/collect_notifly_alert_context.py> \
  --text '<alert text>' \
  --alarm-name '<exact CloudWatch alarm name>' \
  --region ap-northeast-2 \
  --format compact-json
```

Rules:

- Never construct this path with `~`, `$HOME`, `${HERMES_HOME}`, or by appending `/profiles/<name>`.
- Never run `find /home`, `find ~/.hermes`, `ls`, `grep`, or repeated path guesses after a miss.
- Do not trust a negative filename search by itself; profile skill directories may be symlinks.
- If the absolute invocation fails, inspect that exact path with `stat` or load `scripts/collect_notifly_alert_context.py` through `skill_view` once.
- A missing file and a malformed path are different failures. Report which one occurred.

## One-pass workflow

1. Extract the exact alarm name, region, account, metric/log group, and Slack event timestamp from the supplied alert.
2. Run the helper once with the exact alarm name when available. Use a 120-second terminal timeout.
3. Inspect only these result boundaries first:
   - `can_answer_root_cause`
   - `missing_required_context`
   - `required_followups`
   - `alarm`, `history`, and current alarm window
   - datasource-specific evidence (`logs`, `rds_performance_insights`, `sqs`, `lambda`, `http`)
   - `scope_attribution` / `projects`
   - `code`
4. If `can_answer_root_cause: true`, answer immediately. Do not repeat helper-covered CloudWatch, RDS, PI, Logs Insights, SQS, Lambda, DynamoDB, or source queries.
5. If required context is missing, execute only the listed read-only follow-ups that affect a mandatory final field. Prefer at most two bounded follow-up calls.
6. If a datasource is unavailable (`NotAuthorizedException`, expired ECS stream, ingestion lag), mark it unavailable and continue with the strongest remaining evidence. Do not retry the same failed operation with alternate syntax unless the failure explicitly identifies a correctable parameter.
7. Never invent Logs Insights `parse` syntax repeatedly in the model loop. Use a vetted reference or add a deterministic helper collector outside the foreground alert response.

## Manual fallback boundary

Manual fallback is allowed only when the helper itself fails or names a blocking follow-up.

- Use fixed time bounds from CloudWatch `StateReasonData.startDate` / evaluated datapoints, not Slack message time.
- Use structured CLI filters or a small read-only Python probe; do not dump raw logs.
- Parallelize independent AWS reads when a compact probe is genuinely required.
- Stop after the missing final-answer field is filled.
- Never turn one alarm into an open-ended tour of every related AWS service.

Useful references, loaded only when the alarm shape matches:

- `references/helper-script-path-resolution.md`
- `references/ecs-log-manual-trace.md`
- `references/aurora-volume-read-iops-batch-workload.md`
- `references/sqs-dlq-alarm-triage.md`
- `references/sqs-lambda-throughput-bottleneck.md`
- `references/lambda-timeout-empty-log-gap.md`
- `references/rds-aurora-replica-recovery-conflict.md`
- `references/cloudflare-workers-ai-status-check.md`

Load one relevant reference with `skill_view(name="check", file_path="references/<file>.md")`; do not load the whole reference library.

## Evidence rules

- Current breaching-datapoint evidence outranks 7d/30d historical signatures.
- Observed facts, interpretation, and speculation must remain distinct.
- Alarm names are labels; verify the live threshold, period, evaluation periods, datapoints-to-alarm, dimensions, and current state.
- For log-derived alarms, identify the concrete trigger from the exact alarm window. Historical top signatures are baseline only.
- For DB alerts, name the concrete instance/role and top SQL fingerprint from Performance Insights, DB logs, or a clearly labeled fallback. Map sharded table suffixes to project/product.
- If a source is unavailable, say so; do not imply it was checked.
- Do not infer customer impact from metric breach alone. Check delivery failures, queue growth, latency, errors, data loss, or completed work as appropriate.

## Scope attribution

Every final answer must provide scope without forcing unsupported precision.

Resolve in this order:

1. IDs in the exact trigger payload/log/table/SQL.
2. Helper `scope_attribution` and current-window project/campaign pairs.
3. DynamoDB `project` mapping for every discovered `project_id`, projecting only `id`, `product_id`, and `name`.
4. Read-only Postgres/Athena lookup only when campaign or user-journey attribution is a blocking final field.
5. If no per-project evidence exists for a shared infrastructure signal, say `서비스/인프라 공통 범위` and mark campaign/user journey unknown. Do not force a project.

Campaign and user journey are mutually exclusive in the final scope field. Pair campaign IDs with their owning project when known.

## Alarm-family routing

### RDS / Aurora

Use helper alarm metadata, metric datapoints, topology, and Performance Insights. Report writer/reader role, current-focus top SQL, mapped project/product, latency/capacity headroom, and recurrence. If PI is unavailable, use only a documented bounded fallback reference.

### ECS / log-derived alarms

Use the metric filter and exact current alarm-window trigger. Do not substitute a historical signature when current trigger evidence is missing. Load the specific matching reference only after identifying the trigger family.

### SQS / DLQ

Use queue attributes, redrive policy, event-source mapping, Lambda Errors/Throttles/Duration, and bounded message inspection only when approved and necessary. Remember that `receive_message` changes visibility.

### Lambda

Resolve the real function name rather than assuming the alarm prefix equals it. Cross-check runtime Errors/Throttles/Duration. A `REPORT ... Status: timeout` may exist without an ERROR log line.

### HTTP 4xx/5xx

Verify the namespace first. A `ConsoleErrors` log-derived 4xx alarm is not automatically an ALB/API Gateway metric. Distinguish handled client/business rejection from service failure.

## Slack response contract

For subscription alerts:

- Execute silently and return exactly one final assistant response; do not call `send_message`.
- Korean only.
- No acknowledgement, progress report, investigation diary, internal draft, or reasoning text.
- Use short Markdown bullets, not prose paragraphs.
- Convert user-facing timestamps to KST.
- Preserve complete stable identifiers; remove prose before abbreviating IDs.
- Mention `@engineers` only for a genuine urgent incident.
- End with exactly one hidden processing directive.

Visible format, in this exact order:

```text
- 원인: <system cause + strongest implementation/SQL evidence>
- 범위: <project/product + exactly one of campaign or user journey, or infra-wide unknown>
- 빈도: <30일 / 7일 / 1일 / 10분>
- 고객 영향도: <failure/delay/data-loss/no-impact evidence>
- 즉시 조치 필요 여부: <필요|불필요|추적 필요 + reason>
```

Add `- 액션 아이템:` only for `needs_fix` or `urgent`, and name a concrete code/SQL/Terraform/owner target.

Status directive:

- `[[hermes:processing_status=no_action]]`: recovered/known benign pattern, expected rejection, false positive, or no immediate owner action.
- `[[hermes:processing_status=needs_fix]]`: real non-urgent engineering work should be tracked now.
- `[[hermes:processing_status=urgent]]`: immediate outage, customer impact, data-loss risk, cascading failure, or runaway cost/load.

A `no_action` answer has exactly five visible bullets and no `액션 아이템:` line.

## Safety

- AWS and databases are read-only for investigation.
- Never print credentials, raw sender credentials, recipient/device payloads, or full sensitive logs.
- Do not fetch complete DynamoDB project items.
- Do not requeue, resend, redrive, delete, purge, or mutate infrastructure without explicit approval.
- Preserve evidence before recommending remediation.

## Improvement discipline

Do not modify skills or write one-off production scripts during the foreground alert turn. Finish the user response first. Afterward, only add a reusable bounded collector when a deterministic gap was actually observed and a focused regression test exists. Prefer helper code and references over growing this orchestrator.

|## Known improvements (v1.3.1)
|
|- `logs.py`: sharded table references (`table_refs`) now feed their `project_id` into the `project_ids` used for DynamoDB project mapping. Previously, table suffixes like `user_journey_sessions_031b18009978590188e49e6777447fc2` were captured as `table_refs` but never promoted to `project_ids`, causing `scope_attribution.projects` to return `null` even when the project ID was clearly present in the logs. The fix extracts `project_id` from `table_refs` at three points: (1) `current_error_details_from_contexts` concrete-trigger branch, (2) `current_error_details_from_contexts` normal branch, and (3) `collect_logs_insights_summary` current-row scope detection.
|
|## Known improvements (v1.3.2)
|
|- `detect.py`: added `detect_payment_product_names()` to extract customer/product names from payment-executor log lines (e.g. `payment for HONGIN`, `payment for choihome`).
- `scope.py`/`cli.py`: `merge_scope_detections` now returns `payment_product_names`; `detected` and helper JSON include this list so SKILL responses can attach product scope to payment alarms.
- `logs.py`: `collect_surrounding_log_contexts` takes an optional `payment_mode` flag and fetches ±25/15 seconds of log context instead of ±5/5 when payment-executor is detected, improving capture of `Payment details` arrays containing `project_id`.
