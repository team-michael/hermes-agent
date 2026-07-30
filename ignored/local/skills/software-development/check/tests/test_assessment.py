from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPTS_ROOT = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from notifly_alert_context.assessment import (  # noqa: E402
    COMPACT_OUTPUT_MAX_BYTES,
    assess_helper_context,
    compact_output,
    decide_queue_recovery,
)
from notifly_alert_context.collectors import (  # noqa: E402
    queue_names_from_dlq_backlog,
)
from notifly_alert_context.config import MAX_DLQ_MARKER_BYTES  # noqa: E402
from notifly_alert_context.detect import (  # noqa: E402
    parse_dlq_backlog_marker,
    summarize_dlq_backlog_rows,
)


def _sqs_data(*, scoped: bool) -> dict:
    return {
        "detected": {
            "alarm_name": "QueueDepth",
            "queue_names": ["delivery-queue"],
            "keywords": [],
            "service_names": [],
            "lambda_names": [],
            "project_ids": [],
        },
        "alarm_summary": {
            "AlarmName": "QueueDepth",
            "Namespace": "AWS/SQS",
            "MetricName": "ApproximateNumberOfMessagesVisible",
            "Dimensions": [{"Name": "QueueName", "Value": "delivery-queue"}],
        },
        "alarm_history": {
            "latest_alarm_transition": {"timestamp": "2026-07-28T00:00:00Z"},
        },
        "metric_datapoints": {"datapoint_count": 1},
        "sqs_context": {"queue": "delivery-queue", "visible": 12},
        "scope_attribution": (
            {"service_indicators": ["delivery-queue"]} if scoped else {}
        ),
        "repo_code_hits": [{"path": "services/worker.ts"}],
    }


def _dlq_payload(*, observed_at: str = "2026-07-28T09:00:41Z") -> dict:
    return {
        "eventType": "DLQ_BACKLOG_DETECTED",
        "region": "ap-northeast-2",
        "observedAt": observed_at,
        "messageCount": 476,
        "queues": [
            {
                "queueName": "kakao-brand-message-queue-dlq",
                "visibleMessageCount": 272,
                "notVisibleMessageCount": 0,
                "delayedMessageCount": 0,
                "messageCount": 272,
                "messageRetentionPeriodSeconds": 345600,
            },
            {
                "queueName": "kakao-delivery-result-poller-queue-dlq",
                "visibleMessageCount": 204,
                "notVisibleMessageCount": 0,
                "delayedMessageCount": 0,
                "messageCount": 204,
                "messageRetentionPeriodSeconds": 345600,
            },
        ],
    }


def _dlq_marker(payload: dict) -> str:
    return (
        "2026-07-28T09:00:41.029Z request-id ERROR "
        + json.dumps(payload, separators=(",", ":"))
    )


def _dlq_data() -> dict:
    current = summarize_dlq_backlog_rows([
        {
            "@timestamp": "2026-07-28T09:00:41.029Z",
            "@message": _dlq_marker(_dlq_payload()),
        }
    ])
    recent = summarize_dlq_backlog_rows([
        {
            "@timestamp": "2026-07-28T09:00:41.029Z",
            "@message": _dlq_marker(_dlq_payload()),
        },
        {
            "@timestamp": "2026-07-28T08:50:41.029Z",
            "@message": _dlq_marker(
                _dlq_payload(observed_at="2026-07-28T08:50:41Z")
            ),
        },
    ])
    marker = {
        "current": current,
        "recent_sample": recent,
        "alarm_state_note": (
            "An OK transition is not evidence that a detected DLQ backlog "
            "was cleared."
        ),
    }
    queue_names = [
        queue["queueName"]
        for queue in _dlq_payload()["queues"]
    ]
    groups = []
    for queue_name in queue_names:
        source_name = queue_name[:-4]
        groups.append({
            "detected_queue": queue_name,
            "related_queues": [
                {
                    "queue_name": queue_name,
                    "attributes": {
                        "ApproximateNumberOfMessages": (
                            "272"
                            if queue_name.startswith("kakao-brand")
                            else "204"
                        ),
                        "RedriveAllowPolicy": {
                            "redrivePermission": "byQueue",
                            "sourceQueueArns": [
                                "arn:aws:sqs:ap-northeast-2:702197142747:"
                                + source_name
                            ],
                        },
                    },
                    "dead_letter_source_queues": [source_name],
                    "lambda_consumers": {
                        "status": "ok",
                        "mappings": [],
                    },
                },
                {
                    "queue_name": source_name,
                    "attributes": {
                        "ApproximateNumberOfMessages": "0",
                        "RedrivePolicy": {
                            "deadLetterTargetArn": (
                                "arn:aws:sqs:ap-northeast-2:702197142747:"
                                + queue_name
                            ),
                            "maxReceiveCount": (
                                1
                                if source_name.startswith("kakao-brand-message")
                                else 3
                            ),
                        },
                    },
                    "dead_letter_source_queues": [],
                    "lambda_consumers": {
                        "status": "ok",
                        "mappings": [
                            {
                                "function_name": (
                                    "kakao-brand-message-delivery"
                                    if source_name.startswith(
                                        "kakao-brand-message"
                                    )
                                    else "kakao-delivery-result-poller"
                                ),
                                "function_arn": (
                                    "arn:aws:lambda:ap-northeast-2:"
                                    f"702197142747:function:{source_name}"
                                ),
                                "state": "Enabled",
                                "last_processing_result": "OK",
                                "function_response_types": [],
                            }
                        ],
                    },
                },
            ],
        })
    return {
        "detected": {
            "alarm_name": "anomaly-delivery-monitoring lambda error",
            "queue_names": queue_names,
            "keywords": [],
            "service_names": [],
            "lambda_names": ["anomaly-delivery-monitoring"],
            "project_ids": [],
        },
        "alarm_summary": {
            "AlarmName": "anomaly-delivery-monitoring lambda error",
            "Namespace": "ConsoleErrors",
            "MetricName": "anomaly-delivery-monitoring lambda console error",
            "StateValue": "OK",
            "Dimensions": [],
        },
        "alarm_history": {
            "latest_alarm_transition": {
                "timestamp": "2026-07-28T09:01:09Z"
            }
        },
        "metric_datapoints": {"datapoint_count": 1},
        "logs_insights": {
            "current_alarm_window": {
                "start": "2026-07-28T09:00:00Z",
                "end": "2026-07-28T09:01:00Z",
            },
            "current_trigger_contexts": [
                {"surrounding_lines": ["DLQ_BACKLOG_DETECTED"]}
            ],
            "current_error_details": [
                {"likely_error": "DLQ_BACKLOG_DETECTED"}
            ],
            "dlq_backlog": marker,
        },
        "dlq_backlog": marker,
        "sqs_context": {"days": 7, "queues": groups},
        "lambda_context": {
            "functions": [
                {
                    "configuration": {
                        "function_name": "anomaly-delivery-monitoring"
                    },
                    "metrics": [
                        {
                            "metric_name": "Errors",
                            "statistic": "Sum",
                            "summary": {
                                "period": 600,
                                "datapoint_count": 10,
                                "latest": 0,
                                "max": 0,
                            },
                        },
                        {
                            "metric_name": "Duration",
                            "statistic": "p99",
                            "summary": {
                                "period": 600,
                                "datapoint_count": 10,
                                "latest": 44500,
                                "max": 45100,
                            },
                        },
                    ],
                }
            ]
        },
        "scope_attribution": {
            "infra_indicators": queue_names,
        },
        "repo_code_hits": [{"path": "services/monitor/index.ts"}],
    }


def test_parses_structured_dlq_marker_without_raw_payload() -> None:
    result = parse_dlq_backlog_marker(_dlq_marker(_dlq_payload()))

    assert result["marker_seen"] is True
    event = result["event"]
    assert event["message_count"] == 476
    assert event["calculated_message_count"] == 476
    assert event["count_consistent"] is True
    assert [queue["queue_name"] for queue in event["queues"]] == [
        "kakao-brand-message-queue-dlq",
        "kakao-delivery-result-poller-queue-dlq",
    ]
    assert "queueArn" not in json.dumps(result)


def test_dlq_marker_parser_isolates_malformed_and_oversized_payloads() -> None:
    malformed = parse_dlq_backlog_marker(
        'ERROR {"eventType":"DLQ_BACKLOG_DETECTED","queues":['
    )
    oversized_payload = _dlq_payload()
    oversized_payload["padding"] = "x" * MAX_DLQ_MARKER_BYTES
    oversized = parse_dlq_backlog_marker(
        _dlq_marker(oversized_payload)
    )

    assert malformed["parse_issue"]["type"] == "malformed_json"
    assert oversized["parse_issue"]["type"] == "oversized_marker"
    assert "event" not in malformed
    assert "event" not in oversized


def test_dlq_marker_queues_feed_sqs_collection() -> None:
    data = _dlq_data()

    assert queue_names_from_dlq_backlog(data["logs_insights"]) == [
        "kakao-brand-message-queue-dlq",
        "kakao-delivery-result-poller-queue-dlq",
    ]


def test_dlq_backlog_has_bounded_needs_fix_disposition() -> None:
    data = _dlq_data()
    result = assess_helper_context(data)

    assert result["can_answer_root_cause"] is True
    assert result["required_followups"] == []
    disposition = result["dlq_disposition"]
    assert disposition["judgment"] == "needs_fix"
    assert disposition["disposition"] == "hold_for_evidence"
    assert disposition["message_count"] == 476
    assert disposition["alarm_ok_means_resolved"] is False
    assert disposition["customer_impact"] == "unconfirmed_backlog_present"
    assert disposition["action_candidates"]["redrive"]["recommended"] is False
    assert disposition["action_candidates"]["purge"]["recommended"] is False
    assert disposition["underlying_failure_cause"] == "unconfirmed"
    assert disposition["monitor_lambda_health"][0]["metrics"]["Errors"][
        "max"
    ] == 0
    assert any(
        "receive_message" in guardrail
        for guardrail in disposition["response_guardrails"]
    )
    response_facts = disposition["response_facts"]
    assert response_facts["observed_at_kst"] == (
        "2026-07-28 18:00:41 KST"
    )
    assert response_facts["recurrence_sample"] == {
        "sample_is_complete_history": False,
        "continuity_confirmed": False,
        "persistence_duration_confirmed": False,
        "event_count": 2,
        "same_as_latest_snapshot_count": 2,
        "distinct_snapshot_count": 1,
        "sample_start_kst": "2026-07-28 17:50:41 KST",
        "sample_end_kst": "2026-07-28 18:00:41 KST",
    }
    assert all(
        queue["consumer_runtime_metrics_collected"] is False
        for queue in response_facts["queues"]
    )
    assert disposition["mutation_performed"] is False


def test_dlq_queue_recovery_facts_separate_capability_from_safety() -> None:
    disposition = assess_helper_context(_dlq_data())["dlq_disposition"]

    assert [
        queue["recovery_decision"]["disposition"]
        for queue in disposition["queues"]
    ] == ["hold_for_evidence", "hold_for_evidence"]
    assert all(
        queue["redrive_capability"]["supported"] is True
        for queue in disposition["queues"]
    )
    assert [
        queue["redrive_capability"]["max_receive_count"]
        for queue in disposition["queues"]
    ] == [1, 3]
    assert all(
        queue["consumer_contract"]["partial_batch_failure_reporting"]
        is False
        for queue in disposition["queues"]
    )
    assert all(
        queue["recovery_decision"]["mutation_allowed"] is False
        for queue in disposition["queues"]
    )


def test_queue_recovery_requires_complete_redrive_evidence() -> None:
    decision = decide_queue_recovery({
        "technical_redrive_supported": True,
        "failure_class": "transient",
        "replay_safety": "idempotent",
        "obsolescence": "not_obsolete",
        "evidence_preserved": True,
    })

    assert decision["disposition"] == "redrive_candidate"
    assert decision["action_candidates"]["redrive"]["recommended"] is True
    assert decision["action_candidates"]["purge"]["recommended"] is False
    assert decision["mutation_allowed"] is False


def test_queue_recovery_requires_complete_purge_evidence() -> None:
    decision = decide_queue_recovery({
        "technical_redrive_supported": True,
        "failure_class": "terminal",
        "replay_safety": "unsafe",
        "obsolescence": "confirmed_obsolete",
        "evidence_preserved": True,
    })

    assert decision["disposition"] == "purge_candidate"
    assert decision["action_candidates"]["redrive"]["recommended"] is False
    assert decision["action_candidates"]["purge"]["recommended"] is True
    assert decision["mutation_allowed"] is False


def test_queue_age_and_enabled_mapping_never_decide_recovery() -> None:
    decision = decide_queue_recovery({
        "technical_redrive_supported": True,
        "oldest_message_age_seconds": 345000,
        "consumer_mapping_state": "Enabled",
        "failure_class": "unknown",
        "replay_safety": "unknown",
        "obsolescence": "unknown",
        "evidence_preserved": False,
    })

    assert decision["disposition"] == "hold_for_evidence"
    assert decision["action_candidates"]["redrive"]["recommended"] is False
    assert decision["action_candidates"]["purge"]["recommended"] is False
    assert set(decision["missing_evidence"]) == {
        "failure_class",
        "replay_safety",
        "obsolescence",
        "evidence_preservation",
    }


def test_compact_output_preserves_dlq_queues_and_disposition() -> None:
    data = _dlq_data()
    data["helper_assessment"] = assess_helper_context(data)

    result = compact_output(data)
    encoded = json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
        default=str,
    ).encode("utf-8")

    assert len(encoded) <= COMPACT_OUTPUT_MAX_BYTES
    assert result["dlq_disposition"]["judgment"] == "needs_fix"
    assert result["dlq_disposition"]["disposition"] == "hold_for_evidence"
    assert [
        queue["queue_name"]
        for queue in result["dlq_disposition"]["response_facts"]["queues"]
    ] == [
        "kakao-brand-message-queue-dlq",
        "kakao-delivery-result-poller-queue-dlq",
    ]
    assert [
        queue["consumers"][0]["function_name"]
        for queue in result["dlq_disposition"]["response_facts"]["queues"]
    ] == [
        "kakao-brand-message-delivery",
        "kakao-delivery-result-poller",
    ]


def test_compact_dlq_output_stays_under_cap_with_large_history() -> None:
    data = _dlq_data()
    data["alarm_history"].update({
        "sample_items": [
            {
                "timestamp": f"2026-07-28T{hour:02d}:01:09Z",
                "type": "StateUpdate",
                "new_state": "ALARM",
                "summary": "x" * 220,
            }
            for hour in range(12)
        ],
        "top_summaries": [["y" * 220, 12]],
        "alarm_daily_counts": {
            f"2026-07-{day:02d}": day
            for day in range(1, 29)
        },
    })
    data["helper_assessment"] = assess_helper_context(data)

    result = compact_output(data)
    encoded = json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
        default=str,
    ).encode("utf-8")

    assert len(encoded) <= COMPACT_OUTPUT_MAX_BYTES


def test_required_missing_context_always_blocks_answerability() -> None:
    result = assess_helper_context(_sqs_data(scoped=False))

    assert result["root_cause_evidence"] == ["sqs_queue_metrics"]
    assert result["can_answer_root_cause"] is False
    assert any(
        item["key"] == "scope_basis"
        for item in result["missing_required_context"]
    )
    assert len(result["required_followups"]) <= 2


def test_answerable_result_has_no_required_followups() -> None:
    result = assess_helper_context(_sqs_data(scoped=True))

    assert result["can_answer_root_cause"] is True
    assert result["next_action"] == "finalize_now_no_more_tools"
    assert result["missing_required_context"] == []
    assert result["required_followups"] == []
    assert result["note"].startswith("STOP:")


def test_followups_are_hard_capped_at_two() -> None:
    result = assess_helper_context({})

    assert result["can_answer_root_cause"] is False
    assert len(result["required_followups"]) <= 2
    assert result["omitted_followup_count"] >= 1


def test_compact_output_is_capped_and_keeps_decision_fields() -> None:
    huge_line = "x" * 20_000
    data = _sqs_data(scoped=False)
    data["logs_insights"] = {
        "log_groups": ["/aws/lambda/demo"],
        "current_alarm_window": {
            "start": "2026-07-28T00:00:00Z",
            "end": "2026-07-28T00:05:00Z",
        },
        "current_trigger_contexts": [
            {
                "error_blocks": [
                    {"lines": [huge_line for _ in range(20)]}
                    for _ in range(20)
                ],
            }
            for _ in range(20)
        ],
        "current_error_details": [
            {"reason": huge_line, "stack": huge_line}
            for _ in range(20)
        ],
        "daily_counts_30d": [
            {"day": f"2026-07-{day:02d}", "count": day}
            for day in range(1, 31)
        ],
    }
    data["repo_code_hits"] = [
        {"path": f"src/{index}.ts", "line": huge_line}
        for index in range(30)
    ]
    data["helper_assessment"] = assess_helper_context(data)

    result = compact_output(data)
    encoded = json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
        default=str,
    ).encode("utf-8")

    assert len(encoded) <= COMPACT_OUTPUT_MAX_BYTES
    assert "can_answer_root_cause" in result
    assert "missing_required_context" in result
    assert "required_followups" in result
    assert "alarm" in result


if __name__ == "__main__":
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"{len(tests)} assessment tests passed")
