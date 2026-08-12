from __future__ import annotations

import sys
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
