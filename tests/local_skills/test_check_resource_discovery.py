from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = (
    REPO_ROOT
    / "ignored"
    / "local"
    / "skills"
    / "software-development"
    / "check"
)
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from notifly_alert_context.alarm_shape import classify_alarm_shape  # noqa: E402
from notifly_alert_context.aws_collectors import (  # noqa: E402
    alarm_focus_window,
    collect_lambda_top_offenders,
    collect_rds_performance_insights,
    describe_rds_context,
    resolve_db_relevance,
)
from notifly_alert_context.config import (  # noqa: E402
    MAX_DISCOVERY_WINDOW_SECONDS,
    MAX_LAMBDA_OFFENDERS,
)
from notifly_alert_context.collectors import (  # noqa: E402
    CollectorContext,
    collector_keys,
    effective_lambda_names,
    effective_log_groups,
)
from notifly_alert_context.logs import collect_lambda_alarm_signatures  # noqa: E402


DIMENSIONLESS_LAMBDA_ALARM = {
    "_alarm_type": "MetricAlarm",
    "AlarmName": "notifly-lambda-high-duration",
    "Namespace": "AWS/Lambda",
    "MetricName": "Duration",
    "Statistic": "Sum",
    "Period": 60,
    "EvaluationPeriods": 5,
    "Dimensions": [],
}

ALARM_HISTORY = {
    "latest_alarm_transition": {
        "timestamp": "2026-08-12T01:05:00+00:00",
    }
}

RDS_METRIC_MATH_ALARM = {
    "_alarm_type": "MetricAlarm",
    "AlarmName": "explicit-rds-cpu-high",
    "Period": 60,
    "EvaluationPeriods": 5,
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


class FakeCloudWatchClient:
    def __init__(self) -> None:
        self.calls = []

    def get_metric_data(self, **kwargs):
        self.calls.append(kwargs)
        queries = kwargs["MetricDataQueries"]
        if "Expression" in queries[0]:
            return {
                "MetricDataResults": [
                    {
                        "Id": "lambda_duration_sum",
                        "Label": f"{index} - {name}",
                        "Timestamps": [datetime(2026, 8, 12, 1, 5, tzinfo=timezone.utc)],
                        "Values": [value],
                        "StatusCode": "Complete",
                    }
                    for index, (name, value) in enumerate([
                        ("small-function", 10),
                        ("kds-consumer", 50_000_000),
                        ("scheduled-batch-delivery", 64_000_000),
                        ("anomaly-delivery-monitoring", 20_000_000),
                        ("segment-publisher-trigger", 30_000_000),
                        ("user-journey-node-runner", 40_000_000),
                    ], start=1)
                ]
            }

        metric_values = {
            "duration_sum": 64_000_000,
            "duration_avg": 8_000,
            "invocations": 800,
            "errors": 0,
            "throttles": 0,
        }
        return {
            "MetricDataResults": [
                {
                    "Id": query["Id"],
                    "Timestamps": [datetime(2026, 8, 12, 1, 5, tzinfo=timezone.utc)],
                    "Values": [
                        metric_values[next(
                            suffix
                            for suffix in metric_values
                            if query["Id"].endswith(suffix)
                        )]
                    ],
                    "StatusCode": "Complete",
                }
                for query in queries
            ]
        }


class FakeSession:
    def __init__(self, cloudwatch=None) -> None:
        self.cloudwatch = cloudwatch or FakeCloudWatchClient()
        self.requested_clients = []

    def client(self, name: str):
        self.requested_clients.append(name)
        if name != "cloudwatch":
            raise AssertionError(name)
        return self.cloudwatch


class AccessDeniedCloudWatchClient:
    def __init__(self) -> None:
        self.calls = []

    def get_metric_data(self, **kwargs):
        self.calls.append(kwargs)
        raise RuntimeError("AccessDeniedException: cloudwatch:GetMetricData")


class FakeLogsClient:
    def __init__(self) -> None:
        self.start_calls = []

    def start_query(self, **kwargs):
        self.start_calls.append(kwargs)
        return {"queryId": "query-1"}

    def get_query_results(self, **kwargs):
        return {
            "status": "Complete",
            "results": [
                [
                    {"field": "@timestamp", "value": "2026-08-12T01:04:30Z"},
                    {
                        "field": "@message",
                        "value": "REPORT RequestId: req Duration: 12000 ms Status: timeout",
                    },
                    {"field": "@log", "value": "group"},
                    {"field": "@logStream", "value": "stream"},
                ],
                [
                    {"field": "@timestamp", "value": "2026-08-12T01:04:20Z"},
                    {
                        "field": "@message",
                        "value": "Query timeout while waiting for postgres connection",
                    },
                    {"field": "@log", "value": "group"},
                    {"field": "@logStream", "value": "stream"},
                ],
            ],
            "statistics": {"recordsMatched": 2},
        }


class FakeLogsSession:
    def __init__(self) -> None:
        self.logs = FakeLogsClient()

    def client(self, name: str):
        if name != "logs":
            raise AssertionError(name)
        return self.logs


class FakeRdsClient:
    def __init__(self) -> None:
        self.cluster_requests = []

    def describe_db_clusters(self, **kwargs):
        cluster_id = kwargs["DBClusterIdentifier"]
        self.cluster_requests.append(cluster_id)
        return {
            "DBClusters": [{
                "DBClusterIdentifier": cluster_id,
                "Engine": "aurora-postgresql",
                "Status": "available",
                "DBClusterMembers": [
                    {
                        "DBInstanceIdentifier": f"db-{letter}",
                        "IsClusterWriter": letter == "a",
                    }
                    for letter in "abcde"
                ],
            }]
        }

    def describe_db_instances(self, **kwargs):
        if kwargs:
            instance_ids = [kwargs["DBInstanceIdentifier"]]
        else:
            instance_ids = [f"db-{letter}" for letter in "abcde"]
        return {
            "DBInstances": [
                {
                    "DBInstanceIdentifier": instance_id,
                    "DBInstanceClass": "db.r7g.large",
                    "Engine": "aurora-postgresql",
                    "DBInstanceStatus": "available",
                    "PerformanceInsightsEnabled": True,
                    "DbiResourceId": f"resource-{instance_id}",
                }
                for instance_id in instance_ids
            ]
        }


class FakePiClient:
    def __init__(self) -> None:
        self.calls = []

    def get_resource_metrics(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "MetricList": [{
                "Key": {
                    "Dimensions": {
                        "db.sql.id": "sql-1",
                        "db.sql.statement": (
                            "SELECT * FROM users_1234567890abcdef1234567890abcdef"
                        ),
                    }
                },
                "DataPoints": [{
                    "Timestamp": datetime(2026, 8, 12, 1, 5, tzinfo=timezone.utc),
                    "Value": 3.5,
                }],
            }]
        }


class FakeRdsSession:
    def __init__(self) -> None:
        self.rds = FakeRdsClient()
        self.pi = FakePiClient()
        self.requested_clients = []

    def client(self, name: str):
        self.requested_clients.append(name)
        if name == "rds":
            return self.rds
        if name == "pi":
            return self.pi
        raise AssertionError(name)


class RejectUnexpectedClientSession:
    def __init__(self) -> None:
        self.requested_clients = []

    def client(self, name: str):
        self.requested_clients.append(name)
        raise AssertionError(name)


def test_dimensionless_lambda_discovery_is_ranked_and_bounded() -> None:
    session = FakeSession()

    result = collect_lambda_top_offenders(
        session,
        DIMENSIONLESS_LAMBDA_ALARM,
        ALARM_HISTORY,
        classify_alarm_shape(DIMENSIONLESS_LAMBDA_ALARM),
    )

    assert result["status"] == "collected"
    assert [row["function_name"] for row in result["offenders"]] == [
        "scheduled-batch-delivery",
        "kds-consumer",
        "user-journey-node-runner",
        "segment-publisher-trigger",
        "anomaly-delivery-monitoring",
    ]
    assert len(result["offenders"]) == MAX_LAMBDA_OFFENDERS
    assert "Label" not in session.cloudwatch.calls[0]["MetricDataQueries"][0]
    assert result["derived_log_groups"][0] == (
        "/aws/lambda/scheduled-batch-delivery"
    )
    assert len(session.cloudwatch.calls) == 2
    assert all(
        (call["EndTime"] - call["StartTime"]).total_seconds()
        <= MAX_DISCOVERY_WINDOW_SECONDS
        for call in session.cloudwatch.calls
    )
    assert result["offenders"][0] == {
        "function_name": "scheduled-batch-delivery",
        "duration_sum_ms": 64_000_000,
        "duration_avg_ms": 8_000,
        "invocations": 800,
        "errors": 0,
        "throttles": 0,
        "evidence_level": "observed",
    }


def test_alarm_focus_window_is_capped_at_thirty_minutes() -> None:
    alarm = {**DIMENSIONLESS_LAMBDA_ALARM, "EvaluationPeriods": 120}

    start, end = alarm_focus_window(alarm, ALARM_HISTORY)

    assert (end - start).total_seconds() == MAX_DISCOVERY_WINDOW_SECONDS


def test_non_dimensionless_alarm_does_not_request_cloudwatch() -> None:
    session = FakeSession()
    dimensioned = {
        **DIMENSIONLESS_LAMBDA_ALARM,
        "Dimensions": [{"Name": "FunctionName", "Value": "example"}],
    }

    dimensioned_result = collect_lambda_top_offenders(
        session,
        dimensioned,
        ALARM_HISTORY,
        classify_alarm_shape(dimensioned),
    )
    non_lambda = {
        "AlarmName": "queue-age",
        "Namespace": "AWS/SQS",
        "MetricName": "ApproximateAgeOfOldestMessage",
        "Dimensions": [],
    }
    non_lambda_result = collect_lambda_top_offenders(
        session,
        non_lambda,
        ALARM_HISTORY,
        classify_alarm_shape(non_lambda),
    )

    assert dimensioned_result["status"] == "not_applicable"
    assert non_lambda_result["status"] == "not_applicable"
    assert session.requested_clients == []


def test_access_denied_is_returned_after_one_attempt() -> None:
    cloudwatch = AccessDeniedCloudWatchClient()
    session = FakeSession(cloudwatch)

    result = collect_lambda_top_offenders(
        session,
        DIMENSIONLESS_LAMBDA_ALARM,
        ALARM_HISTORY,
        classify_alarm_shape(DIMENSIONLESS_LAMBDA_ALARM),
    )

    assert result["status"] == "error"
    assert "AccessDeniedException" in result["error"]
    assert len(cloudwatch.calls) == 1


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


def test_lambda_signatures_use_one_bounded_multi_group_query() -> None:
    session = FakeLogsSession()
    groups = [f"/aws/lambda/function-{index}" for index in range(7)]

    result = collect_lambda_alarm_signatures(
        session,
        groups,
        DIMENSIONLESS_LAMBDA_ALARM,
        ALARM_HISTORY,
    )

    assert result["status"] == "collected"
    assert len(session.logs.start_calls) == 1
    call = session.logs.start_calls[0]
    assert call["logGroupNames"] == groups[:5]
    assert call["limit"] == 100
    for term in (
        "REPORT",
        "ERROR",
        "Exception",
        "timeout",
        "query",
        "deadlock",
        "connection",
    ):
        assert term in call["queryString"]
    assert len(result["signatures"]) <= 10
    assert result["db_evidence"] == [
        "Query timeout while waiting for postgres connection"
    ]


def test_explicit_cluster_precedes_fallback() -> None:
    session = FakeRdsSession()

    result = describe_rds_context(
        session,
        RDS_METRIC_MATH_ALARM,
        alarm_shape=classify_alarm_shape(RDS_METRIC_MATH_ALARM),
    )

    assert result["target_source"] == "alarm_explicit_cluster"
    assert result["cluster"]["id"] == "explicit-cluster"
    assert session.rds.cluster_requests == ["explicit-cluster"]
    assert len(result["instances"]) == 4


def test_candidate_db_alarm_uses_correlation_target() -> None:
    session = FakeRdsSession()
    alarm = {
        "AlarmName": "worker-db-query-latency",
        "Namespace": "Custom/Worker",
        "MetricName": "Latency",
        "Dimensions": [],
    }

    result = describe_rds_context(
        session,
        alarm,
        alarm_shape=classify_alarm_shape(alarm),
    )

    assert result["target_source"] == "production_default_correlation"
    assert result["db_relevance"]["level"] == "candidate"
    assert session.rds.cluster_requests == ["notifly-db-prod-cluster"]


def test_current_db_log_evidence_confirms_candidate() -> None:
    shape = classify_alarm_shape({
        "AlarmName": "worker-db-latency",
        "Namespace": "Custom/Worker",
        "MetricName": "Latency",
    })

    result = resolve_db_relevance(
        shape,
        {
            "current_error_details": [{
                "likely_error": "Query timeout waiting for postgres connection",
            }]
        },
        None,
    )

    assert result["level"] == "confirmed"
    assert "current_log:query timeout waiting for postgres connection" in result[
        "evidence"
    ]


def test_non_db_alarm_does_not_open_rds_client() -> None:
    session = RejectUnexpectedClientSession()

    result = describe_rds_context(
        session,
        NON_DB_ALARM,
        alarm_shape=classify_alarm_shape(NON_DB_ALARM),
    )

    assert result is None
    assert session.requested_clients == []


def test_fallback_pi_is_bounded_and_correlation_only() -> None:
    session = FakeRdsSession()
    alarm = {
        "AlarmName": "worker-db-query-latency",
        "Namespace": "Custom/Worker",
        "MetricName": "Latency",
        "Dimensions": [],
    }
    rds_context = describe_rds_context(
        session,
        alarm,
        alarm_shape=classify_alarm_shape(alarm),
    )

    result = collect_rds_performance_insights(
        session,
        rds_context,
        ALARM_HISTORY,
    )

    assert result["target_source"] == "production_default_correlation"
    assert result["evidence_level"] == "correlated"
    assert len(result["instances"]) == 4
    assert len(session.pi.calls) == 4
    assert all(
        (call["EndTime"] - call["StartTime"]).total_seconds()
        <= MAX_DISCOVERY_WINDOW_SECONDS
        for call in session.pi.calls
    )
