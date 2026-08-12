# Check Alert Discovery and Enrichment Design

## Context

Two Hashimoto alert investigations exposed related gaps in the deterministic
`check` helper:

1. `notifly-lambda-high-duration` is an account-wide `AWS/Lambda Duration Sum`
   alarm with no `FunctionName` dimension. The helper cannot identify the
   contributing functions, so Lambda logs and DB correlation never run.
2. `hermes-agent-profile-status` is a metric-math alarm over
   `HermesProfileStatus`. Existing Hermes observability code can attribute
   profile-pressure events to sessions, but it activates only for a top-level
   `HermesServiceHealthy` metric and therefore misses this alarm.

The resulting LLM turns either stop with missing context or start an expensive
manual investigation loop. The helper must discover concrete resources before
running datasource-specific collectors.

## Goals

- Resolve the top Lambda contributors for dimensionless Lambda alarms.
- Feed discovered Lambda names and log groups into existing detailed
  collectors during the same helper invocation.
- Detect directly and indirectly DB-related alarms using structured alarm
  metadata, delimiter-aware alarm-name signals, and observed log evidence.
- For DB-related alarms without an explicit RDS identifier, inspect the
  PI-enabled members of the Notifly production Aurora cluster as bounded,
  correlation-only evidence.
- Recognize metric-math `HermesProfileStatus` alarms, identify breaching
  profiles, and attribute them to the most defensible session and tool.
- Keep collection deterministic, read-only, compact, and bounded so the LLM
  does not need to reconstruct helper-covered AWS queries.

## Non-Goals

- Changing CloudWatch alarm or Terraform definitions.
- Writing to AWS, databases, Slack, or profile state databases.
- Scanning every Lambda, RDS instance, log group, repository, or session.
- Replacing the existing collector registry with a generic dependency graph.
- Claiming DB causation from coincident production-cluster load alone.

## Architecture

Use two stages while retaining the existing collector registry:

1. **Discovery** classifies the complete alarm shape and resolves candidate
   resources.
2. **Enrichment** runs existing and new detailed collectors only for those
   resources.

The data flow is:

```text
raw alarm + history
  -> alarm shape classification
  -> bounded resource discovery
  -> Lambda / logs / RDS PI / Hermes enrichment
  -> scope attribution
  -> consistent assessment
  -> sections or compact JSON
```

### Alarm Shape

Create `alarm_shape.py` as the single source of truth for alarm recognition.
It inspects top-level metric fields and every `Metrics[]` expression or
`MetricStat`. It returns immutable structured data containing:

- all observed namespaces, metric names, dimensions, and expression text;
- whether the alarm is a dimensionless Lambda alarm;
- whether it is a Hermes profile-health alarm;
- DB relevance level and the exact evidence supporting it;
- explicit RDS cluster or instance identifiers when present.

Collectors and `assessment.py` must consume this shared classification instead
of maintaining separate metric-name heuristics.

### Discovery Results and Ordering

Use ordered discovery collectors instead of one all-purpose collector:

1. `alarm_shape` classifies the raw alarm without network calls.
2. `lambda_discovery` resolves at most five ranked functions and derives their
   Lambda log groups.
3. `hermes_observability` resolves breaching profiles when the shared shape
   identifies a Hermes profile-health alarm.
4. `metric_filters` and `logs_insights` run with explicit and discovered log
   groups.
5. `rds_context` combines the preliminary alarm-name/namespace classification
   with current log evidence, then resolves an explicit or production-fallback
   RDS target.
6. `rds_performance_insights` enriches only the resolved PI-enabled targets.

The `alarm_shape` result records preliminary DB relevance. The `rds_context`
result records final `db_relevance`, exact evidence, target provenance, and
topology. Downstream collectors use effective resource lists formed from the
original detected values plus discovery values. Original `CollectorContext`
inputs are not mutated.

## Lambda Discovery

Activate top-offender discovery when the alarm shape contains an `AWS/Lambda`
metric but has no `FunctionName` dimension. For `Duration`, use one CloudWatch
Metrics Insights query grouped by `FunctionName`, ordered by `SUM(Duration)`,
and limited to five results in the current alarm window.

For the discovered functions, use one batched `GetMetricData` request for:

- `Duration` sum and average;
- `Invocations` sum;
- `Errors` sum;
- `Throttles` sum.

This distinguishes high aggregate runtime caused by healthy concurrency from
slow or failing invocations. Derive `/aws/lambda/<function>` groups and issue
one multi-log-group Logs Insights query for timeout, exception, database,
connection, query, and lock signatures. Preserve at most ten signatures.

The investigation window is anchored to the latest ALARM transition and the
alarm evaluation period, capped at 30 minutes. The implementation must not
list every function and issue one request per function.

## DB Relevance and RDS Targeting

DB relevance is `confirmed` when any of the following applies:

- the alarm contains `AWS/RDS` metrics or RDS dimensions;
- an expression names RDS metrics or identifiers;
- current-window logs contain a concrete query, connection, deadlock, driver,
  or ORM failure.

DB relevance is `candidate` when delimiter-aware alarm-name or service signals
include terms such as `db`, `database`, `aurora`, `rds`, `sql`, `postgres`,
`writer`, `reader`, or `replica`. A generic term such as `timeout` is
insufficient by itself. Matching `db` must use token boundaries so unrelated
names do not become DB alarms.

RDS target precedence is:

1. cluster or instance explicitly named by alarm dimensions or expressions;
2. a target identified from current service or log evidence;
3. `notifly-db-prod-cluster` when DB relevance is at least `candidate` and no
   stronger target exists.

The third path is labeled
`target_source: production_default_correlation`. It describes the cluster,
selects at most four PI-enabled members, and queries at most five SQL groups per
member in the same alarm window. Its output is correlation evidence and cannot
alone establish root cause.

## Hermes Profile Attribution

Recognize profile-health alarms when `HermesProfileStatus` appears in a
top-level metric, `MetricStat`, Metrics Insights expression, or the canonical
alarm shape. Query profile-grouped metric values for the alarm window and keep
only profiles that breached the alarm threshold.

For each breaching profile:

1. Query the fixed Hermes observability log group for matching
   `profile_pressure` open and recovery events.
2. Open that profile's `state.db` read-only.
3. Prefer the existing exact session-prefix and active-tool-interval match.
4. If no pressure event identifies a session, return at most three sessions
   whose execution interval overlaps the alarm window as low-confidence
   candidates.

An exact event, session, and tool match is `observed` evidence. A time-overlap
candidate must never be described as the definite cause.

## Assessment Rules

### Dimensionless Lambda

- Top function plus a current timeout or error signature is sufficient for a
  root-cause answer.
- A top function with zero errors and throttles, rapid alarm recovery, and a
  repeated healthy batch pattern is sufficient for a workload-spike answer.
- A ranked function without a mechanism keeps `can_answer_root_cause=false`.

### DB-Related Alerts

- For a direct RDS alarm, its explicit target plus current PI SQL is sufficient
  to identify the database load source.
- For a Lambda, ECS, or DLQ alarm, PI remains correlated evidence unless a
  current service error or query fingerprint ties the service to that SQL.
- Production-fallback PI data alone cannot make
  `can_answer_root_cause=true`.
- Existing sharded-table mapping continues to provide project and product
  scope when a SQL fingerprint contains a project suffix.

### Hermes Profile Status

- Breaching profile plus pressure event and exact tool interval is sufficient
  for a root-cause answer.
- A profile plus overlapping session is reported as a candidate.
- A profile without session evidence reports status only and remains
  incomplete for session attribution.

Run a final consistency check so `can_answer_root_cause=true` cannot coexist
with missing mandatory context. Do not emit manual follow-ups for resources the
discovery stage already resolved.

## Evidence Labels and Response Contract

Evidence is labeled consistently:

- `explicit`: named by the alarm or an AWS resource relationship;
- `observed`: confirmed in current-window metrics, logs, PI, or session state;
- `correlated`: coincident evidence without a proven causal link.

The Korean Slack response retains the existing fields: cause, scope,
frequency, customer impact, immediate action, and action items. It names the
function, DB role, SQL fingerprint, profile, session, and tool only when their
evidence level supports the wording.

## Bounds and Failure Handling

- Maximum Lambda offenders: 5.
- Maximum Lambda log signatures: 10.
- Maximum RDS PI instances: 4.
- Maximum SQL groups per instance: 5.
- Maximum detailed investigation window: 30 minutes.
- Maximum serialized compact result: 10 KiB, enforced by deterministic array
  and string trimming while preserving assessment and current evidence.

Each collector returns `not_applicable`, `collected`, `partial`, or `error`
with a sanitized reason. Access denial, disabled PI, unavailable metrics, and
retention expiry are not retried blindly and do not abort unrelated collectors.

## Test Strategy

### Alarm Shape Unit Tests

- Parse top-level Lambda and RDS alarms.
- Parse metric-math expressions containing `HermesProfileStatus` and RDS
  Metrics Insights queries.
- Recognize delimiter-aware DB alarm names.
- Reject unrelated names containing incidental character sequences.

### Discovery Unit Tests

- A dimensionless Lambda Duration alarm issues a bounded Metrics Insights query
  and ranks no more than five functions.
- Discovered Lambda names and derived log groups reach detailed collectors in
  the same helper run.
- Explicit RDS targets take precedence over the production fallback.
- A candidate DB alarm with no explicit target resolves the fallback cluster
  and marks it correlation-only.
- A non-DB alarm never queries the fallback cluster.

### Hermes Regression Tests

- The actual metric-math profile-status alarm shape activates Hermes
  observability.
- Breaching profiles are extracted from grouped metric results.
- Exact pressure/session/tool matching produces the full parent and child
  session links.
- A time-overlap-only match is labeled as a candidate, not a cause.

### Assessment and Output Tests

- Healthy aggregate Lambda batch load can resolve as `no_action` only with the
  required zero-error and recovery evidence.
- Production-fallback PI evidence alone cannot establish DB causation.
- `can_answer_root_cause` never conflicts with missing mandatory context.
- Compact output is at most 10 KiB and retains assessment, current-window
  evidence, and evidence labels.

### Live Read-Only Validation

Run the helper with the Hashimoto environment against:

- `notifly-lambda-high-duration`;
- `hermes-agent-profile-status`;
- one explicit Aurora/RDS alarm;
- one unrelated non-DB alarm.

The first must return ranked Lambda contributors, the second must identify
breaching profiles and session evidence when present, the third must prefer its
explicit DB target, and the fourth must not query production PI. Validation
must not mutate AWS or profile state.

## Source and Delivery Constraints

- Modify the tracked source under
  `ignored/local/skills/software-development/check`, which is the source of
  truth for the live profile symlink.
- Work directly on the primary `main` checkout. Do not create a feature branch
  or a separate worktree.
- Preserve unrelated dirty worktree changes.
- Add focused commits for alarm classification, resource discovery, Hermes
  recognition, and assessment/output behavior.
- The stale clean `alert/lambda-db-pi-context` worktree contains no
  implementation and is not an input to this work.

## Success Criteria

- The helper identifies concrete Lambda contributors for the dimensionless
  alarm without an LLM-driven AWS command loop.
- DB-related direct and indirect alarms obtain bounded PI context with explicit
  target provenance and no false causation claim.
- The metric-math Hermes profile-status alarm identifies the breaching profiles
  and returns exact or clearly labeled candidate sessions.
- Existing RDS, Lambda, SQS, log, scope, and Hermes health tests continue to
  pass.
- Compact helper output remains within 10 KiB.
