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
)
from notifly_alert_context.config import (  # noqa: E402
    MAX_DISCOVERY_WINDOW_SECONDS,
    MAX_LAMBDA_OFFENDERS,
)


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
                        "Label": name,
                        "Timestamps": [datetime(2026, 8, 12, 1, 5, tzinfo=timezone.utc)],
                        "Values": [value],
                        "StatusCode": "Complete",
                    }
                    for name, value in [
                        ("small-function", 10),
                        ("kds-consumer", 50_000_000),
                        ("scheduled-batch-delivery", 64_000_000),
                        ("anomaly-delivery-monitoring", 20_000_000),
                        ("segment-publisher-trigger", 30_000_000),
                        ("user-journey-node-runner", 40_000_000),
                    ]
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
