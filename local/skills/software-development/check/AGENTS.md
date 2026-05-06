# Check Skill Maintenance Guide

This directory contains the Notifly alert investigation skill and its helper.
Keep this guide focused on how to maintain `scripts/notifly_alert_context/`.

## Helper Entry Point

The public helper path is:

```bash
scripts/collect_notifly_alert_context.py
```

That file is intentionally only a thin wrapper. Do not put investigation logic
there. The implementation lives in the package:

```text
scripts/notifly_alert_context/
```

The CLI contract should remain stable:

```bash
python scripts/collect_notifly_alert_context.py --text '<alert text>'
```

The helper emits compact JSON by default. Slack-facing prose is handled by
`SKILL.md`; the helper should provide structured evidence, not final wording.

## Package Layout

- `cli.py`: Parses arguments, detects initial artifacts, runs collectors, maps
  project IDs, assembles the final helper JSON.
- `config.py`: Central place for tunables and domain constants such as default
  AWS region, repo path, output caps, known phrases, log sanitization patterns,
  and campaign-capable table prefixes.
- `collectors.py`: Registry-driven collector orchestration. New reusable data
  collection steps should usually be added here.
- `aws_collectors.py`: AWS API collectors for CloudWatch metrics/history, SQS,
  Lambda, RDS, Performance Insights, and DynamoDB project mapping.
- `logs.py`: CloudWatch Logs Insights query construction/execution and compact
  log evidence extraction. Keep queries vetted and bounded.
- `detect.py`: Pure text/log/alarm artifact extraction. This should stay
  side-effect free.
- `scope.py`: Project/campaign/user-journey attribution and scope merging.
- `assessment.py`: Checks whether required context is missing and emits
  `missing_required_context`, `can_answer_root_cause`, and
  `required_followups`.
- `repo.py`: Local source/Terraform search with narrow context windows.
- `text.py`: Sanitization, truncation, signatures, and Logs Insights escaping.

## Collection Pipeline

The high-level flow is:

1. `cli.py` loads profile/global env files.
2. Initial text detectors parse alarm name, region, log groups, project IDs,
   campaign IDs, user-journey IDs, queues, services, and Lambda names.
3. AWS session, STS identity, CloudWatch alarm metadata, and alarm history are
   collected.
4. `run_collectors()` executes `COLLECTOR_REGISTRY` in order.
5. `scope.merge_scope_detections()` merges initial IDs, current log details,
   Logs Insights project/campaign pairs, and RDS Performance Insights table
   suffix evidence.
6. DynamoDB project mapping resolves project/product names for known
   `project_id` values.
7. Source search runs against the configured repo path.
8. `assessment.assess_helper_context()` decides whether the helper output is
   enough for root-cause analysis or which follow-ups are required.

Collector order matters because later collectors may depend on previous
results. For example, `logs_insights` uses `metric_filters`, and
`rds_performance_insights` uses `rds_context`.

## Adding a New Alert Pattern

Prefer generic alarm-shape handling over service-name or alarm-name branches.
Collectors should be selected from CloudWatch namespace, metric name,
dimensions, metric filters, log groups, and safe payload fields.

Use this decision path:

1. If the pattern only needs another regex, phrase, table prefix, or cap, update
   `config.py` or the relevant pure detector in `detect.py`.
2. If the pattern needs a new AWS/API data source, add a small read-only helper
   in `aws_collectors.py` and register it in `collectors.py`.
3. If the pattern needs a Logs Insights query, add a fixed vetted query template
   in `logs.py`. Do not make the LLM invent query syntax at runtime.
4. If the pattern changes project/campaign/user-journey attribution, update
   `scope.py`.
5. If the pattern changes whether a final answer is allowed, update
   `assessment.py`.
6. Add or update focused tests in `tests/local_skills/`.

Most new monitoring patterns should require one small collector function plus
one `CollectorSpec(...)` entry, or a config/detector-only change. Avoid adding
new orchestration branches in `cli.py`.

## Hard-Coding Rules

Allowed domain constants belong in `config.py`. Examples:

- default AWS region
- default repo path
- DynamoDB project table name
- known stable phrases
- table-family prefixes that can carry campaign or user-journey context
- max query/result/sample caps

Do not hard-code individual service names, alarm names, Slack channel IDs,
project names, campaign IDs, or one-off incident text in helper logic. Use tests
for concrete examples, not production branches.

## Logs Insights Rules

Keep log collection bounded and deterministic:

- never dump raw logs into helper output
- group samples by sanitized signatures
- include current-alarm-window evidence when available
- prefer current trigger context over 7d/30d historical signatures
- use `_run_logs_insights_query()` through the public wrapper functions
- stop broad scans when no stable filter terms can be inferred

If a new log pattern is needed, add a fixed query or filter-term extraction rule
instead of adding manual Slack-session instructions.

## Scope Attribution Rules

Final answers require project/product scope and exactly one of campaign or
user journey when evidence supports it.

Important rules:

- Current alarm-window project/campaign pairs outrank historical samples.
- Do not combine a standalone campaign ID with an unrelated sharded table suffix
  from another log line.
- Sharded table suffixes are table references unless they are tied to the
  current trigger or Performance Insights SQL evidence.
- RDS answers should prioritize current focus-window PI load over broad
  historical top SQL.

Scope logic belongs in `scope.py`, not `cli.py`.

## Tests

Run the focused regression suite after helper changes:

```bash
venv/bin/python -m pytest tests/local_skills/test_check_helper_context.py -q
```

Also run a syntax check when touching helper modules:

```bash
python3 -m py_compile \
  local/skills/software-development/check/scripts/collect_notifly_alert_context.py \
  local/skills/software-development/check/scripts/notifly_alert_context/*.py \
  tests/local_skills/test_check_helper_context.py
```

When adding a new collector, include at least one test that proves the registry
order or scope/assessment behavior that the new collector depends on.
