from __future__ import annotations

import json
import sys
import unittest
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

from notifly_alert_context.assessment import (  # noqa: E402
    COMPACT_OUTPUT_MAX_BYTES,
    assess_helper_context,
    compact_output,
    decide_queue_recovery,
)
from notifly_alert_context.detect import (  # noqa: E402
    parse_dlq_backlog_marker,
    summarize_dlq_backlog_rows,
)


def _marker_payload() -> dict:
    return {
        "eventType": "DLQ_BACKLOG_DETECTED",
        "region": "ap-northeast-2",
        "observedAt": "2026-07-28T09:00:41Z",
        "messageCount": 12,
        "queues": [
            {
                "queueName": "delivery-a-dlq",
                "visibleMessageCount": 7,
                "notVisibleMessageCount": 0,
                "delayedMessageCount": 0,
                "messageCount": 7,
                "messageRetentionPeriodSeconds": 345600,
            },
            {
                "queueName": "polling-b-dlq",
                "visibleMessageCount": 5,
                "notVisibleMessageCount": 0,
                "delayedMessageCount": 0,
                "messageCount": 5,
                "messageRetentionPeriodSeconds": 345600,
            },
        ],
    }


def _marker_row() -> dict:
    message = json.dumps(_marker_payload(), separators=(",", ":"))
    return {
        "@timestamp": "2026-07-28T09:00:41.029Z",
        "@message": f"2026-07-28T09:00:41.029Z request ERROR {message}",
    }


def _queue_group(dlq_name: str, source_name: str, max_receive_count: int) -> dict:
    return {
        "detected_queue": dlq_name,
        "related_queues": [
            {
                "queue_name": dlq_name,
                "attributes": {
                    "ApproximateNumberOfMessages": "1",
                    "ApproximateNumberOfMessagesNotVisible": "0",
                    "ApproximateNumberOfMessagesDelayed": "0",
                    "RedriveAllowPolicy": {
                        "redrivePermission": "byQueue",
                        "sourceQueueArns": [f"arn:aws:sqs:region:account:{source_name}"],
                    },
                },
                "dead_letter_source_queues": [source_name],
                "lambda_consumers": {"status": "ok", "mappings": []},
            },
            {
                "queue_name": source_name,
                "attributes": {
                    "ApproximateNumberOfMessages": "0",
                    "RedrivePolicy": {
                        "deadLetterTargetArn": f"arn:aws:sqs:region:account:{dlq_name}",
                        "maxReceiveCount": max_receive_count,
                    },
                },
                "dead_letter_source_queues": [],
                "lambda_consumers": {
                    "status": "ok",
                    "mappings": [
                        {
                            "function_name": f"{source_name}-consumer",
                            "function_arn": f"arn:aws:lambda:region:account:function:{source_name}-consumer",
                            "state": "Enabled",
                            "last_processing_result": "OK",
                            "function_response_types": [],
                        }
                    ],
                },
            },
        ],
    }


def _dlq_data() -> dict:
    summary = summarize_dlq_backlog_rows([_marker_row()])
    marker = {
        "current": summary,
        "recent_sample": summary,
        "alarm_state_note": "An OK transition does not prove that the backlog cleared.",
    }
    return {
        "detected": {
            "alarm_name": "example DLQ monitor",
            "queue_names": ["delivery-a-dlq", "polling-b-dlq"],
            "keywords": [],
            "service_names": [],
            "lambda_names": ["example-monitor"],
            "project_ids": [],
        },
        "alarm_summary": {
            "AlarmName": "example DLQ monitor",
            "Namespace": "ConsoleErrors",
            "MetricName": "example monitor error",
            "StateValue": "OK",
            "Dimensions": [],
        },
        "alarm_history": {
            "latest_alarm_transition": {"timestamp": "2026-07-28T09:01:09Z"},
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
        "sqs_context": {
            "days": 7,
            "queues": [
                _queue_group("delivery-a-dlq", "delivery-a", 1),
                _queue_group("polling-b-dlq", "polling-b", 3),
            ],
        },
        "lambda_context": {"functions": []},
        "scope_attribution": {
            "infra_indicators": ["delivery-a-dlq", "polling-b-dlq"]
        },
        "repo_code_hits": [{"path": "services/example.ts"}],
    }


class QueueRecoveryDecisionTest(unittest.TestCase):
    def test_plain_inspection_failure_marker_is_preserved(self) -> None:
        parsed = parse_dlq_backlog_marker(
            '2026-07-28T10:40:00Z request ERROR '
            'DLQ_BACKLOG_INSPECTION_FAILED queue inspection failed'
        )

        self.assertTrue(parsed["marker_seen"])
        self.assertEqual(
            parsed["parse_issue"],
            {
                "type": "inspection_failed",
                "event_type": "DLQ_BACKLOG_INSPECTION_FAILED",
            },
        )

    def test_marker_parses_when_event_type_is_not_the_first_field(self) -> None:
        payload = {
            "queues": [
                {
                    "queueName": "delivery-a-dlq",
                    "messageCount": 1,
                }
            ],
            "eventType": "DLQ_BACKLOG_DETECTED",
            "messageCount": 1,
        }

        parsed = parse_dlq_backlog_marker(json.dumps(payload))

        self.assertTrue(parsed["marker_seen"])
        self.assertEqual(parsed["event"]["message_count"], 1)
        self.assertEqual(
            parsed["event"]["queues"][0]["queue_name"],
            "delivery-a-dlq",
        )

    def test_inspection_failure_stays_needs_fix_and_non_mutating(self) -> None:
        data = _dlq_data()
        summary = summarize_dlq_backlog_rows(
            [
                {
                    "@timestamp": "2026-07-28T10:40:00Z",
                    "@message": "DLQ_BACKLOG_INSPECTION_FAILED access denied",
                }
            ]
        )
        marker = {
            "current": summary,
            "recent_sample": summary,
            "alarm_state_note": "Alarm state does not prove queue state.",
        }
        data["dlq_backlog"] = marker
        data["logs_insights"]["dlq_backlog"] = marker
        data["sqs_context"] = None

        disposition = assess_helper_context(data)["dlq_disposition"]

        self.assertEqual(
            disposition["event_type"],
            "DLQ_BACKLOG_INSPECTION_FAILED",
        )
        self.assertEqual(disposition["judgment"], "needs_fix")
        self.assertEqual(disposition["disposition"], "hold_for_evidence")
        self.assertEqual(
            disposition["response_facts"]["inspection_issues"][0]["type"],
            "inspection_failed",
        )
        self.assertFalse(disposition["mutation_performed"])

    def test_redrive_requires_complete_evidence(self) -> None:
        decision = decide_queue_recovery(
            {
                "technical_redrive_supported": True,
                "failure_class": "transient",
                "replay_safety": "idempotent",
                "obsolescence": "not_obsolete",
                "evidence_preserved": True,
            }
        )

        self.assertEqual(decision["disposition"], "redrive_candidate")
        self.assertTrue(decision["action_candidates"]["redrive"]["recommended"])
        self.assertFalse(decision["mutation_allowed"])

    def test_purge_requires_complete_evidence(self) -> None:
        decision = decide_queue_recovery(
            {
                "technical_redrive_supported": True,
                "failure_class": "terminal",
                "obsolescence": "confirmed_obsolete",
                "evidence_preserved": True,
            }
        )

        self.assertEqual(decision["disposition"], "purge_candidate")
        self.assertTrue(decision["action_candidates"]["purge"]["recommended"])
        self.assertEqual(decision["missing_evidence"], [])
        self.assertFalse(decision["mutation_allowed"])

    def test_age_and_enabled_mapping_do_not_unlock_recovery(self) -> None:
        decision = decide_queue_recovery(
            {
                "technical_redrive_supported": True,
                "oldest_message_age_seconds": 345000,
                "consumer_mapping_state": "Enabled",
                "failure_class": "unknown",
                "replay_safety": "unknown",
                "obsolescence": "unknown",
                "evidence_preserved": False,
            }
        )

        self.assertEqual(decision["disposition"], "hold_for_evidence")
        self.assertEqual(
            set(decision["missing_evidence"]),
            {
                "failure_class",
                "replay_safety",
                "obsolescence",
                "evidence_preservation",
            },
        )

    def test_live_shape_separates_capability_from_safety(self) -> None:
        disposition = assess_helper_context(_dlq_data())["dlq_disposition"]

        self.assertEqual(
            [queue["redrive_capability"]["max_receive_count"] for queue in disposition["queues"]],
            [1, 3],
        )
        self.assertTrue(
            all(queue["redrive_capability"]["supported"] for queue in disposition["queues"])
        )
        self.assertTrue(
            all(
                queue["recovery_decision"]["disposition"] == "hold_for_evidence"
                for queue in disposition["queues"]
            )
        )

    def test_malformed_redrive_allow_policy_fails_closed(self) -> None:
        data = _dlq_data()
        data["sqs_context"]["queues"][0]["related_queues"][0][
            "attributes"
        ]["RedriveAllowPolicy"] = "{malformed"

        capability = assess_helper_context(data)["dlq_disposition"]["queues"][
            0
        ]["redrive_capability"]

        self.assertFalse(capability["supported"])
        self.assertEqual(capability["permission"], "unknown")

    def test_live_sqs_depth_replaces_stale_marker_depth(self) -> None:
        disposition = assess_helper_context(_dlq_data())["dlq_disposition"]

        self.assertEqual(disposition["marker_message_count"], 12)
        self.assertEqual(disposition["message_count"], 2)
        self.assertEqual(
            disposition["response_facts"]["processing_status"],
            "needs_fix",
        )
        self.assertEqual(
            [
                (queue["marker_depth"], queue["depth"], queue["depth_source"])
                for queue in disposition["queues"]
            ],
            [
                (7, 1, "live_sqs_attributes"),
                (5, 1, "live_sqs_attributes"),
            ],
        )

    def test_zero_live_sqs_depth_resolves_recovery_decision(self) -> None:
        data = _dlq_data()
        for group in data["sqs_context"]["queues"]:
            group["related_queues"][0]["attributes"][
                "ApproximateNumberOfMessages"
            ] = "0"

        disposition = assess_helper_context(data)["dlq_disposition"]

        self.assertEqual(disposition["message_count"], 0)
        self.assertEqual(disposition["disposition"], "no_action")
        self.assertEqual(
            disposition["response_facts"]["processing_status"],
            "no_action",
        )
        self.assertTrue(disposition["live_sqs_observed_empty"])
        self.assertTrue(
            all(
                queue["recovery_decision"]["disposition"] == "no_action"
                for queue in disposition["queues"]
            )
        )

    def test_partial_or_invalid_sqs_attributes_never_resolve_marker(self) -> None:
        for attributes in (
            {"ApproximateNumberOfMessages": "0"},
            {
                "ApproximateNumberOfMessages": "invalid",
                "ApproximateNumberOfMessagesNotVisible": "0",
                "ApproximateNumberOfMessagesDelayed": "0",
            },
        ):
            with self.subTest(attributes=attributes):
                data = _dlq_data()
                for group in data["sqs_context"]["queues"]:
                    group["related_queues"][0]["attributes"] = attributes

                disposition = assess_helper_context(data)["dlq_disposition"]

                self.assertEqual(disposition["message_count"], 12)
                self.assertEqual(
                    disposition["disposition"],
                    "hold_for_evidence",
                )
                self.assertFalse(disposition["live_sqs_snapshot_complete"])

    def test_missing_marker_total_falls_back_to_calculated_queue_total(self) -> None:
        payload = _marker_payload()
        payload.pop("messageCount")
        summary = summarize_dlq_backlog_rows(
            [
                {
                    "@timestamp": "2026-07-28T09:00:41Z",
                    "@message": json.dumps(payload, separators=(",", ":")),
                }
            ]
        )
        data = _dlq_data()
        marker = {
            "current": summary,
            "recent_sample": summary,
            "alarm_state_note": "Alarm state does not prove queue state.",
        }
        data["dlq_backlog"] = marker
        data["logs_insights"]["dlq_backlog"] = marker
        data["sqs_context"] = None

        disposition = assess_helper_context(data)["dlq_disposition"]

        self.assertEqual(disposition["marker_message_count"], 12)
        self.assertEqual(disposition["message_count"], 12)
        self.assertEqual(disposition["disposition"], "hold_for_evidence")

    def test_mixed_live_and_marker_depths_never_report_cleared(self) -> None:
        data = _dlq_data()
        first, second = data["sqs_context"]["queues"]
        first["related_queues"][0]["attributes"].update(
            {
                "ApproximateNumberOfMessages": "0",
                "ApproximateNumberOfMessagesNotVisible": "0",
                "ApproximateNumberOfMessagesDelayed": "0",
            }
        )
        second["related_queues"][0]["attributes"] = {
            "ApproximateNumberOfMessages": "0"
        }

        disposition = assess_helper_context(data)["dlq_disposition"]

        self.assertFalse(disposition["live_sqs_snapshot_complete"])
        self.assertFalse(disposition["live_sqs_observed_empty"])
        self.assertEqual(disposition["message_count"], 12)
        self.assertEqual(
            [queue["depth_source"] for queue in disposition["queues"]],
            ["live_sqs_attributes", "marker_snapshot_fallback"],
        )
        self.assertEqual(disposition["disposition"], "hold_for_evidence")

    def test_compact_dlq_output_stays_under_ten_kib(self) -> None:
        data = _dlq_data()
        data["alarm_history"].update(
            {
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
                    f"2026-07-{day:02d}": day for day in range(1, 29)
                },
            }
        )
        data["helper_assessment"] = assess_helper_context(data)

        result = compact_output(data)
        encoded = json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        ).encode("utf-8")

        self.assertLessEqual(len(encoded), COMPACT_OUTPUT_MAX_BYTES)
        self.assertEqual(
            [
                queue["recovery_disposition"]
                for queue in result["dlq_disposition"]["response_facts"]["queues"]
            ],
            ["hold_for_evidence", "hold_for_evidence"],
        )

    def test_compact_dlq_output_preserves_fifty_queues_under_cap(self) -> None:
        data = _dlq_data()
        marker_queues = []
        queue_groups = []
        for index in range(50):
            queue_name = f"queue-{index:02d}-{'x' * 60}-dlq"
            source_name = queue_name[:-4]
            marker_queues.append(
                {
                    "queueName": queue_name,
                    "visibleMessageCount": 1,
                    "notVisibleMessageCount": 0,
                    "delayedMessageCount": 0,
                    "messageCount": 1,
                    "messageRetentionPeriodSeconds": 345600,
                }
            )
            queue_groups.append(_queue_group(queue_name, source_name, 3))
        marker_payload = {
            "eventType": "DLQ_BACKLOG_DETECTED",
            "region": "ap-northeast-2",
            "observedAt": "2026-07-28T10:40:00Z",
            "messageCount": 50,
            "queues": marker_queues,
        }
        summary = summarize_dlq_backlog_rows(
            [
                {
                    "@timestamp": "2026-07-28T10:40:00Z",
                    "@message": json.dumps(
                        marker_payload,
                        separators=(",", ":"),
                    ),
                }
            ]
        )
        marker = {
            "current": summary,
            "recent_sample": summary,
            "alarm_state_note": "Alarm state does not prove queue state.",
        }
        data["dlq_backlog"] = marker
        data["logs_insights"]["dlq_backlog"] = marker
        data["sqs_context"] = {"days": 7, "queues": queue_groups}
        data["helper_assessment"] = assess_helper_context(data)
        response_queues = data["helper_assessment"]["dlq_disposition"][
            "response_facts"
        ]["queues"]
        for index, queue in enumerate(response_queues):
            queue["marker_depth"] = 2
            queue["recovery_decision"]["disposition"] = (
                "redrive_candidate" if index % 2 else "purge_candidate"
            )

        result = compact_output(data)
        encoded = json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        ).encode("utf-8")
        queues = result["dlq_disposition"]["response_facts"]["queues"]

        self.assertLessEqual(len(encoded), COMPACT_OUTPUT_MAX_BYTES)
        self.assertEqual(len(queues), 50)
        self.assertEqual(
            result["dlq_disposition"]["response_facts"]["queue_fields"],
            [
                "queue_name",
                "depth",
                "marker_depth",
                "recovery_disposition",
                "depth_source",
            ],
        )


if __name__ == "__main__":
    unittest.main()
