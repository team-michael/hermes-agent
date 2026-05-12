---
name: check
description: Investigate Notifly Slack/Amazon Q/CloudWatch alerts from live data sources using Hermes profile/global .env-backed AWS, GitHub, Postgres, DynamoDB, and Athena credentials. Start from pasted alert text or Slack subscription context, recover alarm/log context, and produce one concise Korean final answer.
version: 1.2.2
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [notifly, alerts, cloudwatch, aws, dynamodb, github, postgres, slack, investigation]
---

# Notifly Alert Check

Use this when the user pastes or a Slack message subscription delivers:
- a Slack thread root from Amazon Q / AWS Chatbot
- a CloudWatch alarm name
- a CloudWatch Logs URL or log group
- a Redis / SQS / RDS / segment-publisher error snippet

and wants the **same live investigation pattern** used in prior Notifly sessions.

This skill is **not** about replaying old Hermes session archives.
It is about using **live data sources** via credentials in the current Hermes profile `.env`, then global `~/.hermes/.env`.

## Automated Slack alert contract

When this skill is invoked by a Slack `message_subscriptions` prompt, operate silently until the investigation is complete.

Final response rules:
- Post exactly one final message; no acknowledgement or progress messages.
- Do not call `send_message` for Slack subscription alerts. Return the final answer as the assistant's final response so the gateway posts it back to the originating Slack thread.
- Never use bare `slack` or `slack:<channel_id>` as a fallback target for subscription alert results; that posts to the channel main timeline and breaks alert threading.
- Korean only. Use the fixed concise list format below; alert context completeness has priority over length.
- Helper/script timestamps remain UTC/ISO internally. In the final Slack/user-facing message only, convert every timestamp to KST (`YYYY-MM-DD HH:mm KST` or `M/D HH:mm KST`). Do not expose UTC as the primary time.
- If needed, slightly exceed the target length or bullet count to include the mandatory context. Do not omit important context just to satisfy the short format.
- Prioritize the fixed labels, mandatory scope attribution, alert metric/threshold context, DB instance/query context when DB-shaped, strongest evidence, 30d/7d/1d/10m trend, customer impact, and immediate action decision.
- Never abbreviate stable identifiers in the final Korean answer. Do not use ellipses for project IDs, product/project names, campaign IDs, user journey IDs, table names, constraint names, file paths, function names, alarm names, or log groups. If space is tight, remove prose first and keep identifiers complete.
- If a helper sample line already contains `...`, do not copy that truncated sample into the final answer. Use structured full fields such as `logs.current_error_details[].project_ids`, `table_names`, `table_refs`, `projects`, and `scope_attribution` instead.
- For log-derived alarms, the strongest evidence is the current alarm-window error detail, not the alarm name or frequency. If `logs.current_error_details` exists, the final Korean answer must describe the concrete triggering error from that field before discussing 7d/30d frequency or threshold sensitivity.
- Always include one compact Korean scope field that names the related project/product and exactly one of campaign or user journey. Campaign and user journey are mutually exclusive: if campaign evidence exists, do not also print an unknown user-journey value; if neither can be tied to the alert after reasonable checks, explicitly say in Korean that campaign/user journey is unknown. If the alert is service/infra-wide, say so in Korean.
- Campaigns are project-scoped. Never list campaign IDs as a standalone flat list when a project can be known. Prefer `project/campaign` pairs such as `fitpet/Zxj6Nx`; if only a campaign ID is known, say in Korean that the project is unknown for that campaign.
- For DB-shaped alerts, always include one compact Korean DB field naming the concrete DB instance/role and top SQL family/query fingerprint. If unavailable, say in Korean that the instance or query is unknown with the shortest reason.
- For `needs_fix` or `urgent`, the implementation target must be concrete somewhere in the fixed labels: file/module/function, SQL/index/table family, or Terraform path/resource. Avoid generic advice like "threshold review" unless paired with the exact Terraform alarm/config location to change.
- If immediate action is not required, do not print `액션 아이템:`; put the concrete non-urgent target briefly in `즉시 조치 필요 여부: 추적 필요 ...`.
**Pitfall**: before finalizing a `no_action` response, count visible bullets. It must be exactly five labels (`원인`, `범위`, `빈도`, `고객 영향도`, `즉시 조치 필요 여부`). Including `액션 아이템:` under `no_action` breaks the Slack reaction contract and inflates perceived severity.
- If the exact code or Terraform location is not found, write the most specific next lookup target instead of a generic action target.
- Mention `@engineers` only for urgent issues requiring immediate engineering response.
- End with exactly one hidden directive: `[[hermes:processing_status=no_action]]`, `[[hermes:processing_status=needs_fix]]`, or `[[hermes:processing_status=urgent]]`.

Final answer format:
- Use short Markdown bullet lines, not paragraph prose.
- Each visible line must start with `- <label>`.
- Use five visible bullets by default; add the sixth `액션 아이템:` bullet only when immediate action is needed.
- Use exactly these Korean labels, in this order:
  - `원인:` alarm-triggering system-level cause plus code-level cause. Include both in one compact line; if one is unknown, say why briefly.
  - `범위:` project/product plus exactly one of campaign or user journey. Campaign and user journey are mutually exclusive.
  - `빈도:` recent `30일 / 7일 / 1일 / 10분` occurrence counts. Prefer alert transition counts from `history.alarm_count_30d`, `history.alarm_count_7d`, `history.alarm_count_1d`, and `history.alarm_count_10m`; use log-event counts only when alert history is unavailable or the user explicitly asks for log volume. If any window is unavailable, mark only that window as `확인 불가(<short reason>)`.
  - `고객 영향도:` concrete customer-facing impact, data loss/delay/failure/noise status, and whether users/customers were likely affected.
  - `즉시 조치 필요 여부:` `필요`, `불필요`, or `추적 필요` plus the shortest reason.
  - `액션 아이템:` include this line only when immediate action is needed. Name the exact owner-facing implementation or infrastructure target.
- Do not add separate `판단`, `근거`, `조치`, `현재 상태`, or narrative summary labels.
- Keep each label to one line unless a single line would hide mandatory identifiers.

Status selection:
- `no_action`: false positive, already recovered transient spike, known issue within the recent baseline, expected business rejection, noisy metric filter, or any case where no immediate owner action is required. Use this even when the final answer includes a later improvement suggestion, if the current alert is benign or already understood.
- `needs_fix`: non-urgent but actionable engineering work should be tracked now because the signal is new, worsening, outside baseline, causing real failed work, repeated customer impact, data-loss risk, runaway cost/load, or materially harmful alert noise. Do not use `needs_fix` merely because a code/config/threshold improvement is possible someday.
- `urgent`: immediate customer impact, data loss risk, sustained outage, runaway cost/load, or failed critical dependency.

Known-issue rule:
- If the alert matches a known recurring pattern, is already recovered or within baseline, and does not require immediate mitigation, choose `no_action` so Slack gets the checkmark reaction.
- Escalate from `no_action` to `needs_fix` only when the recurrence is increasing, the root cause is not understood, the alert creates real operational burden that should be scheduled now, or there is evidence of failed customer-facing work.
- If `history.rapid_recurrence.status` is `rapid` or there are two or more ALARM transitions within 10 minutes, investigate more deeply before deciding. Do not dismiss it as routine solely because 7d/30d history is recurring; cite the rapid recurrence and use `needs_fix` unless current load, impact, and dominant source are clearly benign.

## Live data sources

Backed by env credentials already present in this environment:
- AWS: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`
- GitHub: `GITHUB_TOKEN`
- Postgres: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- DynamoDB `project` table via AWS creds
- Athena via AWS creds when log/query history is in Athena

## Core pattern learned from prior sessions

The recurring investigation flow is:

1. **Start from the pasted alert text or Slack channel ID**
   - extract alarm name, region, log group, service name, queue name, project IDs, error phrases
   - if the user gives a Slack channel ID and asks about Amazon Q / AWS Chatbot messages, use `chatbot.describe_slack_channel_configurations` in `us-west-2` to map `SlackChannelId -> SnsTopicArns`; then inspect CloudWatch alarms whose `AlarmActions`/`OKActions` include those SNS topics. This reconstructs recent Amazon Q alert messages without needing Slack history access.

2. **Use AWS first, not guesswork**
   - `describe_alarms`
   - `describe_alarm_history`
   - CloudWatch metric datapoints
   - Logs Insights / metric filters
   - RDS / Performance Insights / SQS / SNS / CloudTrail as needed

3. **If a project_id appears, always map it to product**
   - DynamoDB `project` table
   - return `project_id + product_id + project.name`
   - Postgres tables follow `table_$project_id`; use this naming convention when checking campaign/user_journey evidence.

4. **If the user asks when the issue started or which change caused it**
   - find earliest retained log evidence first
   - then correlate to local git history / GitHub PRs with `GITHUB_TOKEN`

5. **If the alert is DB-shaped**
   - separate alarm sensitivity from actual workload
   - identify writer vs reader
   - identify the exact DB instance and role
   - identify the SQL family/query fingerprint from Performance Insights or DB logs, not just the metric name

6. **If the alert is log-shaped**
   - inspect metric filter breadth first
   - inspect notification routing drift (SNS subscribers / CloudTrail) if alert volume changed

## Mandatory scope attribution

Every investigation must identify which project and which single campaign or user journey the alert is related to, or explicitly say why that scope is not available.

Resolve scope in this order:
1. Use IDs present in the alert text, alarm dimensions, log signatures, payload samples, table names, or helper output (`project_id`, `campaign_id`, `user_journey_id`, schedule IDs, journey session IDs).
2. Map every `project_id` through DynamoDB `project` and report the product/name mapping, not just the raw ID.
   - If mapping fails or the item is missing, report the full `project_id` and the exact failure reason from `projects[].mapping_failure_reason` or `scope_attribution.project_mapping_failures`.
3. For campaign or user_journey IDs, use read-only DynamoDB/Postgres/Athena lookups to map names and owning project/product when available.
4. For Postgres table names, infer project from the `table_$project_id` suffix and then map that project.
5. For log lines containing both `Project Id` and `Campaign Id`, treat the pair as the primary campaign scope. Current alarm-window pairs outrank 7d/30d historical signatures.
   - Also treat log-style `campaign_id: <id>, project_id: <id>` and `project_id: <id>, campaign_id: <id>` as primary project/campaign pairs.
   - Also treat compact ECS log lines such as `campaignId: UL1T00` (with or without accompanying `projectId`) as primary scope evidence when they appear in the current alarm-window stream.
   - Never combine a standalone campaign ID with an unrelated sharded table suffix from another log line. IDs from `relation "<table>_<project_id>" does not exist` are table references, not campaign ownership evidence, unless that table error is the actual current trigger and no stronger project/campaign pair exists.
6. For DB alerts, Performance Insights SQL statements are scope evidence: `event_intermediate_counts_$project_id`, `users_$project_id`, `delivery_result_$project_id`, `message_events_$project_id`, etc. mean the project is known and must not be reported as unknown.
7. For campaign/user_journey scope, first check whether the SQL/table family can carry `campaign_id`, `resource_type`, or `user_journey_id`. If yes, run a read-only aggregate around the alarm/PI window to find the top campaign or user-journey contributor. If campaign evidence exists, stop there and do not also report user journey. If not available because the query is parameterized or the table family has no campaign/user_journey column, say that specific reason.
8. For service-wide, Lambda/ECS, RDS, SQS, Redis, or broad metric-filter alerts with no per-project evidence, state in Korean that the project and campaign/user journey are unknown, and add a Korean service-wide or infra-wide marker when that is the correct scope.
   - For shared-pipeline SQS queues (e.g., `kinesis-record-dispatcher-queue`) where messages aggregate records from all projects, the Lambda consumer logs typically contain only `START/END/REPORT` lines with no per-project IDs. Do not force a project scope; explicitly say the scope is infra-wide common pipeline delay.

Do not omit scope to stay under the target length. Compress wording first; if still necessary, exceed the target length.

## Important tool discipline

### One-pass first
For automated Slack alerts, run the helper first and treat its compact JSON as the primary evidence bundle.
Do not manually repeat helper-covered steps unless the helper explicitly reports missing data or an error.

The helper is expected to collect in one terminal call:
- answerability fields: `can_answer_root_cause`, `missing_required_context`, and `required_followups`
- CloudWatch alarm metadata and alarm history
- 7d/30d alarm transition counts
- metric filter configuration
- vetted Logs Insights 7d/30d counts
- top 5 sanitized log signatures with at most 3 sample lines each
- current-alarm-window signatures, trigger-centered sanitized log contexts, and compact concrete error details (`logs.current_top_signatures`, `logs.current_trigger_contexts`, `logs.current_error_details`) for log-derived alarms
- HTTP 4xx/5xx metric context when the alarm namespace/dimensions support it
- SQS/DLQ queue attributes, redrive source hints, and safe queue metrics when relevant
- Lambda configuration, event sources, async destination/retry config, and error/throttle/duration metrics when relevant
- RDS topology when relevant
- RDS Performance Insights top SQL by instance when relevant
- RDS current alarm focus-window project attribution (`rds_performance_insights.detected_scope_ids.current_top_projects_by_load`) when relevant
- project IDs inferred from RDS Performance Insights sharded table suffixes before SQL sanitization
- project mapping from DynamoDB when `project_id` is present
- project plus campaign-or-user_journey attribution, including explicit Korean unknown values when no specific scope is supported
- project-campaign pairs from logs (`logs.current_project_campaign_pairs`) when the current alarm-window payload contains both IDs
- campaign/user-journey narrowing hints from log payload IDs and campaign-capable table families
- related implementation and Terraform source locations with only 30-50 nearby lines for the top matches

Helper collectors must be selected from CloudWatch alarm metadata, metric namespace/name, dimensions, metric filters, and log group shape. Do not add service-name-specific branches for individual ECS services or alarm names; add generic namespace/metric/dimension collectors instead.
When a reusable collection step is needed, add it as a bounded collector in `scripts/notifly_alert_context/collectors.py` and keep pattern constants in `scripts/notifly_alert_context/config.py` so new monitoring patterns do not require CLI orchestration changes.

### Prefer `terminal` + Python for AWS
Do not rely on `execute_code` for AWS calls when credentials may only exist in shell env.

Use:
- `terminal("python - <<'PY' ... PY")`
- explicit `boto3.Session(...)` from env vars

When the helper skips Logs Insights despite a clear metric filter (e.g., `filter_pattern` is present but `logs.skipped` says "no stable filter terms inferred"), fall back to the bounded manual trace in `references/ecs-log-manual-trace.md`.

### Safe defaults
- AWS: read-only
- Postgres: read-only
- never print secrets or full sensitive payloads
- avoid dumping raw `Received event:` logs if they contain sender credentials
- never print raw CloudWatch log dumps; use signature counts and sanitized samples only
- never paste full `_aws` metric JSON, access logs, or full event payloads into the conversation
- for source search, avoid broad file reads and AGENTS/SOUL/session context; read only the relevant function/file area when the helper result is insufficient
- when the action is alarm/threshold/routing/config related, search Terraform under `infra/terraform` and name the exact resource/path when found

## Fast path helper

Use the helper script first when the user gives pasted alert text. Its default output is compact JSON designed to keep the prompt small:

```bash
python "${HERMES_HOME:-$HOME/.hermes}/skills/software-development/check/scripts/collect_notifly_alert_context.py" \
  --text 'Amazon Q: CloudWatch Alarm | notifly-db-prod-cluster CPUUtilization too high | ap-northeast-2 | Account: 702197142747'
```

Or with a file:

```bash
python "${HERMES_HOME:-$HOME/.hermes}/skills/software-development/check/scripts/collect_notifly_alert_context.py" \
  --text-file /tmp/alert.txt
```

If the helper fails to parse the alarm name from free-form text (`detected.alarm_name` is null), pass it explicitly:

```bash
python "${HERMES_HOME:-$HOME/.hermes}/skills/software-development/check/scripts/collect_notifly_alert_context.py" \
  --text 'segment-publisher slow eic query' \
  --alarm-name '/aws/ecs/notifly-services-prod/segment-publisher slow eic query' \
  --region ap-northeast-2
```

**Pitfall**: alarm names with embedded priority tiers (e.g., `ScheduledBatchDelivery-P2-FCMLatencyP99`) may not be detected by the text parser. Pass `--alarm-name` explicitly in these cases.

**Pitfall — DLQ creation alarm names**: alarm names matching the literal pattern `<queue-name>-dlq has been created` are not auto-detected because `has been created` is prose, not a metric. Pass `--alarm-name` explicitly, e.g. `--alarm-name 'kinesis-record-dispatcher-queue-dlq has been created'`.

**Pitfall — log-group prefix conflation in alarm name detection**: The text parser may prepend `/aws/ecs/.../` log-group prefixes to the auto-detected alarm name, or it may strip an existing prefix and return a bare name. If `describe_alarms` returns no metadata for a detected name but the alarm is known to exist, try the opposite form: prepend the full log group prefix (`/aws/ecs/notifly-services-prod/<name>`) to a bare detected name, or try the bare alarm name without the prefix.

**Pitfall**: When a metric filter pattern (e.g., `took too long`) differs materially from the alarm or metric name (e.g., `segment-publisher-prod slow eic query`), the helper may derive Logs Insights filter terms from the name and report `count_7d: 0` / `count_30d: 0` despite actual matches existing. Do not treat zero counts as absence of logs; fall back to the bounded manual trace using the exact `filter_pattern` string from `metric_filters[].filter_pattern`.

**Pitfall — `segment-publisher slow eic query` helper false-negative:** The helper frequently returns `can_answer_root_cause: false` for this alarm because its term extractor derives `slow eic query` from the alarm name instead of the actual metric filter pattern `took too long`. When this happens, bypass the generic `required_followups` and immediately run the bounded manual trace using `"took" "too" "long"` (three separate terms) plus a stream-first tail check. See `references/segment-publisher-slow-eic-query-noise.md` for exact fallback commands and Pattern A vs Pattern B triage.

**Pitfall — custom EMF metric alarms have no metric filters**: Alarms in the `Notifly/ScheduledBatchDelivery` namespace (e.g., `DbInsert`, `FCMSendBatch`) are emitted as CloudWatch EMF metrics from Lambda stdout, not CloudWatch log metric filters. The helper will report `metric_filters: []` for these. Do not conclude "no logs exist." Instead, inspect the Lambda log group `/aws/lambda/<actual_function_name>` directly with `filter-log-events` around the alarm datapoint time. See `references/scheduled-batch-delivery-dbinsert-json-serialization-bug.md` for the `DbInsert outcome=error` pattern.

The script does the single-pass first investigation:
- parse alert text
- query live CloudWatch alarm metadata/history
- summarize 7d and 30d alarm history
- **Pitfall**: `describe-alarm-history` may return entries with `StateValue: null` and `StateReason: null`. When this happens, the helper cannot count ALARM transitions from history alone. First, inspect `HistoryData` JSON: it contains `oldState.stateValue` and `newState.stateValue` fields that reliably encode the transition direction. If those are also absent or parsing fails, fall back to metric datapoint breach density and the alarm's current `StateReason` from `describe-alarms`.
- fetch CloudWatch metric datapoints
- detect log groups / project IDs
- inspect metric filters
- run fixed Logs Insights query templates for counts and top signatures
- collect current alarm-window CloudWatch log contexts from the latest `ALARM` transition, then trigger-centered contexts from the exact log stream/time window
- summarize HTTP 4xx/5xx metrics when inferable
- summarize SQS/DLQ context when queue names/dimensions are present
- summarize Lambda config/event sources/runtime metrics when function names/dimensions are present. **Pitfall**: alarm name prefixes may contain priority tiers or other suffixes that do not match actual Lambda function names (e.g., `ScheduledBatchDelivery-P2-...` maps to `scheduled-batch-delivery`); when the collector fails with `ResourceNotFoundException`, fall back to manual name resolution. See `references/lambda-name-mapping-gaps.md`.
- map project IDs via DynamoDB `project`
- map or explicitly rule out project/campaign/user_journey scope
- inspect RDS topology if the alarm is RDS-shaped
- query Performance Insights for top SQL grouped by DB instance when the alarm is RDS-shaped
- search local repo for exact error/alarm strings and return only compact implementation/Terraform context

Do not write custom Logs Insights syntax in the LLM loop unless the helper failed and the missing question cannot be answered otherwise.
If a manual Logs Insights query is unavoidable, keep it based on the helper's fixed query shape and return only aggregate counts or sanitized samples.

### Helper answerability gate

If the helper returns `can_answer_root_cause: true`, produce the final answer
from the helper output immediately. Do not run manual AWS, source-search, or
CloudWatch Logs follow-up calls unless `missing_required_context` contains a
blocking item whose absence makes the fixed final format impossible.

For service-wide or infra-wide metric alarms with no project/campaign/user
journey evidence, do not search raw logs just to find a project. Use
`scope_attribution.required_final_field` and state that the scope is service
wide and campaign/user journey is unknown.

Never run broad `aws logs filter-log-events` or raw log-dump commands in the
LLM loop. If a log query is genuinely required, add or use a bounded helper
collector that returns grouped counts and sanitized samples only.

After the helper returns, inspect these fields before composing the final answer:
- `can_answer_root_cause`
- `missing_required_context`
- `required_followups`

If `can_answer_root_cause` is `false`, do not finalize from the first helper output unless every listed follow-up is impossible, unsafe, or lacks credentials. Execute read-only `required_followups` in priority order, keeping the output compact, and use the new evidence in the final answer.

If `missing_required_context` is non-empty but `can_answer_root_cause` is `true`, answer the root cause from the available evidence but still fill safe follow-ups that affect mandatory final fields such as project/campaign/user journey, DB instance/query, or concrete code/Terraform action.

If a follow-up cannot be completed, the final answer must name the unavailable context briefly instead of implying it was checked.

For log-derived alarms, never finalize with only alarm frequency, threshold, or metric-filter wording when current trigger log details are available. Use `logs.current_error_details[].likely_error`, `context_lines`, and `error_lines` to explain what actually happened in the triggering request/job.

## Continuous improvement loop

Every `check` execution should improve this skill over time:
- If you needed extra manual tool calls beyond the helper, decide whether that step is deterministic and reusable.
- If it is reusable, silently fold it into the helper package (`scripts/notifly_alert_context/`), preferably as a config entry, collector registry entry, or fixed query template, during the same session when safe.
- For any new alert pattern not covered by the helper, classify the missing context before finalizing: alarm family, AWS API needed, log query shape, source-search token, and final response field it should feed.
- Add a small bounded collector or fixed query template for the new pattern when it can be implemented read-only and compactly. Prefer structured fields over prose.
- If code changes are not safe during that Slack session, include a `helper_gap` note in the private reasoning and keep the final answer concrete with the best available evidence.
- Prefer adding compact helper fields, fixed query templates, or output caps over adding more prose instructions.
- If no reusable improvement is found, do not edit files just to create churn.
- For Slack automated alerts, keep this maintenance silent and still post exactly one final Korean response with the hidden status directive.

## Investigation recipes

### A. RDS / Aurora CPU / memory alarm

Pattern examples:
- `CPUUtilization too high`
- `FreeableMemory`
- `notifly-db-prod-cluster`

Flow:
1. alarm metadata + exact thresholds
2. alarm history (`OK -> ALARM`, `ALARM -> OK`)
3. CloudWatch datapoints that actually breached
4. instance topology (writer/readers)
5. Performance Insights `db.load.avg` grouped by `db.sql` on the offending instance
6. use the current alarm focus window first; report dominant `current_top_projects_by_load` instead of listing every project seen in the broader PI lookback
7. if `current_unattributed_top_sql` has significant focus load, report it separately as unattributed DB load instead of assigning it to every detected project
8. if sharded table suffix/project_id appears in SQL -> map via DynamoDB and include the project/product
9. for campaign/user journey, inspect campaign-capable table families (`delivery_result`, `message_events`, `scheduled_messages`, `campaign`, user journey tables) with read-only aggregates around the alarm window; do not mark campaign/user journey unknown until this is impossible or inapplicable

Questions to answer:
- Why did the alarm fire?
- Which instance, writer, or reader caused it?
- Which SQL family/query fingerprint created the load?
- Which project/product is dominant in the current alarm focus window, and which projects are only background/minor contributors?
- Which project/product/campaign/user journey is connected to the SQL table suffix or aggregate? Do not print campaign and user journey together.
- Is this a noisy alert or a real incident signal?

### B. ECS console/log-derived alarm

Pattern examples:
- `/aws/ecs/notifly-services-prod/...`
- `console error`
- `slow eic query`
- `Processing took longer than expected`
- Redis / CROSSSLOT / rate-limit errors

Flow:
1. alarm + metric filter config
2. live alarm history
3. Logs Insights for the primary metric filter pattern and daily counts
4. inspect `logs.current_alarm_window`, `logs.current_top_signatures`, and `logs.current_trigger_contexts` before writing the final answer; root cause must be based on the error that caused the latest `ALARM` transition, not a historical 7d/30d top signature, alarm name, or broad service name
5. if the current alarm-window context shows DB errors, duplicate keys, deadlocks, dependency timeouts, or route/controller frames, treat those as the primary cause and map them to project/table/code context
6. **Helper fallback**: if the helper skips Logs Insights (`logs.skipped`) despite a clear metric filter, use the bounded manual trace in `references/ecs-log-manual-trace.md` rather than running broad `filter-log-events` across the whole log group.
7. if alert volume changed, inspect:
   - metric filter drift
   - alarm config drift
   - SNS subscriber drift
   - CloudTrail `PutMetricFilter` / `PutMetricAlarm` / `Subscribe`
8. trace exact code path in `notifly-event`
9. if user asks when it started, find earliest retained log and correlate to PR/commit

Do not claim a metric filter is matching unrelated messages unless the helper's primary filter terms and current alarm-window contexts prove it. Related metric filters, historical top signatures, and broad alarm words are only supporting context.

**Pitfall — metric-filter name vs. actual trigger**: an alarm may be named after a historic cause (e.g., `slow eic query`) while the current trigger is a different, coarser log pattern (e.g., `[WARN] Processing took longer than expected`). When the same log group already carries a purpose-built metric filter in a custom namespace (e.g., `Custom/segment-publisher` → `SegmentPublisher.ExecutionTimeOverThreshold`), the `ConsoleErrors` copy is likely redundant or stale. Always inspect the exact log line that breached the threshold and the full set of metric filters on the log group before letting the alarm name dictate the root cause. See `references/segment-publisher-slow-eic-query-noise.md` for a concrete example.

**Pitfall — broad metric filter catching multiple unrelated causes**: a coarse substring filter (e.g., `took too long`) may match both a benign WARN continuation and a real DB-query latency signal. The alarm name may be accurate for one pattern (e.g., `EventCounterCteManager.extract` slow EIC query) while a second pattern (batch-processing `[WARN]`) is noise. Always read the exact log line and surrounding context to determine which pattern fired and triage separately.

**Pitfall — helper skipping literal substring metric filters**: when `metric_filters[].filter_pattern` is a simple literal string (e.g., `Processing took longer than expected`) and the helper reports `logs.skipped: "no stable filter terms inferred"`, the helper’s term extractor is failing on what should be a stable substring. Do not conclude "no logs exist." Fall back to the bounded manual trace in `references/ecs-log-manual-trace.md` with the exact literal string, or run a direct Logs Insights `filter @message like 'Processing took longer than expected'` query bounded to the alarm window. This commonly affects `segment-publisher long running alam` and similar alarms whose filter pattern is a plain phrase rather than a tokenized keyword list.

**Pitfall — access-log benign substring matching coarse filter**: a metric filter such as `%ERROR|Exception%` may match benign substrings embedded in HTTP access logs, e.g. a query parameter `templateName=service_error` or a path segment containing `error`. The resulting log line is a normal 200/304 request, not an application error. When `logs.current_error_details` is empty and the trigger context shows only access logs, run a follow-up Logs Insights query that filters out known benign patterns (e.g., `service_error`, `error.html`) to confirm whether any real ERROR logs exist in the alarm window. See `references/ecs-console-error-false-positive-patterns.md`.

**Pitfall — Sentry email alert pipeline matching its own payload**: The `ops-email-receiver` Lambda writes parsed Sentry email alerts to a dedicated log group (`/aws/ecs/notifly-services-prod/web-console/sentry`). A broad `%ERROR%` metric filter on that log group matches the S-issue `title` (`"Error"`, `"SyntaxError"`) and `"level":"error"` inside the JSON payload, causing the alarm to fire whenever any Sentry alert arrives. The Lambda itself is healthy; the real errors are `web-console` Next.js issues tracked in Sentry. When the helper returns empty `current_trigger_contexts`, fall back to `aws logs filter-log-events` bounded by the exact metric-datapoint window because Logs Insights lags metric-filter ingestion. See `references/sentry-email-alert-pipeline-false-positives.md` for scope extraction via `productId` and DynamoDB GSI lookup.

### C. Console error log-level triage / bulk Amazon Q review

Use this when the user asks to review recent Amazon Q / AWS Chatbot `console error` alerts over a time range and decide which logs can be downgraded from `ERROR` to `WARN`/`INFO` in `notifly-event`.

Flow:
1. If the user gives only a Slack channel ID, map `SlackChannelId -> SnsTopicArns` via AWS Chatbot in `us-west-2`, then find CloudWatch alarms whose actions use those SNS topics; this reconstructs Amazon Q alert scope without Slack history.
2. For each relevant `ConsoleErrors` / log-derived alarm, use alarm history plus CloudWatch Logs Insights around recent `ALARM` windows to extract actual triggering log signatures, not just alarm names.
3. Group signatures by service and code path, then trace the exact source location in `notifly-event` before recommending any log-level change.
4. Apply a fail-closed downgrade rule:
   - safe to downgrade only when the log is a handled expected/business/validation outcome and the invocation continues or exits normally;
   - keep `ERROR` for unhandled exceptions, Lambda invocation failures, DLQ-producing paths, DB/SQS/Kinesis writes, provider unknown/network failures, data loss, or dependency failures.
5. Prefer `WARN` for handled but operator-visible data/config quality issues; prefer `INFO` for normal empty-result/no-op outcomes.
6. Remove or minimize full payload/request dumps while downgrading; log only compact non-sensitive context such as project/campaign IDs, metric names, dates, and counts. Treat recipient/device/request payloads as potential PII.
7. Implement in small service-scoped PRs with tests that assert both the new level and that `console.error` is not called for the safe path; also assert non-suppressible failure paths remain `ERROR`.
8. PR body should explicitly list out-of-scope `ERROR` paths so reviewers can see service-fault observability is preserved.

Good candidates seen before:
- empty result with explicit user notification and normal return -> `INFO`
- invalid recipient/device tokens already converted into delivery failure records -> `WARN`
- provider error branches already marked suppressible by code -> `WARN`
- duplicate non-fatal config/cache mappings where processing continues -> `WARN`

Bad candidates / keep `ERROR`:
- database/SQS/Kinesis write failures
- Lambda unhandled exceptions, timeout/OOM, DLQ/retry exhaustion
- provider unknown, network, auth, or rate-limit failures unless explicitly handled/suppressed
- cache initialization or delivery-policy missing data when it may hide a real initialization/data bug

### D. SQS / DLQ alert

Pattern examples:
- `ApproximateNumberOfMessagesVisible`
- `ApproximateAgeOfOldestMessage`
- `*-dlq`
- retry / maxReceiveCount questions

Flow:
1. queue attributes
2. main queue vs DLQ metrics
3. redrive policy and source queue hints
4. Lambda/event source mapping for the consumer when inferable
5. Lambda logs for retry phrases
6. **Lambda throughput bottleneck analysis** (for `ApproximateAgeOfOldestMessage` alarms):
   - if the consumer is a Lambda, inspect the EventSourceMapping config: `BatchSize`, `MaximumConcurrency`, `VisibilityTimeout`
   - check Lambda `Duration`, `Errors`, `Throttles` metrics; short duration + zero errors + zero throttles with queue age rising strongly suggests throughput bottleneck, not code failure
   - compare `NumberOfMessagesSent` vs `NumberOfMessagesDeleted`: near-parity means consumption is keeping up on average; a transient spike causes the age alarm
   - if `MaximumConcurrency` is low (e.g., 2) and `BatchSize` is small (e.g., 50) while message volume is high, the Lambda is likely the bottleneck even when healthy
   - see `references/sqs-lambda-throughput-bottleneck.md` for the full recipe
7. **DLQ-specific checks** (for `-dlq` alarms):
   - DLQ alarms often have no `ALARM` history because messages are short-lived. Cross-correlate with the companion main-queue alarm (e.g., `ApproximateAgeOfOldestMessage` or throughput alarms) using `describe-alarm-history` or `describe-alarms` on the main queue name.
   - Read the main queue `RedrivePolicy` and check `maxReceiveCount`. A value of **1** means any transient receive failure immediately DLQs the message with zero retries. This is a common structural root cause.
   - Check Lambda `Errors` and `Throttles` during the window. If both are zero, the DLQ entries are likely from retry policy, not code bugs.
   - `receive_message` on the DLQ may return zero messages during investigation because they were already re-driven, purged, or consumed. This does not invalidate the alarm.
   - **Inspect DLQ message bodies** with `receive_message` (read-only, do not delete) to extract `project_id`/`campaign_id` from the JSON payload. Map via DynamoDB `project` for scope attribution even when Lambda logs are sparse. See `references/sqs-dlq-message-inspection.md`.
   - **Lambda-healthy + DLQ-has-messages paradox**: When Lambda `Errors=0`, `Throttles=0`, and `Duration` is normal, yet DLQ has messages, the failure is likely an AWS service-level message-deletion failure (Lambda succeeded but the internal SQS `DeleteMessage` call failed), or `maxReceiveCount=1` causing immediate DLQ routing on any transient issue. Do not force a code-bug root cause when metrics show healthy Lambda. There is **no customer-visible log source** for Lambda-SQS deletion failures; see `references/sqs-dlq-alarm-triage.md` § "Deep analysis: Lambda healthy but DLQ still receives messages" for evidence limits and the full triage recipe.
   - see `references/sqs-dlq-alarm-triage.md` for the full recipe
8. avoid `receive_message` unless explicitly approved because it changes message visibility
9. separate:
   - retry broken
   - retry working but poison messages still exhausting budget
   - historical DLQ residue only
   - throughput bottleneck (consumer concurrency too low for traffic spike)
   - aggressive `maxReceiveCount=1` causing zero-retries-on-failure

### E. HTTP 4xx / 5xx / API error-rate alarm

Pattern examples:
- `[api-service] 4xx error response is greater than 300 in 5m`
- API Gateway / ALB `4XXError`, `5XXError`, `HTTPCode_Target_4XX_Count`

Flow:
1. alarm metric/dimensions and exact threshold
2. 4xx/5xx/request-count peer metrics over 7d
3. Logs Insights or Athena/access-log aggregate by status, route/path, method, target service, and project/campaign IDs when available
4. source search for the route/controller/error mapper that emits the dominant status
5. distinguish customer/client input spikes from server-side regression
6. if AI gateway or Workers AI dependency is suspected, verify Cloudflare status per `references/cloudflare-workers-ai-status-check.md`

### F. Redis / CROSSSLOT / cache incident

Pattern examples:
- `All keys in the pipeline should belong to the same slots allocation group`
- `CROSSSLOT`
- `enableAutoPipelining`

Flow:
1. exact error logs and first-seen time
2. error daily trend vs traffic/command metrics
3. inspect ElastiCache cluster shape and headroom
4. trace repo call sites and redis client config
5. correlate to PR/commit that changed cache behavior or redis config
6. separate direct root cause from later traffic amplifier

### G. Lambda latency / error / throttle alarm

Pattern examples:
- `*-FCMLatencyP99`, `*-LatencyP99`
- `*-Errors`, `*-Throttles`
- Metric namespace `Notifly/ScheduledBatchDelivery`, `AWS/Lambda`

Flow:
1. alarm metadata + exact threshold and metric statistic (p99, Average, Sum)
2. alarm history and recurrence pattern
3. CloudWatch metric datapoints that breached, from the custom namespace if available
4. **resolve the real Lambda function name**: alarm prefixes may include priority tiers (e.g., `-P2`) that are not part of the actual function name; see `references/lambda-name-mapping-gaps.md`
5. Lambda configuration (`MemorySize`, `Timeout`, `LastModified`) from the **actual** function name
6. **EventSourceMapping config** when the alarm is tied to an SQS/Kinesis/DynamoDB trigger:
   - `BatchSize`, `MaximumConcurrency`, `ParallelizationFactor`, `BisectBatchOnFunctionError`
   - low `MaximumConcurrency` (e.g., 2) with rising queue latency is a strong throughput-bottleneck signal even if Lambda Duration/Errors/Throttles are all healthy
7. `AWS/Lambda` Duration/Errors/Throttles metrics for the real function
8. log group `/aws/lambda/<actual_name>` for ERROR lines or trigger context
9. correlate `LastModified` deploy time to the alarm window; recurring alarms that spike right after a deploy are not purely baseline
10. determine scope: these are usually service-wide unless log payloads carry `project_id`/`campaign_id`; do not force a project scope when none exists

Pitfall: do not assume the alarm name prefix equals the Lambda function name. When the helper Lambda collector fails with `ResourceNotFoundException`, manually list Lambdas and match by base service name, then verify `LastModified`.

**Distinguishing real bugs from metric-filter noise**: The `ConsoleErrors` namespace is a coarse log substring filter. For Lambda functions, always cross-check the `AWS/Lambda` `Errors` metric. If `Errors > 0`, the alarm reflects a real invocation failure (unhandled exception, timeout, OOM). If `Errors == 0` and `Throttles == 0`, the log line is likely benign text caught by the broad filter. See `references/kds-consumer-event-timestamp-rangeerror.md` for a concrete real-bug example where the `RangeError` in `getValidEventTimestampInMilliseconds` elevates both console ERROR logs and Lambda runtime Errors. See `references/anomaly-delivery-monitoring-lambda-consoleerrors.md` for the counterpart false-positive pattern where routine inspection logs at ERROR level trip the metric filter while Lambda runtime Errors remain zero.

**Pitfall — empty `current_trigger_contexts` on Lambda ConsoleErrors alarms**: The helper's Logs Insights query for the current alarm window may return zero results despite the metric filter having breached. This is common for Lambda log groups where Logs Insights ingestion lags behind metric-filter evaluation. When `logs.current_trigger_contexts` is empty but `can_answer_root_cause` is `true`, do not assume no logs exist. Run a bounded `aws logs filter-log-events` on `/aws/lambda/<actual_function_name>` using the exact metric datapoint timestamp ±5 min as the time window. Use the literal `filterPattern` from the metric filter configuration or a `like` query with the known ERROR substring. This fallback is read-only and deterministic; it resolves scope and trigger evidence that Logs Insights may miss.

**Pitfall — `Notifly/ScheduledBatchDelivery DbInsert` JSON serialization / surrogate pair bug**: For `ScheduledBatchDelivery-P2-DbError` alarms (or any `Notifly/ScheduledBatchDelivery` alarm with `DbInsert outcome=error`), the Lambda log group `/aws/lambda/scheduled-batch-delivery` typically shows `invalid input syntax for type json` on INSERT into `delivery_result_<project_id>` or `delivery_failure_log_<project_id>`. The push-notification path in `scheduled-batch-delivery` most commonly leaks `[object Object]` via `toSendFailureLog` in `services/lambda/scheduled-batch-delivery/lib/push_utils.js` (`sender_info`, `request_body`, `response_body` are raw objects without `JSON.stringify`). The text-message path in `scheduled-batch-text-message-delivery` leaks via `prepareSendResultsToInsertForNHNCloud` (`extra_data` is a raw object). Even when `JSON.stringify` is present, PostgreSQL can reject the JSON with `code: '22P02'` and `detail: 'Unicode low surrogate must follow a high surrogate.'` when emoji in personalized message content have broken UTF-16 surrogate pairs. Inspect the pg error object's `detail` and `where` fields in Lambda logs to distinguish the two failure modes. Also note that the ConsoleErrors alarm `scheduled-batch-delivery lambda error` (metric filter `%ERROR|Status: timeout%`) catches these same ERROR logs, so the same triage applies even when the alarm namespace is `ConsoleErrors` rather than `Notifly/ScheduledBatchDelivery`. See `references/scheduled-batch-delivery-dbinsert-json-serialization-bug.md` for scope extraction, exact file/line targets for both Lambdas, and surrogate pair triage.

**Pitfall — using Slack message time instead of alarm datapoint time for log searches**: When the helper fails and manual `filter-log-events` is needed, anchor the search window precisely to the CloudWatch alarm's `StateReasonData.startDate` or `recentDatapoints[].timestamp` (from `describe-alarms`), converted exactly to epoch milliseconds. Slack `message_ts` and conversation start times can lag the actual alarm transition by minutes or hours; using them as the window anchor searches the wrong time range and may return zero matches even when the triggering logs exist.

**Percentile metric pitfall**: `get-metric-statistics` does not accept `p99` or any percentile statistic. The valid set is `SampleCount | Average | Sum | Minimum | Maximum`. For percentile alarms such as `*-FCMLatencyP99`, use `Maximum` as a conservative proxy, or switch to `get-metric-data` with `ExtendedStatistics=['p99']` if the exact value is required. See `references/scheduled-batch-delivery-fcm-latency.md` for a concrete FCM latency triage recipe.

**Pitfall — CloudWatch Logs API timestamp unit confusion**: `aws logs filter-log-events` expects `--start-time` and `--end-time` in **epoch milliseconds** (ms since 1970-01-01). Some AWS APIs (e.g., `describe-log-streams`) return `lastEventTimestamp` in milliseconds, but the raw value may be visually indistinguishable from seconds if you only glance at the integer. Always verify the unit before passing a value to `filter-log-events`; using seconds instead of milliseconds searches a time range seconds after 1970 and returns zero events, creating a false "no logs exist" conclusion. Convert with `date -d 'YYYY-MM-DD HH:00:00 UTC' +%s` and then multiply by 1000.

**Pitfall — `kds-consumer` null byte → PG error → timeout → ConsoleErrors false positive**: When the `kds-consumer` Lambda processes events containing `\u0000` (null byte) in `event_params`, the INSERT into `event_intermediate_counts_<project_id>` fails with PostgreSQL `22021` (`invalid byte sequence for encoding "UTF8": 0x00`). The code retries up to 10 times via `async-retry`, exhausting the Lambda timeout (900s) and producing a `REPORT ... Status: timeout` line. The `ConsoleErrors` metric filter (`%ERROR|Status: timeout%`) matches this REPORT line, triggering the alarm even though there is no unhandled Lambda exception. Simultaneously, the actual ERROR log line (`invalid byte sequence...`) may be matched by the same filter. Cross-check `AWS/Lambda Errors` to confirm whether this is a runtime crash (real bug) or a retry-timeout from a known data-quality issue. Root cause is usually missing sanitization of `\u0000` in `constructEventIntermediateCountData()` (`services/lambda/kds-consumer/lib/event_counter_utils.ts`). See `references/kds-consumer-null-byte-utf8-timeout.md`.

### H. Kinesis stream iterator age / throughput alarm

Pattern examples:
- `notifly-event-stream High GetRecords Iterator Age`
- `ReadProvisionedThroughputExceeded`
- Metric namespace `AWS/Kinesis` with `GetRecords.IteratorAgeMilliseconds`

Flow:
1. alarm metadata + exact threshold (this is a native AWS metric alarm, not log-derived)
2. alarm history and recurrence pattern
3. **Stream status**: `describe-stream` to confirm `ACTIVE` and record shard count
4. **Consumer topology**: `list-stream-consumers` for EFO consumers; `list-event-source-mappings` to find the actual Lambda consumer. Do not guess the Lambda name from the stream name.
5. **EventSourceMapping config**: `BatchSize`, `ParallelizationFactor`, `MaximumRetryAttempts`, `BisectBatchOnFunctionError`, `DestinationConfig` (DLQ)
6. **Lambda function config**: `MemorySize`, `Timeout`, `LastModified` (deploy time correlation)
7. **Producer traffic**: `IncomingRecords` trend over the past hour to identify spikes
8. **Consumer health**: Lambda `Errors`, `Duration`, `Invocations` in the same window
9. **Iterator age trend**: `GetRecords.IteratorAgeMilliseconds` over the past hour to see if the spike is transient or sustained
10. **Bounded Lambda log check**: `filter-log-events` on `/aws/lambda/<actual_name>` for ERROR lines around the alarm datapoint time; anchor to `StateReasonData.startDate`, not Slack message time
11. Determine if the alarm is a transient spike (`no_action`), throughput bottleneck (`needs_fix` if recurring), or consumer failure (`needs_fix`/`urgent`)

Scope is typically infra-wide because Kinesis streams are shared pipelines with no per-project dimensions on `AWS/Kinesis` metrics. Do not force a project scope unless Lambda logs contain explicit `project_id`/`campaign_id`.

See `references/kinesis-stream-iterator-age-triage.md` for exact bounded commands and interpretation heuristics.

## DynamoDB project mapping rule

Whenever you find a `project_id`, fetch from DynamoDB `project` table with a projection expression and report:
- `id`
- `product_id`
- `name`
- mapping status and failure reason when unavailable

Do not fetch full items because the table may contain sensitive sender credentials.

**Sentry alert scoping**: When the alert originates from the `web-console/sentry` log group, the Sentry JSON payload may contain a Notifly product slug in `request.url` or `tags.url` (e.g. `productId=hybiome`). Use the `project` table GSI `product_id-project_id-index` to map this slug to a Notifly `project.id`. See `references/sentry-email-alert-pipeline-false-positives.md` for the exact query and duplicate-item pitfall.

### Non-existent project edge case (api-service)

If the `project_id` is missing from the `project` table **and** no related `event_list_<project_id>` or sharded DB tables (e.g., `campaign_statistics_<project_id>`, `users_<project_id>`) exist, the project is effectively non-existent. When an api-service `42P01` (`relation does not exist`) error is tied to such a project, the root cause is usually an external caller using an invalid or stale `project_id`. Check the structured access/error log for:
- `ip` / `userAgent` (e.g., `curl/7.81.0` indicates a manual/scripted call)
- `path` / `method` of the request
- Request volume and recurrence pattern

Single or sporadic `curl` requests from an unrecognized IP suggest a misconfigured client test rather than a service regression. See `references/api-service-invalid-project-tracing.md` for the full trace recipe.

## GitHub correlation rule

If the user asks:
- "When did it start?"
- "Which commit or PR was related?"
- "Which change surfaced it?"

then:
1. first find earliest retained log time
2. then inspect local git history in `~/workspace` or `/home/ubuntu/notifly-event`
3. if needed, use GitHub API with `GITHUB_TOKEN`
4. separate:
   - first observed time
   - direct enabling change
   - later change that amplified / surfaced the issue

## Postgres / DynamoDB / Athena step

Use read-only Postgres/DynamoDB/Athena when AWS logs/metrics identify a project, campaign, user journey, event family, or log table to verify.

Examples:
- confirm campaign / user journey / schedule relationship
- inspect schema/index shape for a known table family
- verify shard table existence for a discovered `project_id`
- compare recent 7d/30d event or error counts

**Pitfall — sharded campaign lookup**: Notifly campaigns are stored in 1,400+ sharded Postgres tables (`campaigns_<project_id_hash>`). Scanning all tables to map a campaign ID to its owning project is impractical and may hit command-length limits. Prefer:
- DynamoDB `event_list_*` tables for recent campaign-project relationships.
- Athena `notifly_analytics.notifly_campaign_events` for historical mapping.
- Accepting "project unknown for campaign" in the final answer when neither source is available.

Never mutate data.

## Output shape

For interactive user requests, answer in this order:
1. direct conclusion
2. mandatory scope: project/product and exactly one of campaign or user journey, or explicit Korean unknown/service-wide/infra-wide wording
3. DB instance + SQL fingerprint when DB-shaped, or exact evidence from AWS/logs/metrics otherwise
4. exact evidence from AWS/logs/metrics
5. tradeoff: real issue vs noisy alert
6. concrete next action naming the implementation file/function, SQL/index/table family, or Terraform resource/path to change

For automated Slack subscription alerts, obey the automated Slack alert contract instead of this longer shape.

## Practical note

The helper script is only the first pass.
For full incident work, continue with the appropriate datasource-specific steps above.
