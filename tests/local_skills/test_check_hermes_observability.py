from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = (
    REPO_ROOT / "ignored" / "local" / "skills" / "software-development" / "check"
)
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from notifly_alert_context.assessment import compact_output  # noqa: E402
from notifly_alert_context.hermes_observability import (  # noqa: E402
    collect_hermes_observability_context,
    pair_pressure_events,
    resolve_pressure_session,
)


PARENT = "20260730_021248_fd8920ce"
ACTIVE_CHILD = "20260730_044352_4ae8ad"
OTHER_CHILD = "20260730_044352_ea6a5e"


def _create_profile_db(root: Path) -> None:
    profile_home = root / "profiles" / "andrej"
    profile_home.mkdir(parents=True)
    db = sqlite3.connect(profile_home / "state.db")
    db.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT,
            parent_session_id TEXT,
            started_at REAL,
            ended_at REAL,
            title TEXT
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            role TEXT,
            content TEXT,
            tool_call_id TEXT,
            tool_calls TEXT,
            tool_name TEXT,
            timestamp REAL,
            active INTEGER DEFAULT 1
        );
        CREATE INDEX idx_messages_session ON messages(session_id);
        """
    )
    db.executemany(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
        [
            (PARENT, "slack", None, 10.0, None, "대형 MAU 비용 산식 검토"),
            (ACTIVE_CHILD, "subagent", PARENT, 100.0, 240.0, None),
            (OTHER_CHILD, "subagent", PARENT, 90.0, 240.0, None),
        ],
    )
    task = (
        "Braze 실제 구매 가격의 신뢰 가능한 시장 레퍼런스를 수집하라. "
        "Vendr, Tropic, Spendflo 자료를 조사하라."
    )
    queries = ", ".join(repr(f"Braze price {index}") for index in range(23))
    code = (
        "from hermes_tools import web_search\n"
        f"queries = [{queries}]\n"
        "for query in queries:\n"
        "    web_search(query, limit=8)\n"
    )
    active_call = json.dumps([
        {
            "id": "active-call",
            "function": {
                "name": "execute_code",
                "arguments": json.dumps({"code": code}),
            },
        }
    ])
    other_call = json.dumps([
        {
            "id": "other-call",
            "function": {
                "name": "execute_code",
                "arguments": json.dumps({"code": "print('done')"}),
            },
        }
    ])
    db.executemany(
        """
        INSERT INTO messages(
            session_id, role, content, tool_call_id, tool_calls,
            tool_name, timestamp, active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """,
        [
            (ACTIVE_CHILD, "user", task, None, None, None, 100.0),
            (ACTIVE_CHILD, "assistant", None, None, active_call, None, 120.0),
            (ACTIVE_CHILD, "tool", None, "active-call", None, "execute_code", 200.0),
            (OTHER_CHILD, "user", "Other task", None, None, None, 90.0),
            (OTHER_CHILD, "assistant", None, None, other_call, None, 95.0),
            (OTHER_CHILD, "tool", None, "other-call", None, "execute_code", 110.0),
        ],
    )
    db.commit()
    db.close()


def _open_event(timestamp: float = 150.0) -> dict:
    return {
        "timestamp": timestamp,
        "instance_id": "i-test",
        "profile": "andrej",
        "signal": "profile_pressure",
        "state": "open",
        "reasons": ["read"],
        "read_mib_s": 65.057,
        "cpu_percent": 5.83,
        "memory_percent": 31.97,
        "session_id_short": "20260730_044",
        "source": "subagent",
        "tool_name": "execute_code",
    }


def _recovered_event(timestamp: float = 210.0) -> dict:
    return {
        "timestamp": timestamp,
        "instance_id": "i-test",
        "profile": "andrej",
        "signal": "profile_pressure",
        "state": "recovered",
        "read_mib_s": 18.472,
    }


class _LogsClient:
    def filter_log_events(self, **kwargs):
        second_open = {
            "timestamp": 185.0,
            "instance_id": "i-test",
            "profile": "andrej",
            "signal": "profile_pressure",
            "state": "open",
            "reasons": ["read"],
            "read_mib_s": 56.151,
            "session_id_short": "20260730_021",
            "source": "slack",
            "tool_name": "execute_code",
        }
        second_recovery = {
            **_recovered_event(230.0),
            "read_mib_s": 17.509,
        }
        return {
            "events": [
                {
                    "timestamp": 151_000,
                    "message": json.dumps(_open_event()),
                },
                {
                    "timestamp": 211_000,
                    "message": json.dumps(_recovered_event()),
                },
                {
                    "timestamp": 231_000,
                    "message": json.dumps(second_open),
                },
                {
                    "timestamp": 232_000,
                    "message": json.dumps(second_recovery),
                },
            ]
        }


class _CloudWatchClient:
    def get_metric_statistics(self, **kwargs):
        return {
            "Datapoints": [
                {
                    "Timestamp": datetime.fromtimestamp(140, tz=timezone.utc),
                    "Minimum": 1.0,
                },
                {
                    "Timestamp": datetime.fromtimestamp(220, tz=timezone.utc),
                    "Minimum": 1.0,
                },
            ]
        }


class _Session:
    def client(self, service_name: str):
        if service_name == "logs":
            return _LogsClient()
        if service_name == "cloudwatch":
            return _CloudWatchClient()
        raise AssertionError(service_name)


def _alarm() -> dict:
    return {
        "_alarm_type": "MetricAlarm",
        "AlarmName": "hermes-agent-service-unhealthy",
        "Namespace": "CWAgent",
        "MetricName": "HermesServiceHealthy",
        "Statistic": "Minimum",
        "Period": 60,
        "Threshold": 0.5,
        "ComparisonOperator": "LessThanOrEqualToThreshold",
        "TreatMissingData": "breaching",
        "Dimensions": [
            {"Name": "InstanceId", "Value": "i-test"},
            {"Name": "metric_type", "Value": "gauge"},
        ],
    }


def _history() -> dict:
    return {
        "latest_alarm_transition": {
            "timestamp": datetime.fromtimestamp(190, tz=timezone.utc).isoformat(),
            "state_reason": (
                "Threshold Crossed: 3 datapoints were missing and 2 datapoints "
                "were not breaching."
            ),
        },
        "sample_items": [
            {
                "timestamp": datetime.fromtimestamp(180, tz=timezone.utc).isoformat(),
                "new_state": "ALARM",
            }
        ],
    }


def test_resolve_pressure_session_matches_exact_active_tool(tmp_path: Path) -> None:
    _create_profile_db(tmp_path)

    result = resolve_pressure_session(tmp_path, _open_event())

    assert result is not None
    assert result["session_id"] == ACTIVE_CHILD
    assert result["session_link"] == f"@session:andrej/{ACTIVE_CHILD}"
    assert result["parent_session_link"] == f"@session:andrej/{PARENT}"
    assert result["parent_title"] == "대형 MAU 비용 산식 검토"
    assert result["attribution_confidence"] == "active_tool_interval_match"
    assert result["task_excerpt"].startswith("Braze 실제 구매 가격")
    assert result["tool"]["tool_name"] == "execute_code"
    assert result["tool"]["execution_summary"] == {
        "operations": ["web_search"],
        "batch_item_count": 23,
        "execution_mode": "sequential_loop",
    }


def test_pair_pressure_events_keeps_open_and_recovery_measurements() -> None:
    incidents = pair_pressure_events([_open_event(), _recovered_event()])

    assert len(incidents) == 1
    assert incidents[0]["open"]["read_mib_s"] == 65.057
    assert incidents[0]["recovered"]["read_mib_s"] == 18.472
    assert incidents[0]["duration_seconds"] == 60.0


def test_live_collector_emits_report_ready_full_session_context(tmp_path: Path) -> None:
    _create_profile_db(tmp_path)

    result = collect_hermes_observability_context(
        _Session(),
        _alarm(),
        _history(),
        root=tmp_path,
    )

    assert result["status"] == "collected"
    assert result["alarm_trigger"]["classification"] == "missing_data_breach"
    assert result["alarm_trigger"]["observed_breaching_count"] == 0
    facts = result["report_facts"]
    assert facts["parent_session"] == f"@session:andrej/{PARENT}"
    assert facts["active_session"] == f"@session:andrej/{ACTIVE_CHILD}"
    assert facts["read_mib_s"] == 65.057
    assert facts["tool"]["execution_summary"]["batch_item_count"] == 23
    assert facts["related_same_parent_incidents"] == [
        {
            "opened_at_kst": "1970-01-01 09:03:05 KST",
            "read_mib_s": 56.151,
            "recovered_at_kst": "1970-01-01 09:03:50 KST",
        }
    ]

    compact = compact_output({
        "alarm_summary": _alarm(),
        "alarm_history": _history(),
        "metric_datapoints": {"datapoint_count": 2},
        "hermes_observability": result,
        "helper_assessment": {
            "can_answer_root_cause": True,
            "next_action": "answer_now",
            "missing_required_context": [],
            "required_followups": [],
            "root_cause_evidence": [
                "hermes_profile_pressure_events",
                "hermes_session_attribution",
            ],
        },
    })
    assert (
        compact["hermes_observability"]["report_facts"]["active_session"]
        == f"@session:andrej/{ACTIVE_CHILD}"
    )
