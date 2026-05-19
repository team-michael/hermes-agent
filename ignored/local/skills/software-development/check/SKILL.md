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
- **Pitfall — Amazon Q / AWS Chatbot follow-up in the same thread**: Amazon Q sometimes posts a second Slack message in the same thread containing the full CloudWatch log extract or console link. This is supplementary context for the alarm already analyzed, not a new alert. If the same alarm was already triaged in the thread root, do not post a second full 5-field analysis. A concise one-line acknowledgment that the alarm is already triaged is sufficient unless the follow-up reveals a materially different error signature or a new alarm name.
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
- **Time-of-day recurrence**: when alarms fire at nearly the same clock time on multiple days (e.g., every day at ~17:10 KST), treat this as a scheduled/cron-like signature. Check whether the spike correlates with a batch job, external provider sync, or client-side retry window before classifying as purely random traffic.

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
   - If a project name appears in logs without a `project_id` (e.g., `Failed to execute payment for <name>`), scan DynamoDB `project` table with `FilterExpression '#n = :val'` on the `name` attribute to resolve the `project_id`.
3. For campaign or user_journey IDs, use read-only DynamoDB/Postgres/Athena lookups to map names and owning project/product when available.
   - **Pitfall — empty `campaigns_*` table does not mean deleted**: When a candidate campaign ID is not found in `campaigns_<project_id>`, do not conclude it was deleted. It may be a user journey ID stored in `user_journeys_<project_id>`. Check the `resource_type` field in `delivery_result_<project_id>` or `message_events_<project_id>` if the alarm logs include DB insert lines. If `resource_type = 'user_journey'`, query `user_journeys_<project_id>` for the ID and report user journey scope instead. See `references/email-delivery-bounce-rate-triage.md` for a concrete example where `ifrxyr` existed in `user_journeys_*` but not in `campaigns_*`.
4. For Postgres table names, infer project from the `table_$project_id` suffix and then map that project.
5. For log lines containing both `Project Id` and `Campaign Id`, treat the pair as the primary campaign scope. Current alarm-window pairs outrank 7d/30d historical signatures.
   - Also treat log-style `campaign_id: <id>, project_id: <id>` and `project_id: <id>, campaign_id: <id>` as primary project/campaign pairs.
   - Also treat compact ECS log lines such as `campaignId: UL1T00` (with or without accompanying `projectId`) as primary scope evidence when they appear in the current alarm-window stream.
   - Also treat structured api-service `error-response` logs containing `"projectId":"<id>"` as project scope evidence when they appear in the current alarm-window stream.
   - Also treat `segment-publisher` `Received event` JSON payloads containing a `user_journeys` array (with `schedule_type: "user_journey"`) as user journey scope evidence; the `campaign_id` field in the same stream then refers to the user journey ID.
   - Never combine a standalone campaign ID with an unrelated sharded table suffix from another log line. IDs from `relation "<table>_<project_id>" does not exist` are table references, not campaign ownership evidence, unless that table error is the actual current trigger and no stronger project/campaign pair exists.
   - **Pitfall — campaign/user journey IDs are not globally unique**: Notifly stores campaigns and user journeys in sharded tables (`campaigns_<project_id>`, `user_journeys_<project_id>`). The same ID string can exist in multiple projects' shards. For example, `UL1T00` has been observed under both `stepup` and `proudp` on different days. Do not scope by campaign/user journey ID alone using prior-day evidence when the current alarm window lacks an explicit `project_id`. See `references/segment-publisher-slow-eic-query-noise.md` § "Scope-attribution caveat for UL1T00" for a concrete example.
   - **Pitfall — helper `scope_kind` may mismatch the actual trigger**: When a Lambda log stream contains mixed `resource_type` values (both `campaign` and `user_journey`) within the same alarm window, the helper's `scope_attribution.scope_kind` can derive from keyword frequency across all contexts rather than the specific log line that breached the metric filter. For example, the helper may report `scope_kind: "user_journey"` even when the actual trigger is a `campaign` ERROR line. Always verify the `resource_type` field on the specific triggering log line (the one matching the metric filter pattern) before accepting `scope_kind` as definitive.
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

**Pitfall — bracket service prefix in alarm name**: Alarm names starting with a service bracket prefix such as `[api-service]` or `[web-console]` may not be parsed by the helper text detector because the brackets break word-boundary heuristics. Pass `--alarm-name` explicitly when `detected.alarm_name` is null but the pasted text clearly contains a bracketed service name.

**Pitfall — bracket prefix breaks AWS CLI `--alarm-names` JSON parsing**: When an alarm name starts with `[` (e.g., `[api-service] 4xx ...`), the AWS CLI `--alarm-names` parameter interprets the leading bracket as the start of a JSON array and throws `ParamValidation: Invalid JSON`. The helper uses `--alarm-names` internally, so passing `--alarm-name '[api-service] ...'` to the helper will also fail with `missing_required_context: alarm_metadata` even when the alarm exists. Do not pass the raw bracketed name to `--alarm-name`. Reliable workarounds, in order of preference:
1. Use `--alarm-name-prefix` with a unique substring (e.g., `--alarm-name-prefix 'api-service 4xx'`). **Note**: the helper currently does **not** expose `--alarm-name-prefix`, so for helper bracket-prefix failures always fall back to direct AWS CLI or Python boto3.
2. Use direct AWS CLI with `--query` matching (the CLI field selector is not affected by bracket parsing):
   ```bash
   aws cloudwatch describe-alarms --region ap-northeast-2 \
     --query 'MetricAlarms[?contains(AlarmName, `api-service`) && contains(AlarmName, `4xx`)].{Name:AlarmName,Namespace:Namespace,MetricName:MetricName,Statistic:Statistic,Period:Period,Threshold:Threshold,ComparisonOperator:ComparisonOperator,StateValue:StateValue,StateReason:StateReason,StateReasonData:StateReasonData}' \
     --output json
   ```
3. Use Python `boto3` directly (the SDK does not have this JSON-parsing quirk).
4. Write the alarm name to a file and use `--alarm-names file:///tmp/alarm.txt`.
Do not retry the same bare quoted string; the CLI JSON parser will reject it regardless of shell quoting.

**Pitfall — DLQ creation alarm names**: alarm names matching the literal pattern `<queue-name>-dlq has been created` are not auto-detected because `has been created` is prose, not a metric. Pass `--alarm-name` explicitly, e.g. `--alarm-name 'kinesis-record-dispatcher-queue-dlq has been created'`.

**Pitfall — log-group prefix conflation in alarm name detection**: The text parser may prepend `/aws/ecs/.../` log-group prefixes to the auto-detected alarm name, or it may strip an existing prefix and return a bare name. If `describe_alarms` returns no metadata for a detected name but the alarm is known to exist, try the opposite form: prepend the full log group prefix (`/aws/ecs/notifly-services-prod/<name>`) to a bare detected name, or try the bare alarm name without the prefix.

**Pitfall — log-group path used as alarm name**: Some Terraform-generated alarms use the exact CloudWatch log group path suffixed with ` alert` as the alarm name (e.g., `/aws/ecs/notifly-services-prod/web-console/sentry alert`). When Slack delivers this bare path as the alert text, the helper text parser has no alarm-name marker and returns `detected.alarm_name: null`. The alarm name is literally the pasted string. Pass `--alarm-name` explicitly with the exact path when this pattern is suspected. This pattern is common for Sentry-pipeline and lambda-invocation metric-filter alarms created by Terraform `aws_cloudwatch_log_metric_filter` + `aws_cloudwatch_metric_alarm` pairs that reuse the log group name.

**Pitfall — bare alarm name without resource identifier**: Some alarms use minimal names like `High VolumeReadIOPs` with no cluster, service, or resource identifier embedded. The helper text parser may incorrectly prepend a resource name (e.g., `notifly-db-prod-cluster VolumeReadIOPs too high`) when the actual alarm name is simply `High VolumeReadIOPs`. When `describe_alarms` returns empty for a constructed name, try the exact bare name from the alert text first before adding prefixes.

**Pitfall — alarm name ending in `... lambda error` not parsed by text detector**: alarm names consisting only of `<service-name> lambda error` (e.g., `email-delivery lambda error`) may return `detected.alarm_name: null` because the helper text parser has no heuristic for the trailing `lambda error` suffix. Pass `--alarm-name` explicitly.

**Pitfall — helper returns `{}` or single-line empty JSON for Lambda `... lambda error` alarms**: When the helper exits 0 but produces only `{}` or a single-line empty result for a `<service> lambda error` alarm, the CLI either failed to resolve the alarm metadata or parsed a null alarm name and short-circuited. Do not halt investigation. Immediately run a bounded manual trace:
1. Describe the metric filter on the Lambda log group (`/aws/lambda/<service>`).
2. Get `ConsoleErrors` metric daily Sum for 7d/30d.
3. Run `filter-log-events` on `/aws/lambda/<service>` with `ERROR` bounded to the alarm datapoint window.
4. Cross-check `AWS/Lambda` `Errors` metric to distinguish real invocation failures from handled business rejections caught by `%ERROR|Status: timeout%`.
This fallback is deterministic and read-only; see `references/lambda-consoleerrors-handled-business-rejection.md` for classification of common handled rejection signatures.

**Pitfall**: When a metric filter pattern (e.g., `took too long`) differs materially from the alarm or metric name (e.g., `segment-publisher-prod slow eic query`), the helper may derive Logs Insights filter terms from the name and report `count_7d: 0` / `count_30d: 0` despite actual matches existing. Do not treat zero counts as absence of logs; fall back to the bounded manual trace using the exact `filter_pattern` string from `metric_filters[].filter_pattern`.

**Pitfall — `segment-publisher slow eic query` helper false-negative:** The helper frequently returns `can_answer_root_cause: false` for this alarm because its term extractor derives `slow eic query` from the alarm name instead of the actual metric filter pattern `took too long`. When this happens, bypass the generic `required_followups` and immediately run the bounded manual trace using `"took" "too" "long"` (three separate terms) plus a stream-first tail check. See `references/segment-publisher-slow-eic-query-noise.md` for exact fallback commands and Pattern A vs Pattern B triage.

**Pitfall — custom EMF metric alarms have no metric filters**: Alarms in the `Notifly/ScheduledBatchDelivery` namespace (e.g., `DbInsert`, `FCMSendBatch`) are emitted as CloudWatch EMF metrics from Lambda stdout, not CloudWatch log metric filters. The helper will report `metric_filters: []` for these. Do not conclude "no logs exist." Instead, inspect the Lambda log group `/aws/lambda/<actual_function_name>` directly with `filter-log-events` around the alarm datapoint time. See `references/scheduled-batch-delivery-dbinsert-json-serialization-bug.md` for the `DbInsert outcome=error` pattern. See `references/scheduled-batch-delivery-fcm-send-error.md` for the `FCMSendBatch`/`BatchCompletion` push-notification send-failure trace, including the meaning of `error_codes: {"unknown":1}` and bounded Logs Insights `parse` queries for tab-delimited EMF logs.

The script does the single-pass first investigation:
- parse alert text
- query live CloudWatch alarm metadata/history
- summarize 7d and 30d alarm history
- **Pitfall**: `describe-alarm-history` may return entries with `StateValue: null` and `StateReason: null`. When this happens, the helper cannot count ALARM transitions from history alone. First, inspect `HistoryData` JSON: it contains `oldState.stateValue` and `newState.stateValue` fields that reliably encode the transition direction.

  Exact extraction pipeline (use `--output json` because `--query` cannot filter null `StateValue` fields):
  ```bash
  aws cloudwatch describe-alarm-history --region ap-northeast-2 \
    --alarm-name 'ALARM_NAME' \
    --history-item-type StateUpdate \
    --start-date 'YYYY-MM-DDTHH:MM:SSZ' \
    --end-date 'YYYY-MM-DDTHH:MM:SSZ' \
    --output json | jq -r '.AlarmHistoryItems[] | [.Timestamp, (.HistoryData | fromjson | .oldState.stateValue // "-"), (.HistoryData | fromjson | .newState.stateValue // "-")] | @tsv'
  ```

  Then count transitions by window:
  ```bash
  # 30d/7d/1d/10m OK→ALARM counts
  awk -F'\t' '$2=="OK" && $3=="ALARM" {count++} END {print count+0}'
  # Daily OK→ALARM counts, sorted descending
  awk -F'\t' '$2=="OK" && $3=="ALARM" {print $1}' | cut -dT -f1 | sort | uniq -c | sort -rn | head -20
  ```

  If `HistoryData` is also absent or parsing fails, fall back to metric datapoint breach density and the alarm's current `StateReason` from `describe-alarms`.
- **Pitfall — periodic batch-job alarms with `INSUFFICIENT_DATA → ALARM` transitions**: Alarms for scheduled/batch jobs that emit metrics only during execution (e.g., `segment-publisher long running alam` with `TreatMissingData: missing`) transition from `INSUFFICIENT_DATA` to `ALARM` and back, never reaching `OK`. The helper counts `alarm_count_7d: 0` / `alarm_count_30d: 0` because it only counts `OK → ALARM` transitions. Use `get_metric_statistics` with `Period=86400` and `Statistics=Sum` on the custom metric namespace to verify daily recurrence. If the daily sum is perfectly stable (e.g., exactly 1.0 every day for 30 days), the alarm is a known periodic pattern, not an anomaly. Use the daily metric counts for the `빈도` field instead of the helper's transition counts when this pitfall applies.
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

**Pitfall — `can_answer_root_cause: false` with actionable `current_trigger_contexts`**: The helper may return `can_answer_root_cause: false` because `current_error_details` is empty even when `current_trigger_contexts` already contains a clear, specific error signature. When `current_trigger_contexts` shows a recognizable signature (e.g., `FailedToUploadImageException`, `InvalidImageFormatException`, `The maximum number of registered templates.`, `080 unsubscribe number missing`, `[Symbol(errored)]`, `de_CommandError` from `@aws-sdk/client-ses`), check whether it matches a known reference pattern first. If it does, the root cause is already known — the missing `current_error_details` is a structural gap, not a blocking unknown. In this case, bypass the generic `required_followups`, use the reference to classify the alert, and produce the final answer directly. Only run manual follow-up if the trigger context is truly ambiguous (generic `severity=ERROR` with no code path or provider name) or if scope attribution is still required for mandatory fields.

**Pitfall — helper scope aggregator misses project_ids from `current_trigger_contexts`**: The helper's top-level `detected_scope_ids.project_ids` and `scope_attribution.scope_kind` may report `"unknown"` even when individual `logs.current_trigger_contexts[].project_ids` entries contain valid `project_id` values (e.g., from Lambda SQS payload logs). When `scope_attribution` says unknown but at least one trigger context carries a `project_id`, extract those IDs and map them via DynamoDB `project` before declaring scope unknown. The same applies to `campaign_id` or `user_journey_id` nested inside individual context objects that the aggregator failed to merge.

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
10. cross-check downstream ECS service logs (especially `api-service`, `segment-publisher`) for `canceling statement due to conflict with recovery` / PG error `40001` during the same window — reader-replica query cancellations may surface in service logs before or without native RDS alarms firing. See `references/rds-aurora-replica-recovery-conflict.md` for bounded trace commands and classification.

Questions to answer:
- Why did the alarm fire?
- Which instance, writer, or reader caused it?
- Which SQL family/query fingerprint created the load?
- Which project/product is dominant in the current alarm focus window, and which projects are only background/minor contributors?
- Which project/product/campaign/user journey is connected to the SQL table suffix or aggregate? Do not print campaign and user journey together.
- Is this a noisy alert or a real incident signal?

### A2. RDS / Aurora VolumeReadIOPs / ReadIOPS batch workload

Pattern examples:
- `High VolumeReadIOPs`
- `VolumeReadIOPs too high`
- Metric namespace `AWS/RDS` with `VolumeReadIOPs` on `DBClusterIdentifier`

Flow:
1. alarm metadata + exact thresholds, period, and `StateReasonData.startDate`
2. alarm history (`OK -> ALARM`, `ALARM -> OK`) — look for daily time-of-day recurrence
3. CloudWatch cluster-level `VolumeReadIOPs` datapoints around the breach (5-min buckets)
4. per-instance `ReadIOPS` via `DBInstanceIdentifier` dimension — uniform spikes across all readers indicate distributed batch workload
5. cluster-level `ReadLatency` — if under ~5 ms, the spike is throughput, not contention
6. per-instance `CPUUtilization` during the window — under ~50% means capacity headroom
7. check ECS `segment-publisher` log streams active during the window for `Start extracting project segment` and batch `recipients published` lines
8. extract `project_id`/`campaign_id` from segment-publisher logs, map via DynamoDB `project`
9. if PI is available, inspect `db.load.avg` by `db.sql` on the cluster; if PI returns `NotAuthorizedException`, fall back to CloudWatch metrics + ECS logs
10. classify based on the interpretation table in `references/aurora-volume-read-iops-batch-workload.md`

Questions to answer:
- Is the spike uniform across all readers or isolated to one instance?
- Do ReadLatency and CPU remain healthy during the spike?
- Does alarm history show a daily ~25–35 min recurrence pattern?
- Is segment-publisher scheduled batch activity visible in ECS logs during the window?
- Is this a known recurring batch workload or an unexpected read surge?

**Pitfall — Performance Insights unauthorized**: `pi:DescribeDimensionKeys` may return `NotAuthorizedException` for the current IAM role. Do not block triage on PI; CloudWatch metrics (`ReadIOPS`, `ReadLatency`, `CPUUtilization`) and ECS logs are sufficient for classification.

**Pitfall — per-instance `VolumeReadIOPs` does not exist**: Aurora exposes `VolumeReadIOPs` only at the `DBClusterIdentifier` level. For instance-level breakdown, use `ReadIOPS` with `DBInstanceIdentifier` dimension.

**Pitfall — confusing cluster metric name with instance metric name**: The cluster metric is `VolumeReadIOPs`; the per-instance metric is `ReadIOPS`. Querying `VolumeReadIOPs` per instance returns no data.

See `references/aurora-volume-read-iops-batch-workload.md` for exact commands, interpretation table, and historical baseline.

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

**Pitfall — mixed-pattern day on broad metric-filter alarms**: When a single alarm fires multiple times in one day, do not assume all transitions share the same pattern. A broad metric filter can catch Pattern A in the morning and Pattern B in the afternoon. Always verify the exact log line for the **most recent datapoint** before classifying. See `references/segment-publisher-slow-eic-query-noise.md` § "2026-05-14 session — mixed-pattern day" for a concrete example where the same alarm had an actual slow EIC query at 12:59 KST and a batch-processing WARN at 15:30 KST.

**Pitfall — segment-publisher Pattern B memory pressure**: When the current trigger is `[WARN] Processing took longer than expected`, check `[MEMORY USAGE REPORT] rss:` in the same stream. If rss exceeds the ECS task memory limit (segment-publisher-prod tasks use 3072 MB) and the task does not OOM-kill, note this as a potential swap-driven latency indicator. It does not change classification by itself, but it helps explain why total batch time exceeds the 30-minute WARN threshold.

**Pitfall — do not substitute historical top signatures when current trigger contexts are empty**: when `logs.current_trigger_contexts` is empty because of Logs Insights ingestion delay, manual `filter-log_events` may also return zero results while the metric filter has demonstrably breached. In this state, do **not** fall back to `logs.top_signatures` or `logs.trigger_contexts` from previous alarm cycles as evidence for what caused the current `ALARM` transition. Historical top signatures describe the 7d/30d baseline mix, not the current trigger. The correct behavior is to state that the current trigger is **unverified due to log ingestion delay** and cite only what is confirmed (alarm history, metric datapoint, recurrence pattern). Do not invent a specific root cause for this alarm window until `current_trigger_contexts` or a bounded manual trace confirms it. This pitfall especially affects `web-console console error` alarms where coarse `%ERROR|Exception%` catches multiple unrelated external-provider validation errors; the most common historical signature (`The maximum number of registered templates.`) is not guaranteed to be the current trigger. See `references/web-console-max-registered-templates-external-provider.md` for the full external-provider rejection family.

**Pitfall — helper skipping literal substring metric filters**: when `metric_filters[].filter_pattern` is a simple literal string (e.g., `Processing took longer than expected`) and the helper reports `logs.skipped: "no stable filter terms inferred"`, the helper’s term extractor is failing on what should be a stable substring. Do not conclude "no logs exist." Fall back to the bounded manual trace in `references/ecs-log-manual-trace.md` with the exact literal string, or run a direct Logs Insights `filter @message like 'Processing took longer than expected'` query bounded to the alarm window. This commonly affects `segment-publisher long running alam` and similar alarms whose filter pattern is a plain phrase rather than a tokenized keyword list.

**Pitfall — `filter_log_events` false-negative on recently ingested WARN or ERROR lines**: `filter_log_events` with an exact phrase may return zero results and an empty `nextToken` chain even when the matching log line exists in the stream. This occurs because CloudWatch Logs indexing can lag behind metric-filter evaluation, especially for WARN-level lines in ECS service logs and ERROR-level lines in Lambda logs. When the alarm `StateReasonData` confirms a datapoint breach but `filter_log_events` returns empty, use `get_log_events` on the stream that was active during the alarm window (identified via `describe_log_streams` ordered by `LastEventTime`) to read the unindexed events directly.

**Pitfall — access-log benign substring matching coarse filter**: a metric filter such as `%ERROR|Exception%` may match benign substrings embedded in HTTP access logs, e.g. a query parameter `templateName=service_error` or a path segment containing `error`. The resulting log line is a normal 200/304 request, not an application error. When `logs.current_error_details` is empty and the trigger context shows only access logs, run a follow-up Logs Insights query that filters out known benign patterns (e.g., `service_error`, `error.html`) to confirm whether any real ERROR logs exist in the alarm window. See `references/ecs-console-error-false-positive-patterns.md`.

**Pitfall — Sentry email alert pipeline matching its own payload**: The `ops-email-receiver` Lambda writes parsed Sentry email alerts to a dedicated log group (`/aws/ecs/notifly-services-prod/web-console/sentry`). A broad `%ERROR%` metric filter on that log group matches the S-issue `title` (`"Error"`, `"SyntaxError"`) and `"level":"error"` inside the JSON payload, causing the alarm to fire whenever any Sentry alert arrives. The Lambda itself is healthy; the real errors are `web-console` Next.js issues tracked in Sentry. When the helper returns empty `current_trigger_contexts`, fall back to `aws logs filter-log-events` bounded by the exact metric-datapoint window because Logs Insights lags metric-filter ingestion. See `references/sentry-email-alert-pipeline-false-positives.md` for scope extraction via `productId` and DynamoDB GSI lookup.

**Pitfall — web-console "maximum number of registered templates" is an external provider limit, not our code**: When the current trigger is `Error: The maximum number of registered templates.` during campaign upsert, the error originates from **Kakao Biz Message Center** or **NHN Cloud** template creation APIs — not from AWS, not from our code. The string does not exist in the `notifly-event` codebase. The code path is `CampaignService.upsertCampaign` → `MessageTransformer.transform` → external provider template registration. This is a handled business rejection (provider quota exhausted), not a service bug. The alert itself is typically `no_action`; the long-term fix is log-level downgrade or pre-flight quota check. See `references/web-console-max-registered-templates-external-provider.md` for verification commands and exact file paths.

**Pitfall — web-console `FailedToUploadImageException` / `InvalidImageFormatException` is a Kakao image validation error, not our code**: When the current trigger is `[FailedToUploadImageException(유효하지 않은 URL입니다. : <url>)]` or `[InvalidImageFormatException(<filename>)]`, the error originates from an external Kakao SDK/wrapper during image upload validation. Neither string exists in the `notifly-event` codebase. This is a handled business rejection (client-provided invalid image URL or unsupported image format), not a service bug. 30-day volume is typically single-digit. Classify as `no_action` when no other ERROR patterns coexist. See `references/web-console-kakao-image-upload-validation-error.md` for triage commands and remediation direction.

**Pitfall — "maximum number of registered templates" is not always AWS SES**: The web-console `upsertCampaign` path logs `Error: The maximum number of registered templates.` when a template provider limit is reached. Do not assume AWS SES without live verification. Check actual SES template count with `ses.list_templates` (limit 10,000 per region). If count is well under the limit, the error is from NHN Cloud Kakao Bizmessage, Firebase, or another provider. Extract `project_id` from the `PUT /api/projects/{project_id}/campaigns` access log line and scope via DynamoDB. **Resolution**: When SES is confirmed not the bottleneck, guide directly to GitHub workflow `cleanup-nhncloud-unused-templates.yml` for manual NHN Cloud unused template cleanup — this pattern was previously resolved via that workflow. See `references/web-console-template-limit-scope.md` for verification commands and narrowing steps.

**Pitfall — DB replica `canceling statement due to conflict with recovery` masquerading as ECS console error**: When `current_trigger_contexts` shows PostgreSQL error `40001` with detail `User query may not have access to page data due to replica disconnect.`, the root cause is Aurora reader replica instability (WAL recovery conflict), not an application code bug. The ERROR logs are emitted by `pg` client retry paths in `packages/common/dist/db.js`. This pattern has been observed on `api-service` (`getUserData`), `segment-publisher`, and other services with reader-replica queries. Use 15-minute log buckets to determine if the spike is transient (single burst → 0) or sustained. Correlate with RDS `ReadLatency` and CPU metrics to confirm recovery. Classify as `no_action` when transient and already recovered; `needs_fix` only if sustained or recurring daily. See `references/rds-aurora-replica-recovery-conflict.md` for bounded trace commands, scope extraction from `users_<project_id>` table references, and classification guidance.

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
   - **newly deployed consumer consistent timeout**: When the queue `CreatedTimestamp`, Lambda `LastModified`, and EventSourceMapping `LastModified` are all within hours or minutes of each other, and every Lambda invocation ends with `REPORT ... Status: timeout`, the root cause is almost certainly a freshly deployed consumer that cannot reach its dependency (DB, VPC endpoint, secrets, external API). The DLQ payload may contain synthetic test data (e.g. round-number timestamps like `2025-01-01T00:00:00`). Check `NumberOfMessagesSent` on the main queue: near-zero means no production traffic has arrived yet. See `references/sqs-dlq-new-consumer-deployment-failure.md` for bounded trace commands.

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

**Pitfall — `api-service` 4xx alarm triggered by handled `/authenticate` client errors**: The `ConsoleErrors` metric filter `{ $.message = "error-response" && $.status >= 400 }` on `/aws/ecs/notifly-services-prod/api-service` counts every `error-response` log, but the underlying logs are emitted at `WARN` level for handled validation rejections. On weekdays around 17:00 UTC (KST 02:00), a burst of ~500–1000 `POST /authenticate` 400 requests from `Apache-HttpClient/5.3.1 (Java/17.0.19)` with `"Missing required fields"` reliably breaches the `Sum > 100` threshold. This is a client-side bad request, not a service fault. Weekend volume for this signature drops to near zero. Before classifying as `needs_fix`, inspect the alarm-window logs for the `/authenticate` dominance pattern and check the `level` field (`warn` vs `error`). See `references/api-service-4xx-authenticate-noise.md` for bounded trace commands and daily trend verification.

**Pitfall — `[service] 4xx error response` is a `ConsoleErrors` log metric filter, not an ALB/API Gateway metric**: Some 4xx alarms (notably `[api-service] 4xx error response...`) live in the `ConsoleErrors` namespace and are driven by a CloudWatch log metric filter on the ECS service log group, not by native HTTP load-balancer metrics. The investigation must follow the **ECS console/log-derived alarm** recipe (inspect metric filter pattern, current trigger log context, project IDs in structured `error-response` logs) rather than the ALB/API Gateway metric flow. Do not assume the namespace is `AWS/ApplicationELB` or `AWS/ApiGateway` without checking `describe-alarms` first.

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

**Distinguishing real bugs from metric-filter noise**: The `ConsoleErrors` namespace is a coarse log substring filter. For Lambda functions, always cross-check the `AWS/Lambda` `Errors` metric. If `Errors > 0`, the alarm reflects a real invocation failure (unhandled exception, timeout, OOM). If `Errors == 0` and `Throttles == 0`, the log line is likely benign text caught by the broad filter. See `references/kds-consumer-event-timestamp-rangeerror.md` for a concrete real-bug example where the `RangeError` in `getValidEventTimestampInMilliseconds` elevates both console ERROR logs and Lambda runtime Errors. See `references/anomaly-delivery-monitoring-lambda-consoleerrors.md` for the counterpart false-positive pattern where routine inspection logs at ERROR level trip the metric filter while Lambda runtime Errors remain zero. See `references/message-event-consumer-delivery-policy-error.md` for the `message-event-consumer` case where handled `send_failure` logs with `failure_reason: 'delivery_policy_inspection_failed__global_frequency_limit'` are emitted at ERROR level and match the broad filter even though the Lambda completes normally. See `references/lambda-consoleerrors-handled-business-rejection.md` for a class-level index of handled business/configuration rejections that fire Lambda ConsoleErrors false positives (including `kakao-brand-message-delivery` 080 unsubscribe number skips).

**Pitfall — empty `current_trigger_contexts` on Lambda ConsoleErrors alarms**: The helper's Logs Insights query for the current alarm window may return zero results despite the metric filter having breached. This is common for Lambda log groups where Logs Insights ingestion lags behind metric-filter evaluation. When `logs.current_trigger_contexts` is empty but `can_answer_root_cause` is `true`, do not assume no logs exist. Run a bounded `aws logs filter-log-events` on `/aws/lambda/<actual_function_name>` using the exact metric datapoint timestamp ±5 min as the time window. Use the literal `filterPattern` from the metric filter configuration or a `like` query with the known ERROR substring. This fallback is read-only and deterministic; it resolves scope and trigger evidence that Logs Insights may miss.

**Pitfall — helper scope extraction misses campaign IDs in sanitized SQS payloads**: When the helper sanitizes `project_id` as `<project_id>` in JSON payload bodies, the `current_project_campaign_pairs` extractor may fail to pair it with the `campaign_id` from the same SQS record even when both are present. If `table_refs` or `project_ids` are available from other log fields (e.g., `delivery_result_<project_id>`), use them to establish the project scope and then manually read the `campaign_id` from the SQS payload lines.

**Pitfall — Node.js deprecation warnings can trigger `%ERROR%` metric filters**: Node.js 22.x cold-start deprecation warnings (e.g., `[DEP0040] DeprecationWarning: The punycode module is deprecated...`) may contain the literal string `ERROR` in their output line, breaching coarse `%ERROR|Status: timeout%` filters despite being benign warnings with no runtime failure. The first matching line in a scheduled Lambda invocation often has `undefined` as the request ID. Cross-check `AWS/Lambda Errors`; if zero, this is a false positive. In scheduled Lambdas like `payment-executor`, the deprecation warning often appears alongside handled business rejections caught in `try...catch` (e.g., `PaymentError: Payple payment failed`). See `references/nodejs-deprecation-warning-lambda-consoleerrors-false-positive.md` for triage.

**Pitfall — external provider API 5xx triggers Lambda ConsoleErrors when full error is console.error'd**: When a Lambda calls an external provider API (e.g., Naver Commerce, Cafe24, Kakao, NHN Cloud) and the provider returns HTTP 5xx, code that uses `try...catch (e) { console.error(e); }` dumps the full AxiosError/HTTP client object into logs. The coarse `%ERROR|Status: timeout%` metric filter matches the literal string `ERROR` inside the serialized error object, triggering a ConsoleErrors alarm even though Lambda runtime `Errors` remains 0 and the invocation completed normally. The root cause is the provider's transient outage, not a service bug. Classify as `no_action` when Lambda Errors=0 and the provider error indicates a transient issue. Long-term fix: downgrade handled external 5xx to WARN and log only compact non-sensitive fields (projectId, statusCode, providerMessage) instead of the full error object. See `references/lambda-consoleerrors-external-api-5xx.md`.

**Pitfall — Lambda `kakao-brand-message-delivery` 080 unsubscribe number missing**: When the `kakao-brand-message-delivery` Lambda processes a Kakao Bizmessage marketing batch and the project's `kakaoSenderInfo.unsubscribe_phone_number` is unset, the code logs `080 unsubscribe number missing, skipping batch: <projectId>/<campaignId>` at `ERROR` level (`services/lambda/kakao-brand-message-delivery/index.ts` line ~163). The batch is skipped normally and the Lambda continues, but the `%ERROR%` metric filter catches this line and triggers a `ConsoleErrors` alarm. Lambda runtime `Errors=0`. Scope is extractable directly from the log line (`projectId/campaignId`). Classify as `no_action` when isolated; use `needs_fix` only when recurrence becomes noisy. See `references/lambda-consoleerrors-handled-business-rejection.md`.

**Pitfall — `Notifly/ScheduledBatchDelivery DbInsert` JSON serialization / surrogate pair bug**: For `ScheduledBatchDelivery-P2-DbError` alarms (or any `Notifly/ScheduledBatchDelivery` alarm with `DbInsert outcome=error`), the Lambda log group `/aws/lambda/scheduled-batch-delivery` typically shows `invalid input syntax for type json` on INSERT into `delivery_result_<project_id>` or `delivery_failure_log_<project_id>`. The push-notification path in `scheduled-batch-delivery` most commonly leaks `[object Object]` via `toSendFailureLog` in `services/lambda/scheduled-batch-delivery/lib/push_utils.js` (`sender_info`, `request_body`, `response_body` are raw objects without `JSON.stringify`). The text-message path in `scheduled-batch-text-message-delivery` leaks via `prepareSendResultsToInsertForNHNCloud` (`extra_data` is a raw object). Even when `JSON.stringify` is present, PostgreSQL can reject the JSON with `code: '22P02'` and `detail: 'Unicode low surrogate must follow a high surrogate.'` when emoji in personalized message content have broken UTF-16 surrogate pairs. Inspect the pg error object's `detail` and `where` fields in Lambda logs to distinguish the two failure modes. Also note that the ConsoleErrors alarm `scheduled-batch-delivery lambda error` (metric filter `%ERROR|Status: timeout%`) catches these same ERROR logs, so the same triage applies even when the alarm namespace is `ConsoleErrors` rather than `Notifly/ScheduledBatchDelivery`. See `references/scheduled-batch-delivery-dbinsert-json-serialization-bug.md` for scope extraction, exact file/line targets for both Lambdas, and surrogate pair triage.

**Pitfall — using Slack message time instead of alarm datapoint time for log searches**: When the helper fails and manual `filter-log-events` is needed, anchor the search window precisely to the CloudWatch alarm's `StateReasonData.startDate` or `recentDatapoints[].timestamp` (from `describe-alarms`), converted exactly to epoch milliseconds. Slack `message_ts` and conversation start times can lag the actual alarm transition by minutes or hours; using them as the window anchor searches the wrong time range and may return zero matches even when the triggering logs exist.

**Pitfall — suppressible FCM network errors produce no ERROR logs**: In `send_push_v1_api.js`, network errors (`ECONNRESET`, `ETIMEDOUT`, `timeout`) are in `SUPPRESSIBLE_RESPONSE_MESSAGES`. When caught, `console.error` is NOT called. The only trace is an INFO-level EMF metric line with `error_codes: {"unknown":1}`. Do not conclude "no errors exist" just because `filter-log-events --filter-pattern ERROR` returns empty. Use the bounded Logs Insights queries in `references/scheduled-batch-delivery-fcm-send-error.md` instead.

**Pitfall — EMF metric alarm onset tightly correlated with Lambda deployment**: When an EMF metric alarm (e.g., `Notifly/ScheduledBatchDelivery`) fires and helper logs are empty, always check the consumer Lambda's `LastModified` timestamp via `get-function-configuration`. If `LastModified` falls within minutes of the alarm onset and metric history shows zero errors before that time, treat the deployment as the primary suspect before deep log analysis. Confirm with the deploying engineer, check for return-contract changes in handler subroutines (e.g., boolean → object), and consider rollback while root-causing.

**Percentile metric pitfall**: `get-metric-statistics` does not accept `p99` or any percentile statistic. The valid set is `SampleCount | Average | Sum | Minimum | Maximum`. For percentile alarms such as `*-FCMLatencyP99`, use `Maximum` as a conservative proxy, or switch to `get-metric-data` with `ExtendedStatistics=['p99']` if the exact value is required. See `references/scheduled-batch-delivery-fcm-latency.md` for a concrete FCM latency triage recipe.

**Pitfall — CloudWatch Logs API timestamp unit confusion**: `aws logs filter-log-events` expects `--start-time` and `--end-time` in **epoch milliseconds** (ms since 1970-01-01). Some AWS APIs (e.g., `describe-log-streams`) return `lastEventTimestamp` in milliseconds, but the raw value may be visually indistinguishable from seconds if you only glance at the integer. Always verify the unit before passing a value to `filter-log-events`; using seconds instead of milliseconds searches a time range seconds after 1970 and returns zero events, creating a false "no logs exist" conclusion. Convert with `date -d 'YYYY-MM-DD HH:00:00 UTC' +%s` and then multiply by 1000.

**Pitfall — Logs Insights ephemeral field collision**: CloudWatch Logs Insights auto-extracts top-level JSON keys as query fields. If a log line contains `"status":400`, then `status` is already available without parsing. Adding `parse @message '\"status\":*' as status` in the same query raises `MalformedQueryException: Ephemeral field is already defined: status`. Remove redundant `parse` clauses for fields already present as top-level JSON keys, or rename the alias (e.g., `as parsed_status`).

**Pitfall — `kds-consumer` null byte → PG error → timeout → ConsoleErrors false positive**: When the `kds-consumer` Lambda processes events containing `\u0000` (null byte) in `event_params`, the INSERT into `event_intermediate_counts_<project_id>` fails with PostgreSQL `22021` (`invalid byte sequence for encoding "UTF8": 0x00`). The code retries up to 10 times via `async-retry`, exhausting the Lambda timeout (900s) and producing a `REPORT ... Status: timeout` line. The `ConsoleErrors` metric filter (`%ERROR|Status: timeout%`) matches this REPORT line, triggering the alarm even though there is no unhandled Lambda exception. Simultaneously, the actual ERROR log line (`invalid byte sequence...`) may be matched by the same filter. Cross-check `AWS/Lambda Errors` to confirm whether this is a runtime crash (real bug) or a retry-timeout from a known data-quality issue. Root cause is usually missing sanitization of `\u0000` in `constructEventIntermediateCountData()` (`services/lambda/kds-consumer/lib/event_counter_utils.ts`). See `references/kds-consumer-null-byte-utf8-timeout.md`.

**Pitfall — Aurora reader conflict (`canceling statement due to conflict with recovery`)**: Aurora PostgreSQL may cancel queries on reader instances during WAL replay or Zero-Downtime Patching (ZDP), producing `canceling statement due to conflict with recovery` (PG error 40001, detail: `User query may not have access to page data due to replica disconnect.`). This affects Lambdas (e.g., `user-journey-node-runner` → `Failed to execute segment branching node`) and ECS services (e.g., `api-service` → `Failed to get user data`). Cross-check `AWS/Lambda Errors`: if zero, the failure is transient infrastructure-level, not a code bug. Pattern is sporadic when isolated; classify as `no_action`. If it spikes to hundreds or thousands in a single 15-minute window, use 15-minute buckets and RDS `ReadLatency` to judge recovery. See `references/rds-aurora-replica-recovery-conflict.md` for the full triage recipe.

**Pitfall — `filter-log-events` colon in `filterPattern`**: CloudWatch Logs `filter-log-events` rejects `?Status: timeout` with `InvalidParameterException: Invalid character(s) in term ':'`. Use stream-first enumeration (`describe_log_streams` + `filter_log_events` with no filter pattern) or a simpler term like `ERROR` instead.

**Pitfall — Lambda timeout does not emit ERROR log lines**: Lambda timeout produces `REPORT ... Status: timeout`, not a `console.error` or ERROR-level log line. Searching `filter-log-events` with `ERROR` returns zero results even when every invocation times out. Always inspect raw log streams for `REPORT` lines when investigating Lambda consumer failures.

**Pitfall — newly deployed Lambda consumer consistent timeout**: When Lambda `LastModified`, EventSourceMapping `LastModified`, and queue `CreatedTimestamp` are all within hours or minutes of the alarm, and every invocation times out at exactly `Timeout` duration, the consumer cannot reach its dependency (VPC, security group, secrets, DB, external API). This is a deployment issue, not a traffic spike or regression on a stable system. See `references/sqs-dlq-new-consumer-deployment-failure.md`.

**Pitfall — Lambda timeout with empty log gap after successful work**: When a Lambda `REPORT ... Status: timeout` is the sole alarm trigger and no ERROR application logs exist between `START` and `REPORT`, check whether `SendResultsInsertQuery` or other "work complete" logs appear minutes or hours before `END`. If work completed successfully but the invocation remained alive, the hang is likely an unawaited Promise, a background timer, or a network call without proper client-side timeout (e.g., SES `sendEmail`). Cross-check `AWS/Lambda` `Duration` (`Maximum`) for the 900,000ms spike and `Errors` (which may register in the invocation's *start* minute rather than the timeout minute). Inspect SQS `RedrivePolicy.maxReceiveCount`; a value of `1` means the timed-out message is immediately DLQed with zero retries. If DLQ is empty and retry succeeded, delivery was not lost. See `references/lambda-timeout-empty-log-gap.md` for the full triage recipe.

**Pitfall — Lambda Redis cluster slot refresh failure causes timeout hang**: When `current_trigger_contexts` shows `[ioredis] Unhandled error event: ClusterAllFailedError: Failed to refresh slots cache.` followed by `REPORT ... Status: timeout`, the root cause is usually a Redis cluster connectivity or topology change. The Lambda hangs because `@notifly/redis` `CACHE` profile sets `enableOfflineQueue: true`, causing ioredis to queue commands indefinitely instead of failing fast. Check Lambda `LastModified` for deployment correlation, inspect `packages/redis/src/index.ts` profile configs, and verify the `REDIS_HOST` environment variable. See `references/lambda-redis-clusterallfailederror-timeout.md` for bounded trace commands and classification guidance.

**Pitfall — Lambda Redis cluster error without timeout (handled dependency failure)**: Some Lambdas wrap each Redis call in a service-level `try...catch` with a fallback return (e.g., `ses-bounce-tracker/lib/redis.ts`). The invocation completes normally, `AWS/Lambda Errors = 0`, and `Duration` stays below `Timeout`. However, ioredis still emits `ERROR Error: Cluster isn't ready...` for every failed command, and the `%ERROR|Status: timeout%` metric filter matches the literal `ERROR` substring. Do not dismiss the alarm solely because `Errors = 0`; check whether the daily ERROR log count is increasing and whether the Lambda performs safety-critical work (e.g., bounce-rate campaign termination). See `references/lambda-redis-clusterallfailederror-timeout.md` § "Variant B".

**Pitfall — Lambda SQS batch + maxReceiveCount=1 DLQ amplification**: When a Lambda consumer uses SQS `BatchSize > 1` (e.g., `BatchSize: 10`) with `maxReceiveCount: 1`, a single Lambda timeout affects ALL messages in that batch, immediately DLQing them with zero retries. For `email-delivery`, this means ~10 messages × ~50 recipients = ~500 undelivered emails per timeout. The metric filter `%ERROR|Status: timeout%` catches only the REPORT line, so the alarm fires once per timeout but the actual DLQ impact is multiplied by batch size. When triaging, always:
1. Check `EventSourceMapping` `BatchSize` and queue `maxReceiveCount`
2. Cross-check DLQ depth before and after the timeout window
3. Inspect DLQ message bodies for `project_id`/`campaign_id` scope attribution
4. Note whether the Lambda recovered to normal Duration afterward (indicates transient spike, not code bug)
5. See `references/lambda-timeout-empty-log-gap.md` § "Batch + maxReceiveCount=1 impact" for the email-delivery specific pattern.

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
