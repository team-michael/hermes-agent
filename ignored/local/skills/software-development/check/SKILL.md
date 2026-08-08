---
name: check
description: Investigate Notifly Slack/Amazon Q/CloudWatch alerts from live data sources using the bundled deterministic helper, then return one concise Korean triage result.
version: 1.4.6
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

Run the bundled helper before any manual AWS query. Prefer the `sections` format on the first invocation so that `current_error_facts`, `current_trigger_contexts`, and `Logs Insights compact summary` are available; only fall back to `compact-json` when token size requires it.

### Path rule — mandatory

Use the fully resolved absolute path shown for `scripts/collect_notifly_alert_context.py` in this skill's injected `linked_files`/`[Skill directory]` metadata. Copy it verbatim.

Invoke the exact absolute script path copied from the injected metadata:

```bash
python <absolute path to scripts/collect_notifly_alert_context.py> \
  --text '<alert text>' \
  --alarm-name '<exact CloudWatch alarm name>' \
  --region ap-northeast-2 \
  --format sections
```

Rules:

- In a Hermes Slack subscription turn, the helper re-reads the persisted inbound
  alert and treats its exact alarm name as authoritative. If
  `input_integrity.corrected=true`, use `resolved_alarm_name`; do not retry with
  the shortened model-supplied value or replace the helper with manual AWS calls.
- Never construct this path with `~`, `$HOME`, `${HERMES_HOME}`, or by appending `/profiles/<name>`.
- Never run `find /home`, `find ~/.hermes`, `ls`, `grep`, or repeated path guesses after a miss.
- Do not trust a negative filename search by itself; profile skill directories may be symlinks.
- If the absolute invocation fails, inspect that exact path with `stat` or load `scripts/collect_notifly_alert_context.py` through `skill_view` once.
- A missing file and a malformed path are different failures. Report which one occurred.

## One-pass workflow

1. Extract the exact alarm name, region, account, metric/log group, and Slack event timestamp from the supplied alert. If the user supplies a Slack permalink, also read the referenced message/thread with `conversations.replies` using `SLACK_BOT_TOKEN` from the active Hermes environment before claiming the alert context is unavailable.
2. Run the helper once with the exact alarm name when available. Use `--format sections` first and a 35-second terminal timeout. Do not start with `compact-json` unless the response is oversized.
3. Inspect only these result boundaries first:
   - `input_integrity`
   - `can_answer_root_cause`
   - `missing_required_context`
   - `required_followups`
   - `alarm`, `history`, and current alarm window
   - `current_error_facts`, `current_trigger_contexts`, `logs`
   - `logs` → `current_top_signatures` / `current_trigger_contexts` if `current_error_facts` is empty
   - datasource-specific evidence (`rds_performance_insights`, `sqs`, `lambda`, `http`)
   - `hermes_observability` for `HermesServiceHealthy` host alarms
   - `scope_attribution` / `projects`
   - `code`
4. If `can_answer_root_cause: true`, answer immediately **only after** the concrete cause (error signature + throwing stack/function + mechanism) is established. Do not finalize with frequency/status metadata alone.
5. If required context is missing, execute only the listed read-only follow-ups that affect a mandatory final field. Execute no more than two follow-up tool calls.
6. After those two calls, finalize with the strongest available evidence and state any remaining field as unavailable. Do not start another investigation branch.
7. If a datasource is unavailable (`NotAuthorizedException`, expired ECS stream, ingestion lag), mark it unavailable and continue with the strongest remaining evidence. Do not retry the same failed operation with alternate syntax unless the failure explicitly identifies a correctable parameter.
8. Never invent Logs Insights `parse` syntax repeatedly in the model loop. Use a vetted reference or add a deterministic helper collector outside the foreground alert response.

## Manual fallback boundary

Manual fallback is allowed only when the helper itself fails or names a blocking follow-up.

- Use fixed time bounds from CloudWatch `StateReasonData.startDate` / evaluated datapoints, not Slack message time.
- Use structured CLI filters or a small read-only Python probe; do not dump raw logs.
- Parallelize independent AWS reads when a compact probe is genuinely required.
- Stop after the missing final-answer field is filled.
- Never turn one alarm into an open-ended tour of every related AWS service.
- Never use `find /`, recursive searches across multiple workspaces, or unbounded `filter-log-events` pagination.
- Restrict source searches to known repository roots with `rg`, and restrict log reads to the current alarm window unless a listed follow-up explicitly requests an aggregate.

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

If `current_error_facts` and `current_trigger_contexts` are empty for a log-derived ECS alarm, perform one bounded Logs Insights fallback query over the exact alarm window (`logs.current_alarm_window.start` ... `end`) before finalizing. Use only these filter terms:

```sql
fields @timestamp, @message
| filter @message like /ERROR/ or @message like /Exception/
| sort @timestamp desc
| limit 20
```

Then report the exact returned message as the trigger signature in `원인:`. Do not fall back to alarm-frequency metadata when a concrete ERROR line exists.

For structured Sentry alerts, use `current_error_facts` for the issue, message, transaction, request path, project/product slug, and handled status. Use `current_code_locations.page` for the exact Next.js route page. Treat `error_location` as the exact throwing function only when its evidence is `sentry_stack_frame`; `function_candidates` are route-rendered components, not proven throw sites. Preserve `trace_status` so a missing stack frame is reported as unavailable rather than guessed.

### SQS / DLQ

Use queue attributes, redrive policy, event-source mapping, Lambda Errors/Throttles/Duration, and bounded message inspection only when approved and necessary. Remember that `receive_message` changes visibility.

When `dlq_backlog.event_type` is `DLQ_BACKLOG_DETECTED`, use the helper's
`dlq_disposition` as the controlling decision:

- Render only facts in `dlq_disposition.response_facts`; do not add another
  cause, frequency claim, health conclusion, channel subtype, or timestamp
  conversion.
- Report every queue's current live SQS depth and marker depth. The marker is a
  historical trigger snapshot; do not substitute it for current queue state.
  In the extreme compact fallback, zip `response_facts.queue_fields` with each
  array in `response_facts.queues`, then decode short values with
  `response_facts.queue_value_codes`; do not omit any queue.
- If `live_sqs_snapshot_complete` is false, identify each
  `marker_snapshot_fallback` queue and do not call the aggregate a complete
  current snapshot.
- Treat a live non-empty backlog as `needs_fix` even if the log-derived alarm is
  currently `OK`. Only `live_sqs_observed_empty: true`, not an alarm state
  transition, permits the helper's current-snapshot `no_action` disposition.
  SQS counts are approximate; do not claim historical message outcomes.
- Use `hold_for_evidence` until message outcome and replay side-effect safety
  are confirmed.
- Treat each queue's `recovery_decision` independently. `redrive_candidate` or
  `purge_candidate` is a recommendation candidate, never mutation approval.
- A technically configured redrive path, an old-message age, or an `Enabled`
  mapping is not replay-safety or obsolescence evidence.
- Report source queues and consumers when the helper resolved them. An empty
  Lambda mapping does not prove that no polling consumer exists.
- Customer impact is `미확인` unless delivery outcome evidence proves impact
  or proves that processing completed safely.
- State only the confirmed backlog as the cause. Do not invent why the messages
  reached the DLQ, call them stale, or translate queue names into an unsupported
  product/channel subtype.
- `receive_message` and payload inspection change message visibility. Never
  describe them as read-only; require explicit approval before using them.
- Report inspection-Lambda metric values only when present. Do not call
  duration "normal" without an explicit baseline or threshold.
- An event-source mapping state of `Enabled` confirms wiring only, not consumer
  runtime health.
- `recurrence_sample` is bounded sample evidence. Never call it complete
  7-day history, call the sample-window span a persistence duration, or say
  every sample is consecutive. Use its provided KST timestamps verbatim and
  state that continuity is unconfirmed.
- Render `frequency_summary_ko` verbatim; do not derive a duration from hidden
  or neighboring timestamps.
- Do not assign an owner unless `response_facts` provides one.
- Use `immediate_action_label_ko` and `immediate_action_reason_ko` verbatim.
  Queue depth alone is not an urgency threshold. If `action_owner` is
  `unconfirmed`, omit the owner instead of inventing a team or role.
- Consumer runtime metrics are not in DLQ `response_facts`. Do not transfer the
  monitoring Lambda's Errors/Throttles/Duration to the queue consumer.
- Output Korean only except for exact technical identifiers.
- Never recommend or perform redrive, purge, delete, or stream replay while the
  disposition is `hold_for_evidence`.

### Lambda

Resolve the real function name rather than assuming the alarm prefix equals it. Cross-check runtime Errors/Throttles/Duration. A `REPORT ... Status: timeout` may exist without an ERROR log line.

### HTTP 4xx/5xx

Verify the namespace first. A `ConsoleErrors` log-derived 4xx alarm is not automatically an ALB/API Gateway metric. Distinguish handled client/business rejection from service failure.

### Hermes Agent host health

When `MetricName` is `HermesServiceHealthy`, use the helper's
`hermes_observability` result instead of stopping at the instance-level gauge:

- Use `alarm_trigger` to distinguish an observed unhealthy gauge from a
  `TreatMissingData=breaching` transition with no observed breaching value.
- Use `report_facts.parent_session` and `report_facts.active_session` verbatim
  as `@session:<profile>/<full-id>` links. Never report only the 12-character
  collector prefix when the helper resolved a full session.
- Under the `원인` bullet, include nested evidence lines for the parent session,
  directly active subagent/session, task excerpt, tool start/end time, tool
  batch summary, pressure-open read rate, and recovery time when present.
- For `execute_code`, render `batch_item_count`, `operations`, and
  `execution_mode` from the helper. Do not inspect or quote the raw code in the
  Slack response.
- Include `related_same_parent_incidents` when the same parent caused another
  pressure/recovery cycle in the alarm cluster.
- Preserve the helper's attribution boundary: the active session/tool is
  correlated with profile-level cgroup IO; bytes are not metered per process.
  Say `직접 실행 중이던 session/tool` rather than claiming byte-perfect process
  accounting.
- If session attribution is unavailable, say so. Do not guess a full ID or use
  archived session replay as evidence.

## Slack response contract

For subscription alerts:

- Call the `terminal` tool with the helper command first. Do not output the command as a Slack code block; do not describe what you will do before doing it. The only valid final response is the Korean triage bullets below plus the status directive.
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

### Cause-first requirement

The `원인:` bullet must contain the exact trigger signature when one exists. It is not acceptable to lead with the alarm name, metric namespace, or a generic service description when a concrete log line, SQL error, or exception message has been observed.

Required order inside `원인:`:
1. Exact error signature / message / exception class from the current alarm window.
2. Immediate mechanism in plain language (which code path, external provider, validation rule, etc.).
3. Throwing function, repository file, or SQL fingerprint when visible.
4. Only if none of the above are available: state that the concrete signature is unavailable and what was checked instead.

Frequency and alarm metadata belong in the `빈도:` bullet, never in place of the concrete cause.

**Common failure mode**: treating "concise" as "omit the concrete error message". Concise means removing filler, not removing the trigger signature. The user asks "what error" exactly because the metric name (e.g. `/aws/ecs/.../web-console console error`) is not informative. Always answer that question with the real log line first, then summarize scope/frequency/impact.

### Two-step fallback for empty helper signatures

If `current_error_facts` and `current_trigger_contexts` are empty for a log-derived alarm, the final response is not allowed until one of the following succeeds:
1. A bounded Logs Insights query over the exact alarm window returns one or more ERROR/Exception lines. Report the exact returned message(s).
2. A `filter-log-events` call over the exact alarm window returns one or more ERROR/Exception lines. Report the exact returned message(s).
3. Both fail due to ingestion lag or authorization. In that case the `원인:` bullet must explicitly say the concrete signature could not be retrieved and name the fallback that was attempted.

Never answer with only frequency, alarm state, or a generic service description when the alarm has a concrete log-derived cause.

### Verification gate before responding

Before emitting the final Slack response, perform this self-check against the draft `원인:` bullet:

1. Does it start with an exact error string, exception class, SQL error, or validation message from the **current alarm window**?
2. Are the following high-signal fields preserved unless truly unavailable?
   - exact error message / constraint name / table name
   - row count / affected records
   - Lambda duration / HTTP status / request ID
   - project ID / product slug
   - campaign ID when visible in the trigger event
3. Is the `빈도:` bullet the only place that contains alarm counts/state transitions?
4. If the concrete signature is "unavailable", does the `원인:` bullet explicitly say which fallback was attempted and why it failed?

If any check fails, do not emit the response. Re-run the appropriate fallback or add an explicit "signature unavailable" note.

When a concrete signature is present, the `원인:` bullet must take one of these shapes:
- `ECS/Lambda: <service> <timestamp> <log stream> <exact ERROR line>`
- `DB: <table/constraint> <exact SQL error> <affected rows>`
- `External API: <provider> <exact rejection message> <request path>`
- `Timeout: <function> REPORT Duration: <value> ms Status: timeout`

Then add one plain-language sentence of mechanism, not before.

For `HermesServiceHealthy`, the `원인` item may contain the nested session and
pressure evidence required by the Hermes Agent host-health rules above. Keep
the same five top-level bullets; nested evidence lines do not add new top-level
fields.

Add `- 액션 아이템:` only for `needs_fix` or `urgent`, and name a concrete
code/SQL/Terraform target. Include an owner only when the relevant response
facts provide a confirmed owner.

Status directive:

- `[[hermes:processing_status=no_action]]`: recovered/known benign pattern, expected rejection, false positive, or no immediate owner action.
- `[[hermes:processing_status=needs_fix]]`: real non-urgent engineering work should be tracked now.
- `[[hermes:processing_status=urgent]]`: immediate outage, customer impact, data-loss risk, cascading failure, or runaway cost/load.

A `no_action` answer has exactly five visible bullets and no `액션 아이템:` line.

## Slack permalink handling

If the user provides a Slack permalink to an alert or thread, read it via Slack API (`conversations.replies` for threads, `conversations.history` for single messages) using the environment's `SLACK_BOT_TOKEN` before invoking the helper. Parse the CloudWatch alarm name and timestamp from the retrieved message and treat them as authoritative. Do not tell the user that you cannot read Slack links when the token is present.

## Safety

- AWS and databases are read-only for investigation.
- Never print credentials, raw sender credentials, recipient/device payloads, or full sensitive logs.
- Do not fetch complete DynamoDB project items.
- Do not requeue, resend, redrive, delete, purge, or mutate infrastructure without explicit approval.
- Preserve evidence before recommending remediation.

## Improvement discipline

Do not modify skills or write one-off production scripts during the foreground alert turn. Finish the user response first. Afterward, only add a reusable bounded collector when a deterministic gap was actually observed and a focused regression test exists. Prefer helper code and references over growing this orchestrator.

## Known improvements

- `v1.4.6`: `HermesServiceHealthy` collection resolves profile-pressure events
  to full parent/subagent session links, active tool intervals, bounded task
  excerpts, sequential `execute_code` batch size, read rate, and recovery time.
  The Slack contract renders these as nested cause evidence while preserving
  profile-cgroup versus process-level attribution boundaries.
- `v1.4.4`: DLQ compact facts provide one safe frequency sentence and omit
  monitoring-Lambda metrics that the model previously attributed to consumers.
- `v1.4.3`: DLQ response facts precompute the immediate-action label and block
  low-depth severity downgrades or invented owners observed in live responses.
- `v1.4.2`: DLQ disposition reconciles the trigger marker with current SQS
  approximate attributes. Slack responses use the latest observed depth,
  retain marker depth for history, and report `no_action` only when every
  affected queue is observed empty in the current snapshot.
- `v1.4.1`: DLQ output separates technical redrive capability from replay
  safety and emits a queue-local recovery decision. Redrive requires a
  transient failure plus idempotent replay; purge requires a terminal or
  permanent failure plus confirmed obsolescence. Both require preserved
  evidence and remain non-mutating recommendations.
- `v1.4.0`: structured DLQ backlog markers are parsed before sanitization,
  affected queues feed the read-only SQS/source-consumer collector, and the
  helper emits a deterministic `needs_fix / hold_for_evidence` disposition
  that does not treat an alarm `OK` transition as backlog resolution.
- `v1.3.3`: compact helper output is capped at 10 KB, missing required
  context cannot be marked answerable, and automated alert turns are bounded
  to the helper plus at most two follow-up tool calls.
- `v1.3.1`: sharded table references (`table_refs`) feed their `project_id`
  into DynamoDB project mapping so scope attribution can resolve projects
  already identified in logs.
|
|## Known improvements (v1.3.2)
|
|- `detect.py`: added `detect_payment_product_names()` to extract customer/product names from payment-executor log lines (e.g. `payment for HONGIN`, `payment for choihome`).
- `scope.py`/`cli.py`: `merge_scope_detections` now returns `payment_product_names`; `detected` and helper JSON include this list so SKILL responses can attach product scope to payment alarms.
- `logs.py`: `collect_surrounding_log_contexts` takes an optional `payment_mode` flag and fetches ±25/15 seconds of log context instead of ±5/5 when payment-executor is detected, improving capture of `Payment details` arrays containing `project_id`.
