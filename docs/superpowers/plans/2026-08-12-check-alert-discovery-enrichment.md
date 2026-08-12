# Check Alert Discovery and Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the deterministic `check` helper resolve dimensionless Lambda offenders, bounded DB/PI correlation, and metric-math Hermes profile/session attribution without an LLM-driven manual investigation loop.

**Architecture:** Keep the registry-driven helper and add ordered discovery before datasource enrichment. A pure alarm-shape classifier feeds Lambda discovery and Hermes recognition; current-window logs then finalize DB relevance and RDS target selection before Performance Insights runs. Assessment and compact output consume the same structured evidence so collection and final-answer gating cannot diverge.

**Tech Stack:** Python 3.11, boto3 CloudWatch/RDS/Performance Insights/Logs APIs, SQLite read-only profile state, pytest 9, existing Notifly `check` helper package.

## Global Constraints

- Work directly in `/home/ubuntu/.hermes/hermes-agent` on branch `main`; do not create a branch or worktree.
- Preserve every unrelated dirty or staged change and commit only the paths named by each task.
- Treat `ignored/local/skills/software-development/check` as the tracked source of truth for live profile symlinks.
- All AWS and SQLite operations are read-only.
- Do not add a model tool, dependency, environment variable, alarm-name special case, Slack channel ID, project ID, campaign ID, or incident-specific production branch.
- Use `notifly-db-prod-cluster` only as the approved production fallback after DB relevance reaches `candidate` or `confirmed`.
- Cap Lambda offenders at 5, Lambda signatures at 10, PI instances at 4, PI SQL groups at 5, and detailed windows at 30 minutes.
- Preserve the compact output limit of 10,000 UTF-8 bytes.
- Every task follows red-green-refactor and ends with a focused commit.

## File Map

**Create**

- `ignored/local/skills/software-development/check/scripts/notifly_alert_context/alarm_shape.py`: pure alarm classification.
- `tests/local_skills/test_check_alarm_shape.py`: top-level and metric-math shape regressions.
- `tests/local_skills/test_check_resource_discovery.py`: Lambda discovery, registry propagation, DB targeting, and PI provenance.

**Modify**

- `ignored/local/skills/software-development/check/scripts/notifly_alert_context/config.py`: caps and DB domain constants.
- `ignored/local/skills/software-development/check/scripts/notifly_alert_context/aws_collectors.py`: bounded window, Lambda discovery, RDS target resolution, and PI provenance.
- `ignored/local/skills/software-development/check/scripts/notifly_alert_context/logs.py`: current-window Lambda signature query.
- `ignored/local/skills/software-development/check/scripts/notifly_alert_context/collectors.py`: ordered discovery and effective resource helpers.
- `ignored/local/skills/software-development/check/scripts/notifly_alert_context/hermes_observability.py`: profile metric and session attribution.
- `ignored/local/skills/software-development/check/scripts/notifly_alert_context/assessment.py`: shared-shape answer gating and compact output.
- `ignored/local/skills/software-development/check/scripts/notifly_alert_context/cli.py`: discovery result propagation.
- `ignored/local/skills/software-development/check/SKILL.md`: helper-first response guidance.
- `tests/local_skills/test_check_hermes_observability.py`: metric-math and candidate-session regressions.
- `tests/local_skills/test_check_helper_context.py`: gating and budget regressions.
- `ignored/local/skills/software-development/check/tests/test_assessment.py`: assessment regressions.

---

### Task 1: Add One Pure Alarm-Shape Classifier

**Files:**
- Create: `ignored/local/skills/software-development/check/scripts/notifly_alert_context/alarm_shape.py`
- Modify: `ignored/local/skills/software-development/check/scripts/notifly_alert_context/config.py:5-19`
- Create: `tests/local_skills/test_check_alarm_shape.py`

**Interfaces:**
- Produces `classify_alarm_shape(alarm: Any, *, text: str = "", service_names: Sequence[str] = ()) -> Dict[str, Any]`.
- Stable result keys: `status`, `namespaces`, `metric_names`, `dimension_names`, `expressions`, `dimensionless_lambda`, `hermes_profile_status`, `hermes_instance_ids`, and `db_relevance`.
- `db_relevance` contains `level`, `evidence`, `explicit_cluster_ids`, and `explicit_instance_ids`.

- [ ] **Step 1: Write the failing classifier tests**

Create `tests/local_skills/test_check_alarm_shape.py` using the existing `SKILL_ROOT/scripts` import setup. Add these assertions:

```python
from notifly_alert_context.alarm_shape import classify_alarm_shape


def test_dimensionless_lambda_duration_shape() -> None:
    result = classify_alarm_shape({
        "_alarm_type": "MetricAlarm",
        "AlarmName": "notifly-lambda-high-duration",
        "Namespace": "AWS/Lambda",
        "MetricName": "Duration",
        "Statistic": "Sum",
        "Dimensions": [],
    })
    assert result["dimensionless_lambda"] is True
    assert result["namespaces"] == ["AWS/Lambda"]
    assert result["metric_names"] == ["Duration"]


def test_metric_math_hermes_profile_status_shape() -> None:
    result = classify_alarm_shape({
        "AlarmName": "hermes-agent-profile-status",
        "Metrics": [{
            "Id": "profiles",
            "Expression": (
                'SELECT MAX(HermesProfileStatus) FROM SCHEMA("CWAgent", '
                'InstanceId, Profile, metric_type) '
                "WHERE InstanceId = 'i-test' GROUP BY Profile"
            ),
        }],
    })
    assert result["hermes_profile_status"] is True
    assert result["metric_names"] == ["HermesProfileStatus"]
    assert result["hermes_instance_ids"] == ["i-test"]


def test_metric_math_rds_shape_extracts_cluster() -> None:
    result = classify_alarm_shape({
        "AlarmName": "notifly-db-prod-instance-high-cpu-usage",
        "Metrics": [{
            "Id": "cpu",
            "Expression": (
                'SELECT MAX(CPUUtilization) FROM SCHEMA("AWS/RDS", '
                "DBInstanceIdentifier) WHERE tag.DBClusterIdentifier = "
                "'notifly-db-prod-cluster' GROUP BY DBInstanceIdentifier"
            ),
        }],
    })
    assert result["db_relevance"]["level"] == "confirmed"
    assert result["db_relevance"]["explicit_cluster_ids"] == [
        "notifly-db-prod-cluster"
    ]


def test_db_token_matching_is_delimiter_aware() -> None:
    unrelated = classify_alarm_shape({
        "AlarmName": "job-results-udp-latency",
        "Namespace": "Custom/Worker",
        "MetricName": "Latency",
        "Dimensions": [],
    })
    candidate = classify_alarm_shape({
        "AlarmName": "worker-db-query-latency",
        "Namespace": "Custom/Worker",
        "MetricName": "Latency",
        "Dimensions": [],
    })
    assert unrelated["db_relevance"]["level"] == "none"
    assert candidate["db_relevance"]["level"] == "candidate"
```

- [ ] **Step 2: Run the test and verify the missing-module failure**

```bash
venv/bin/python -m pytest tests/local_skills/test_check_alarm_shape.py -q
```

Expected: `ModuleNotFoundError: notifly_alert_context.alarm_shape`.

- [ ] **Step 3: Add the exact constants to `config.py`**

```python
MAX_LAMBDA_OFFENDERS = 5
MAX_LAMBDA_LOG_SIGNATURES = 10
MAX_DISCOVERY_WINDOW_SECONDS = 30 * 60
DEFAULT_PRODUCTION_RDS_CLUSTER_ID = "notifly-db-prod-cluster"

DB_ALARM_NAME_TOKENS = frozenset({
    "db", "database", "aurora", "rds", "sql", "postgres", "postgresql",
    "mysql", "writer", "reader", "replica", "deadlock",
})

DB_LOG_PATTERNS = (
    re.compile(r"(?i)\b(query|sql|deadlock|transaction|connection pool)\b"),
    re.compile(r"(?i)\b(psycopg|postgres|sequelize|typeorm|prisma|jdbc)\b"),
    re.compile(r"(?i)\b(connection|query)\b.{0,40}\b(timeout|timed out|refused|reset)\b"),
)
```

Increase `MAX_LOG_QUERY_GROUPS` from 4 to 5 so all bounded offender groups fit in one current-window query.

- [ ] **Step 4: Implement the pure classifier**

In `alarm_shape.py`, structurally gather top-level fields and every `MetricStat.Metric` before parsing expressions. Use these exact patterns:

```python
TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")
NAMESPACE_PATTERN = re.compile(r'SCHEMA\(["\']?([^,"\')]+)')
METRIC_PATTERN = re.compile(
    r"(?i)\b(MAX|MIN|SUM|AVG|AVERAGE)\s*\(\s*([A-Za-z][A-Za-z0-9_]*)\s*\)"
)
CLUSTER_PATTERN = re.compile(
    r"(?i)(?:tag\.)?DBClusterIdentifier\s*=\s*['\"]([^'\"]+)['\"]"
)
INSTANCE_PATTERN = re.compile(
    r"(?i)DBInstanceIdentifier\s*=\s*['\"]([^'\"]+)['\"]"
)
HERMES_INSTANCE_PATTERN = re.compile(
    r"(?i)InstanceId\s*=\s*['\"]([^'\"]+)['\"]"
)
```

Classify `AWS/RDS`, RDS dimensions, and RDS expressions as `confirmed`. Classify delimiter-separated alarm/service DB tokens as `candidate`. A generic `timeout` token cannot establish DB relevance. Return stable-order lists, not set iteration order.

- [ ] **Step 5: Run tests and syntax checks**

```bash
venv/bin/python -m pytest tests/local_skills/test_check_alarm_shape.py -q
python3 -m py_compile \
  ignored/local/skills/software-development/check/scripts/notifly_alert_context/alarm_shape.py \
  ignored/local/skills/software-development/check/scripts/notifly_alert_context/config.py
```

Expected: four tests pass and both files compile.

- [ ] **Step 6: Commit Task 1 only**

```bash
git add -f \
  ignored/local/skills/software-development/check/scripts/notifly_alert_context/alarm_shape.py \
  ignored/local/skills/software-development/check/scripts/notifly_alert_context/config.py
git add tests/local_skills/test_check_alarm_shape.py
git commit -m "feat(check): classify metric math alarm shapes"
```

---

### Task 2: Discover Dimensionless Lambda Offenders

**Files:**
- Modify: `ignored/local/skills/software-development/check/scripts/notifly_alert_context/aws_collectors.py:274-295,565-632`
- Create: `tests/local_skills/test_check_resource_discovery.py`

**Interfaces:**
- Produces `alarm_focus_window(alarm, history) -> tuple[datetime, datetime]`, capped at 30 minutes.
- Produces `collect_lambda_top_offenders(session, alarm, history, alarm_shape) -> Dict[str, Any]`.
- Result keys: `status`, `window_start`, `window_end`, `query`, `offenders`, `derived_lambda_names`, and `derived_log_groups`.
- Each offender contains `function_name`, `duration_sum_ms`, `duration_avg_ms`, `invocations`, `errors`, `throttles`, and `evidence_level='observed'`.

- [ ] **Step 1: Write bounded-query tests**

Create fake session and CloudWatch clients that record `get_metric_data` calls and return six grouped Duration series. Assert the result keeps exactly the top five, derives `/aws/lambda/<name>` groups, and every request window is at most `MAX_DISCOVERY_WINDOW_SECONDS`. Add tests that dimensioned/non-Lambda alarms return `not_applicable` without requesting a client and AccessDenied returns one sanitized `error` result without retry.

The main assertion is:

```python
assert [row["function_name"] for row in result["offenders"]] == [
    "scheduled-batch-delivery",
    "kds-consumer",
    "user-journey-node-runner",
    "segment-publisher-trigger",
    "anomaly-delivery-monitoring",
]
assert len(session.cloudwatch.calls) == 2
```

- [ ] **Step 2: Run tests and verify missing symbols**

```bash
venv/bin/python -m pytest tests/local_skills/test_check_resource_discovery.py -q
```

Expected: imports for `alarm_focus_window` and `collect_lambda_top_offenders` fail.

- [ ] **Step 3: Implement the bounded alarm window**

Anchor to `history.latest_alarm_transition.timestamp`; derive the natural evaluation range from `Period * EvaluationPeriods`, add at most five minutes after the anchor, and clamp the total span:

```python
if (end - start).total_seconds() > MAX_DISCOVERY_WINDOW_SECONDS:
    start = end - timedelta(seconds=MAX_DISCOVERY_WINDOW_SECONDS)
```

With no anchor, use current time and a 15-minute lookback.

- [ ] **Step 4: Implement one Metrics Insights offender query**

Use this exact expression with `Id='lambda_duration_sum'`, `Label="${PROP('Dim.FunctionName')}"`, and `ReturnData=True`:

```python
expression = (
    'SELECT SUM(Duration) FROM SCHEMA("AWS/Lambda", FunctionName) '
    'GROUP BY FunctionName ORDER BY SUM() DESC '
    f'LIMIT {MAX_LAMBDA_OFFENDERS}'
)
```

Rank by maximum current-window value, reject empty labels, and keep five.

- [ ] **Step 5: Implement one peer-metric batch**

Build at most 25 `MetricDataQueries`: five functions multiplied by Duration sum, Duration average, Invocations sum, Errors sum, and Throttles sum. Use valid index IDs such as `f0_duration_sum`. Merge values into offender rows. Return `partial` if peer metrics fail after offender discovery; return `error` only if offender discovery fails.

- [ ] **Step 6: Run focused tests and compile**

```bash
venv/bin/python -m pytest \
  tests/local_skills/test_check_alarm_shape.py \
  tests/local_skills/test_check_resource_discovery.py \
  -q
python3 -m py_compile \
  ignored/local/skills/software-development/check/scripts/notifly_alert_context/aws_collectors.py
```

Expected: all Task 1-2 tests pass.

- [ ] **Step 7: Commit Task 2 only**

```bash
git add -f \
  ignored/local/skills/software-development/check/scripts/notifly_alert_context/aws_collectors.py
git add tests/local_skills/test_check_resource_discovery.py
git commit -m "feat(check): discover dimensionless Lambda offenders"
```

---

### Task 3: Wire Ordered Discovery and Current-Window Lambda Logs

**Files:**
- Modify: `ignored/local/skills/software-development/check/scripts/notifly_alert_context/logs.py:252-356,985-1196`
- Modify: `ignored/local/skills/software-development/check/scripts/notifly_alert_context/collectors.py:19-131`
- Modify: `tests/local_skills/test_check_resource_discovery.py`

**Interfaces:**
- Produces `collect_lambda_alarm_signatures(session, log_groups, alarm, history) -> Dict[str, Any]`.
- Produces collector keys `alarm_shape`, `lambda_discovery`, and `lambda_log_signatures`.
- Produces `effective_lambda_names(ctx)` and `effective_log_groups(ctx)` without mutating initial context fields.
- `lambda_context` consumes effective names; Task 4 DB resolution consumes shape and both log results.

- [ ] **Step 1: Add failing order and propagation tests**

Extend `test_check_resource_discovery.py`:

```python
def test_registry_discovers_before_enrichment() -> None:
    keys = collector_keys()
    assert keys.index("alarm_shape") < keys.index("lambda_discovery")
    assert keys.index("lambda_discovery") < keys.index("lambda_log_signatures")
    assert keys.index("lambda_log_signatures") < keys.index("rds_context")
    assert keys.index("rds_context") < keys.index("rds_performance_insights")


def test_effective_resources_include_discovery_without_mutation() -> None:
    ctx = CollectorContext(
        session=None,
        text="CloudWatch Alarm",
        alarm={},
        log_groups=(),
        keywords=(),
        queue_names=(),
        lambda_names=(),
        history={},
    )
    ctx.results["lambda_discovery"] = {
        "derived_lambda_names": ["scheduled-batch-delivery"],
        "derived_log_groups": ["/aws/lambda/scheduled-batch-delivery"],
    }
    assert effective_lambda_names(ctx) == ["scheduled-batch-delivery"]
    assert effective_log_groups(ctx) == [
        "/aws/lambda/scheduled-batch-delivery"
    ]
    assert ctx.lambda_names == ()
    assert ctx.log_groups == ()
```

Add a fake Logs Insights client and assert one `start_query` receives no more than five `logGroupNames` and a query containing `REPORT`, `ERROR`, `Exception`, `timeout`, `query`, `deadlock`, and `connection`.

- [ ] **Step 2: Run tests and verify missing interfaces**

```bash
venv/bin/python -m pytest tests/local_skills/test_check_resource_discovery.py -q
```

Expected: effective-resource helpers and Lambda signature collector are absent.

- [ ] **Step 3: Add the fixed Lambda signature query**

Implement `collect_lambda_alarm_signatures()` using `alarm_trigger_window()` and `run_logs_insights_query_window_groups()`. Use one current-window query:

```sql
fields @timestamp, @message, @logStream, @log
| filter @message like /(?i)REPORT/
    or @message like /(?i)ERROR/
    or @message like /(?i)Exception/
    or @message like /(?i)timeout/
    or @message like /(?i)query/
    or @message like /(?i)deadlock/
    or @message like /(?i)connection/
| sort @timestamp desc
| limit 100
```

Pass at most five groups, wait at most 25 seconds, sanitize samples, aggregate with `top_log_signatures()`, and keep ten signatures. Return `db_evidence` containing only sanitized lines matching `DB_LOG_PATTERNS`.

- [ ] **Step 4: Add ordered registry wrappers**

Replace registry lambdas with named wrappers where results are dependencies. Keep this exact relative order:

```python
COLLECTOR_REGISTRY = (
    CollectorSpec("metric_datapoints", _collect_metric_datapoints),
    CollectorSpec("alarm_shape", _collect_alarm_shape),
    CollectorSpec("lambda_discovery", _collect_lambda_discovery),
    CollectorSpec("hermes_observability", _collect_hermes_observability),
    CollectorSpec("metric_filters", _collect_metric_filters),
    CollectorSpec("logs_insights", _collect_logs_insights),
    CollectorSpec("lambda_log_signatures", _collect_lambda_log_signatures),
    CollectorSpec("rds_context", _collect_rds_context),
    CollectorSpec("http_context", _collect_http_context),
    CollectorSpec("five_xx_metrics", _collect_five_xx_metrics),
    CollectorSpec("sqs_context", _collect_sqs_context),
    CollectorSpec("lambda_context", _collect_lambda_context),
    CollectorSpec("rds_performance_insights", _collect_rds_performance_insights),
    CollectorSpec("campaign_scope_hints", _collect_campaign_scope_hints),
)
```

Merge explicit and discovered names in `effective_lambda_names()`. Merge explicit and derived log groups in `effective_log_groups()` and cap at `MAX_LOG_QUERY_GROUPS`. Use effective names for `lambda_context`, and use effective groups for `lambda_log_signatures` and final detected output. Keep `metric_filters` and the existing 7d/30d `logs_insights` summary on the original explicit/metric-filter-derived groups so discovery does not multiply historical scans. Payment-mode detection uses effective Lambda names in both paths.

- [ ] **Step 5: Run registry and helper regressions**

```bash
venv/bin/python -m pytest \
  tests/local_skills/test_check_resource_discovery.py \
  tests/local_skills/test_check_helper_context.py \
  -q
```

Expected: registry, propagation, and existing helper tests pass.

- [ ] **Step 6: Commit Task 3 only**

```bash
git add -f \
  ignored/local/skills/software-development/check/scripts/notifly_alert_context/logs.py \
  ignored/local/skills/software-development/check/scripts/notifly_alert_context/collectors.py
git add tests/local_skills/test_check_resource_discovery.py
git commit -m "feat(check): stage Lambda discovery before enrichment"
```

---

### Task 4: Resolve DB Targets and PI Provenance

**Files:**
- Modify: `ignored/local/skills/software-development/check/scripts/notifly_alert_context/aws_collectors.py:634-880`
- Modify: `ignored/local/skills/software-development/check/scripts/notifly_alert_context/collectors.py:39-118`
- Modify: `tests/local_skills/test_check_resource_discovery.py`

**Interfaces:**
- Produces `resolve_db_relevance(alarm_shape, logs_insights, lambda_log_signatures) -> Dict[str, Any]`.
- Extends `describe_rds_context(session, alarm, *, alarm_shape=None, logs_insights=None, lambda_log_signatures=None)`.
- `rds_context` adds `status`, `db_relevance`, and `target_source` while retaining `cluster`, `instance`, and `instances` topology.
- PI output adds `evidence_level` and `target_source`.

- [ ] **Step 1: Add failing target-precedence tests**

Define these module fixtures, then add fake RDS and PI clients that return a
cluster with one writer, four readers, and five PI-enabled instances:

```python
RDS_METRIC_MATH_ALARM = {
    "AlarmName": "explicit-rds-cpu-high",
    "Metrics": [{
        "Id": "cpu",
        "Expression": (
            'SELECT MAX(CPUUtilization) FROM SCHEMA("AWS/RDS", '
            "DBInstanceIdentifier) WHERE tag.DBClusterIdentifier = "
            "'explicit-cluster' GROUP BY DBInstanceIdentifier"
        ),
    }],
}

NON_DB_ALARM = {
    "AlarmName": "event-stream-iterator-age",
    "Namespace": "AWS/Kinesis",
    "MetricName": "GetRecords.IteratorAgeMilliseconds",
    "Dimensions": [{"Name": "StreamName", "Value": "prod-events"}],
}
```

`FakeRdsSession.client('rds')` returns a client whose
`describe_db_clusters()` echoes the requested ID and returns members
`db-a` through `db-e`, with `db-a` marked `IsClusterWriter=True`.
`describe_db_instances()` returns those five IDs with
`PerformanceInsightsEnabled=True` and `DbiResourceId='resource-<id>'`.
`FakeRdsSession.client('pi')` returns one `db.load.avg` SQL series per call and
records call count. `RejectUnexpectedClientSession.client()` appends the
requested name and raises `AssertionError`, proving non-DB alarms make no AWS
request.

Use these assertions:

```python
def test_explicit_cluster_precedes_fallback() -> None:
    result = describe_rds_context(
        FakeRdsSession(),
        RDS_METRIC_MATH_ALARM,
        alarm_shape=classify_alarm_shape(RDS_METRIC_MATH_ALARM),
    )
    assert result["target_source"] == "alarm_explicit_cluster"
    assert result["cluster"]["id"] == "explicit-cluster"


def test_candidate_db_alarm_uses_correlation_target() -> None:
    alarm = {
        "AlarmName": "worker-db-query-latency",
        "Namespace": "Custom/Worker",
        "MetricName": "Latency",
        "Dimensions": [],
    }
    result = describe_rds_context(
        FakeRdsSession(),
        alarm,
        alarm_shape=classify_alarm_shape(alarm),
    )
    assert result["target_source"] == "production_default_correlation"
    assert result["db_relevance"]["level"] == "candidate"


def test_non_db_alarm_does_not_open_rds_client() -> None:
    session = RejectUnexpectedClientSession()
    result = describe_rds_context(
        session,
        NON_DB_ALARM,
        alarm_shape=classify_alarm_shape(NON_DB_ALARM),
    )
    assert result is None
    assert session.requested_clients == []
```

Also assert no more than four PI-enabled instances are returned and fallback PI has `evidence_level='correlated'`.

- [ ] **Step 2: Run DB tests and verify failures**

```bash
venv/bin/python -m pytest \
  tests/local_skills/test_check_resource_discovery.py \
  -q -k 'rds or db or production or pi'
```

Expected: current RDS context ignores metric-math and candidate alarms.

- [ ] **Step 3: Finalize DB relevance from current evidence**

Start with `alarm_shape['db_relevance']`. Inspect only bounded fields from `logs_insights.current_error_details`, `logs_insights.current_top_signatures`, and `lambda_log_signatures.db_evidence`. Upgrade to `confirmed` when `DB_LOG_PATTERNS` match. Preserve short evidence codes such as `namespace:AWS/RDS`, `alarm_token:db`, and `current_log:query timeout`; never copy raw log blocks.

- [ ] **Step 4: Resolve topology with explicit-first precedence**

Implement this decision order:

```python
if explicit_cluster_ids:
    target_source = "alarm_explicit_cluster"
    cluster_id = explicit_cluster_ids[0]
elif explicit_instance_ids:
    target_source = "alarm_explicit_instance"
    instance_id = explicit_instance_ids[0]
elif db_relevance["level"] in {"candidate", "confirmed"}:
    target_source = "production_default_correlation"
    cluster_id = DEFAULT_PRODUCTION_RDS_CLUSTER_ID
else:
    return None
```

Describe only that cluster or instance. For clusters, preserve writer/reader roles and keep at most four PI-enabled members with a `DbiResourceId`.

- [ ] **Step 5: Bound PI and label provenance**

Change `rds_pi_window()` to the same bounded alarm window. Preserve focus-window calculations inside that range. Add:

```python
"target_source": rds_context.get("target_source"),
"evidence_level": (
    "correlated"
    if rds_context.get("target_source") == "production_default_correlation"
    else "observed"
),
```

Keep existing SQL sanitization, project suffix detection, and top-five cap.

- [ ] **Step 6: Pass prior results from the RDS wrapper**

Update `_collect_rds_context(ctx)` to pass `alarm_shape`, `logs_insights`, and `lambda_log_signatures`. Do not inspect raw LLM text again in `aws_collectors.py`.

- [ ] **Step 7: Run DB, scope, and assessment regressions**

```bash
venv/bin/python -m pytest \
  tests/local_skills/test_check_resource_discovery.py \
  tests/local_skills/test_check_helper_context.py \
  ignored/local/skills/software-development/check/tests/test_assessment.py \
  -q
```

Expected: target precedence and existing scope/assessment tests pass.

- [ ] **Step 8: Commit Task 4 only**

```bash
git add -f \
  ignored/local/skills/software-development/check/scripts/notifly_alert_context/aws_collectors.py \
  ignored/local/skills/software-development/check/scripts/notifly_alert_context/collectors.py
git add tests/local_skills/test_check_resource_discovery.py
git commit -m "feat(check): correlate DB alarms with bounded PI context"
```

---

### Task 5: Recognize Metric-Math Profile Status and Attribute Sessions

**Files:**
- Modify: `ignored/local/skills/software-development/check/scripts/notifly_alert_context/hermes_observability.py:19-690`
- Modify: `ignored/local/skills/software-development/check/scripts/notifly_alert_context/collectors.py:99-117`
- Modify: `tests/local_skills/test_check_hermes_observability.py`

**Interfaces:**
- Extends `is_hermes_service_health_alarm(alarm, alarm_shape=None) -> bool`.
- Produces `collect_profile_status_metrics(session, alarm, history, alarm_shape) -> Dict[str, Any]`.
- Produces `find_overlapping_session_candidates(root, profiles, start, end, limit_per_profile=3) -> List[Dict[str, Any]]`.
- Extends `collect_hermes_observability_context(session, alarm, history, *, root=None, alarm_shape=None)` with `breaching_profiles` and `session_candidates`.

- [ ] **Step 1: Add the actual metric-math alarm fixture**

In `test_check_hermes_observability.py`, add:

```python
def _profile_status_alarm() -> dict:
    return {
        "_alarm_type": "MetricAlarm",
        "AlarmName": "hermes-agent-profile-status",
        "Threshold": 1.0,
        "ComparisonOperator": "GreaterThanOrEqualToThreshold",
        "EvaluationPeriods": 1,
        "Metrics": [{
            "Id": "profile_status",
            "Expression": (
                'SELECT MAX(HermesProfileStatus) FROM SCHEMA("CWAgent", '
                'InstanceId, Profile, metric_type) '
                "WHERE InstanceId = 'i-test' AND metric_type = 'gauge' "
                "GROUP BY Profile ORDER BY MAX() DESC"
            ),
            "ReturnData": True,
            "Period": 60,
        }],
    }
```

Extend the fake CloudWatch client with grouped labels `linus`, `jeff`, and `hashimoto` and values 2, 1, and 0.

- [ ] **Step 2: Add failing exact and candidate tests**

```python
def test_metric_math_alarm_collects_breaching_profiles(tmp_path: Path) -> None:
    _create_profile_db(tmp_path)
    alarm = _profile_status_alarm()
    result = collect_hermes_observability_context(
        _Session(),
        alarm,
        _history(),
        root=tmp_path,
        alarm_shape=classify_alarm_shape(alarm),
    )
    assert [row["profile"] for row in result["breaching_profiles"]] == [
        "linus",
        "jeff",
    ]


def test_overlap_without_pressure_is_candidate_only(tmp_path: Path) -> None:
    _create_profile_db(tmp_path)
    candidates = find_overlapping_session_candidates(
        tmp_path,
        ["andrej"],
        datetime.fromtimestamp(100, tz=timezone.utc),
        datetime.fromtimestamp(220, tz=timezone.utc),
    )
    assert candidates[0]["attribution_confidence"] == "time_overlap_candidate"
    assert candidates[0]["session_link"] == f"@session:andrej/{ACTIVE_CHILD}"
```

Keep the existing assertion that a pressure event plus tool interval yields `active_tool_interval_match`.

- [ ] **Step 3: Run tests and verify metric-math failures**

```bash
venv/bin/python -m pytest tests/local_skills/test_check_hermes_observability.py -q
```

Expected: existing `HermesServiceHealthy` tests pass; new metric-math interfaces fail.

- [ ] **Step 4: Query grouped profile metrics**

Use one bounded `get_metric_data()` query:

```python
expression = (
    'SELECT MAX(HermesProfileStatus) FROM SCHEMA("CWAgent", '
    'InstanceId, Profile, metric_type) '
    f"WHERE InstanceId = '{instance_id}' AND metric_type = 'gauge' "
    'GROUP BY Profile ORDER BY MAX() DESC LIMIT 20'
)
```

Accept instance IDs only when they match `^[A-Za-z0-9_-]+$`. Parse profile labels, apply the alarm comparison and threshold, and keep breaching profiles. Without a safe instance ID, return `partial` without issuing a broad query.

- [ ] **Step 5: Add read-only overlap candidates**

Open each validated profile `state.db` using SQLite URI `mode=ro`. Query sessions joined to messages with timestamps inside the alarm window. Rank by latest matching timestamp and keep three per profile. Return parent/child session links, title, source, task excerpt, and `attribution_confidence='time_overlap_candidate'`.

Do not infer activity from `ended_at IS NULL` alone; require a message or tool timestamp in the window.

- [ ] **Step 6: Integrate exact and candidate evidence**

Recognize either the old `HermesServiceHealthy` metric or `alarm_shape.hermes_profile_status`. Collect profile metrics first. For metric-math alarms, build `alarm_trigger` from the grouped profile query and do not call `_collect_alarm_trigger()`, which requires top-level `Namespace` and `MetricName`. Filter pressure events to breaching profiles when available. Call candidate resolution only for breaching profiles with no exact pressure-event attribution. Pass `ctx.results['alarm_shape']` from the collector wrapper.

- [ ] **Step 7: Run Hermes and compact regressions**

```bash
venv/bin/python -m pytest \
  tests/local_skills/test_check_hermes_observability.py \
  tests/local_skills/test_check_helper_context.py \
  -q
```

Expected: old and new Hermes alarm paths pass.

- [ ] **Step 8: Commit Task 5 only**

```bash
git add -f \
  ignored/local/skills/software-development/check/scripts/notifly_alert_context/hermes_observability.py \
  ignored/local/skills/software-development/check/scripts/notifly_alert_context/collectors.py
git add tests/local_skills/test_check_hermes_observability.py
git commit -m "feat(check): attribute profile status alarms to sessions"
```

---

### Task 6: Unify Assessment, CLI Output, Budget, and Skill Guidance

**Files:**
- Modify: `ignored/local/skills/software-development/check/scripts/notifly_alert_context/assessment.py:745-1162,1684-1799`
- Modify: `ignored/local/skills/software-development/check/scripts/notifly_alert_context/cli.py:74-237`
- Modify: `ignored/local/skills/software-development/check/SKILL.md:35-130`
- Modify: `tests/local_skills/test_check_helper_context.py`
- Modify: `ignored/local/skills/software-development/check/tests/test_assessment.py`

**Interfaces:**
- `data` adds `alarm_shape`, `lambda_discovery`, and `lambda_log_signatures`.
- `detected.lambda_names` and `detected.log_groups` expose effective resources.
- Assessment evidence adds `lambda_top_offender`, `lambda_current_error`, `healthy_lambda_batch_pattern`, `rds_explicit_top_sql`, `rds_correlated_top_sql`, `hermes_breaching_profiles`, `hermes_session_attribution`, and `hermes_session_candidates`.

- [ ] **Step 1: Add failing assessment invariants**

Add this complete base builder in `test_check_helper_context.py`; each derived
builder calls it to get a fresh dictionary and changes only the shown fields:

```python
def dimensionless_lambda_data() -> dict:
    return {
        "detected": {
            "alarm_name": "notifly-lambda-high-duration",
            "log_groups": [],
            "keywords": [],
            "service_names": [],
            "lambda_names": ["scheduled-batch-delivery"],
            "project_ids": [],
        },
        "alarm_summary": {
            "AlarmName": "notifly-lambda-high-duration",
            "Namespace": "AWS/Lambda",
            "MetricName": "Duration",
            "StateValue": "ALARM",
            "Statistic": "Sum",
            "Dimensions": [],
        },
        "alarm_shape": {
            "dimensionless_lambda": True,
            "hermes_profile_status": False,
            "db_relevance": {"level": "none", "evidence": []},
        },
        "alarm_history": {
            "latest_alarm_transition": {"timestamp": "2026-08-12T01:05:00Z"},
            "alarm_count_7d": 2,
            "sample_items": [],
        },
        "metric_datapoints": {"datapoint_count": 1},
        "lambda_discovery": {
            "status": "collected",
            "offenders": [{
                "function_name": "scheduled-batch-delivery",
                "duration_sum_ms": 64_000_000,
                "invocations": 800,
                "errors": 0,
                "throttles": 0,
            }],
        },
        "lambda_log_signatures": {
            "status": "collected",
            "signatures": [],
            "db_evidence": [],
        },
        "lambda_context": {"functions": [{"function_name": "scheduled-batch-delivery"}]},
        "logs_insights": None,
        "rds_context": None,
        "rds_performance_insights": None,
        "hermes_observability": None,
        "scope_attribution": {"infra_indicators": ["AWS/Lambda"]},
        "project_mappings": [],
        "repo_code_hits": [{"path": "services/lambda.ts"}],
    }


def answerable_lambda_timeout_data() -> dict:
    data = dimensionless_lambda_data()
    data["lambda_discovery"]["offenders"][0]["errors"] = 3
    data["lambda_log_signatures"]["signatures"] = [{
        "signature": "REPORT Status: timeout",
        "count_in_current_alarm_window": 3,
    }]
    return data


def healthy_lambda_batch_data() -> dict:
    data = dimensionless_lambda_data()
    data["alarm_history"]["sample_items"] = [{
        "timestamp": "2026-08-12T01:07:00Z",
        "new_state": "OK",
    }]
    data["alarm_history"]["rapid_recurrence"] = {
        "status": "normal",
        "alarm_count_within_30m": 1,
    }
    return data


def hermes_profile_only_data() -> dict:
    data = dimensionless_lambda_data()
    data["detected"]["alarm_name"] = "hermes-agent-profile-status"
    data["detected"]["lambda_names"] = []
    data["alarm_summary"] = {
        "AlarmName": "hermes-agent-profile-status",
        "StateValue": "ALARM",
        "Dimensions": [],
    }
    data["alarm_shape"] = {
        "dimensionless_lambda": False,
        "hermes_profile_status": True,
        "db_relevance": {"level": "none", "evidence": []},
    }
    data["lambda_discovery"] = {"status": "not_applicable", "offenders": []}
    data["lambda_context"] = None
    data["hermes_observability"] = {
        "status": "collected",
        "breaching_profiles": [{"profile": "linus", "value": 2}],
        "pressure_incidents": [],
        "session_candidates": [],
    }
    data["scope_attribution"] = {"infra_indicators": ["HermesProfileStatus"]}
    return data
```

Then add these tests:

```python
def test_fallback_pi_alone_cannot_establish_root_cause() -> None:
    data = dimensionless_lambda_data()
    data["alarm_shape"]["db_relevance"]["level"] = "candidate"
    data["rds_context"] = {
        "target_source": "production_default_correlation",
        "db_relevance": {"level": "candidate", "evidence": ["alarm_token:db"]},
        "instances": [{"id": "notifly-db-prod-c", "role_hint": "writer"}],
    }
    data["rds_performance_insights"] = {
        "evidence_level": "correlated",
        "instances": [{"top_sql": [{"sql_id": "sql-1", "statement": "SELECT 1"}]}],
    }
    assert assess_helper_context(data)["can_answer_root_cause"] is False


def test_answerable_result_has_no_required_gap() -> None:
    result = assess_helper_context(answerable_lambda_timeout_data())
    assert result["can_answer_root_cause"] is True
    assert not [
        item for item in result["missing_required_context"]
        if item.get("severity", "required") == "required"
    ]
    assert result["required_followups"] == []


def test_healthy_aggregate_pattern_can_finalize() -> None:
    result = assess_helper_context(healthy_lambda_batch_data())
    assert result["can_answer_root_cause"] is True
    assert "healthy_lambda_batch_pattern" in result["root_cause_evidence"]


def test_profile_without_session_remains_incomplete() -> None:
    result = assess_helper_context(hermes_profile_only_data())
    assert result["can_answer_root_cause"] is False
    assert any(
        item["key"] == "hermes_session_attribution"
        for item in result["missing_required_context"]
    )
```

Add a compact-output test containing five offenders, ten signatures, four PI instances, and Hermes candidates. Assert encoded length is at most `COMPACT_OUTPUT_MAX_BYTES` and that the top offender, PI `target_source`, and exact session link survive.

- [ ] **Step 2: Run tests and verify gating failures**

```bash
venv/bin/python -m pytest \
  tests/local_skills/test_check_helper_context.py \
  ignored/local/skills/software-development/check/tests/test_assessment.py \
  -q
```

Expected: new evidence labels and gating assertions fail.

- [ ] **Step 3: Consume the shared shape in assessment**

Replace duplicate top-level-only checks with:

```python
dimensionless_lambda = bool(alarm_shape.get("dimensionless_lambda"))
hermes_shaped = bool(alarm_shape.get("hermes_profile_status")) or (
    metric_name == "HermesServiceHealthy"
)
db_level = ((rds or {}).get("db_relevance") or {}).get("level", "none")
fallback_pi = (
    isinstance(rds, dict)
    and rds.get("target_source") == "production_default_correlation"
)
```

For dimensionless Lambda, require a current error/timeout signature or the complete healthy pattern: top offender, Errors=0, Throttles=0, rapid recovery, and recurring workload evidence. Do not emit `describe_lambda_context` after discovery resolved functions.

For indirect DB alarms, fallback PI enriches scope but cannot satisfy root cause alone. For direct RDS alarms, explicit topology plus current top SQL is sufficient. For Hermes, exact session attribution is sufficient; candidates leave a required attribution gap.

- [ ] **Step 4: Keep final answer gating consistent**

Compute required missing context once at the end:

```python
required_missing = [
    item for item in missing
    if str(item.get("severity") or "required").lower() == "required"
]
can_answer = bool(evidence_is_sufficient and not required_missing)
selected_followups = [] if can_answer else followups[:2]
```

Do not add a runtime assertion that could terminate alert handling; enforce the invariant in tests.

- [ ] **Step 5: Expose discovery from CLI**

Read `alarm_shape`, `lambda_discovery`, and `lambda_log_signatures` after `run_collectors()`. Merge derived names/groups into `detected`, use effective names in `repo_tokens`, add all three sections to `data`, and print them before detailed Lambda/RDS sections in `sections` mode.

- [ ] **Step 6: Preserve evidence under 10,000 bytes**

Add bounded sections:

```python
"alarm_shape": _bounded_value(data.get("alarm_shape"), max_depth=4),
"lambda_discovery": _bounded_value(
    data.get("lambda_discovery"), max_depth=5, max_items=5
),
"lambda_log_signatures": _bounded_value(
    data.get("lambda_log_signatures"), max_depth=5, max_items=10
),
```

Prioritize their cause/provenance fields in `_fit_compact_budget()` ahead of historical samples and repo hits. Preserve `COMPACT_OUTPUT_MAX_BYTES = 10_000`.

- [ ] **Step 7: Update `SKILL.md`**

Add the new sections to the first inspection boundaries. State that discovered functions replace manual per-function CloudWatch loops, `production_default_correlation` is not causal proof, exact Hermes attribution may be reported as cause, candidates must be labeled uncertain, and helper-covered AWS queries must not be repeated manually.

- [ ] **Step 8: Run focused tests and syntax checks**

```bash
venv/bin/python -m pytest \
  tests/local_skills/test_check_alarm_shape.py \
  tests/local_skills/test_check_resource_discovery.py \
  tests/local_skills/test_check_hermes_observability.py \
  tests/local_skills/test_check_helper_context.py \
  ignored/local/skills/software-development/check/tests/test_assessment.py \
  -q
python3 -m py_compile \
  ignored/local/skills/software-development/check/scripts/collect_notifly_alert_context.py \
  ignored/local/skills/software-development/check/scripts/notifly_alert_context/*.py
```

Expected: focused tests pass and all helper modules compile.

- [ ] **Step 9: Commit Task 6 only**

```bash
git add -f \
  ignored/local/skills/software-development/check/scripts/notifly_alert_context/assessment.py \
  ignored/local/skills/software-development/check/scripts/notifly_alert_context/cli.py \
  ignored/local/skills/software-development/check/SKILL.md \
  ignored/local/skills/software-development/check/tests/test_assessment.py
git add tests/local_skills/test_check_helper_context.py
git commit -m "feat(check): gate answers on discovered alert evidence"
```

---

### Task 7: Run Full and Live Read-Only Verification

**Files:**
- Modify only if a test reveals a defect: files already named in Tasks 1-6.
- Do not commit generated output.

**Interfaces:**
- Validates public entry point `scripts/collect_notifly_alert_context.py`.
- Uses the Hashimoto profile environment without printing credentials.

- [ ] **Step 1: Run all check helper tests**

```bash
venv/bin/python -m pytest \
  tests/local_skills/test_check_alarm_shape.py \
  tests/local_skills/test_check_resource_discovery.py \
  tests/local_skills/test_check_hermes_observability.py \
  tests/local_skills/test_check_helper_context.py \
  ignored/local/skills/software-development/check/tests \
  -q
```

Expected: all check helper tests pass.

- [ ] **Step 2: Run the complete local-skills suite**

```bash
venv/bin/python -m pytest tests/local_skills -q
```

Expected: all tests pass. If an unrelated failure appears, record its exact test ID and verify it also fails against the pre-task commit before changing code.

- [ ] **Step 3: Check syntax, whitespace, and worktree scope**

```bash
git diff --check -- \
  ignored/local/skills/software-development/check \
  tests/local_skills
python3 -m py_compile \
  ignored/local/skills/software-development/check/scripts/collect_notifly_alert_context.py \
  ignored/local/skills/software-development/check/scripts/notifly_alert_context/*.py \
  tests/local_skills/test_check_alarm_shape.py \
  tests/local_skills/test_check_resource_discovery.py \
  tests/local_skills/test_check_hermes_observability.py \
  tests/local_skills/test_check_helper_context.py
git status --short
```

Expected: no whitespace or syntax errors. Unrelated user changes may remain, but all implementation paths are committed.

- [ ] **Step 4: Validate the live dimensionless Lambda alarm**

```bash
HERMES_HOME=/home/ubuntu/.hermes/profiles/hashimoto \
  venv/bin/python \
  ignored/local/skills/software-development/check/scripts/collect_notifly_alert_context.py \
  --text 'CloudWatch Alarm | notifly-lambda-high-duration | ap-northeast-2 | Account: 702197142747' \
  --alarm-name notifly-lambda-high-duration \
  --region ap-northeast-2 \
  --format compact-json \
  | jq '{alarm_shape, lambda_discovery, lambda_log_signatures, lambda, helper_notes}'
```

Expected: `dimensionless_lambda=true`, up to five ranked offenders, derived Lambda context, and no follow-up asking the LLM to identify a function already discovered.

- [ ] **Step 5: Validate the live metric-math Hermes alarm**

```bash
HERMES_HOME=/home/ubuntu/.hermes/profiles/hashimoto \
  venv/bin/python \
  ignored/local/skills/software-development/check/scripts/collect_notifly_alert_context.py \
  --text 'CloudWatch Alarm | hermes-agent-profile-status | ap-northeast-2 | Account: 702197142747' \
  --alarm-name hermes-agent-profile-status \
  --region ap-northeast-2 \
  --format compact-json \
  | jq '{alarm_shape, hermes_observability, missing_required_context, required_followups}'
```

Expected: `hermes_profile_status=true`; current breaching profiles are listed when present; session links are exact or explicitly low-confidence candidates.

- [ ] **Step 6: Validate explicit DB precedence**

```bash
HERMES_HOME=/home/ubuntu/.hermes/profiles/hashimoto \
  venv/bin/python \
  ignored/local/skills/software-development/check/scripts/collect_notifly_alert_context.py \
  --text 'CloudWatch Alarm | notifly-db-prod-instance-high-cpu-usage | ap-northeast-2 | Account: 702197142747' \
  --alarm-name notifly-db-prod-instance-high-cpu-usage \
  --region ap-northeast-2 \
  --format compact-json \
  | jq '{alarm_shape, rds, rds_performance_insights}'
```

Expected: the explicit cluster/instance wins over fallback and PI provenance is `observed`.

- [ ] **Step 7: Validate non-DB isolation**

```bash
HERMES_HOME=/home/ubuntu/.hermes/profiles/hashimoto \
  venv/bin/python \
  ignored/local/skills/software-development/check/scripts/collect_notifly_alert_context.py \
  --text 'CloudWatch Alarm | notifly-event-stream High GetRecords Iterator Age | ap-northeast-2 | Account: 702197142747' \
  --alarm-name 'notifly-event-stream High GetRecords Iterator Age' \
  --region ap-northeast-2 \
  --format compact-json \
  | jq '{alarm_shape, rds, rds_performance_insights}'
```

Expected: DB relevance is `none`; RDS sections are null or `not_applicable`; production PI is not queried.

- [ ] **Step 8: Confirm live compact byte limits**

Repeat each live command without the final `jq` filter and pipe to `wc -c`. Confirm every result is at most `10000`. Do not save payloads outside `/home/ubuntu/.hermes`.

- [ ] **Step 9: Review the final commit range**

```bash
git log --oneline --decorate -8
git diff --stat c55e1eceb4..HEAD -- \
  ignored/local/skills/software-development/check \
  tests/local_skills
git status --short
```

Expected: only focused Task 1-6 commits affect the feature paths; unrelated dirty files remain untouched.

---

## Completion Checklist

- [ ] Dimensionless Lambda alarms return ranked functions and current-window signatures.
- [ ] Derived functions reach Lambda enrichment in the same helper run.
- [ ] DB matching is delimiter-aware and does not trigger on unrelated names.
- [ ] Explicit RDS targets outrank production fallback.
- [ ] Fallback PI is correlation-only and cannot alone establish root cause.
- [ ] Metric-math profile alarms return breaching profiles and exact or candidate sessions.
- [ ] Collector and assessment recognition use one classifier.
- [ ] No answerable assessment contains required missing context or follow-ups.
- [ ] Compact output is at most 10,000 bytes.
- [ ] Focused, local-skill, syntax, live AWS, and diff reviews pass.
