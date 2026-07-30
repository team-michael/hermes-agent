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
)
from notifly_alert_context.logs import parse_sentry_error_fact  # noqa: E402
from notifly_alert_context.repo import trace_sentry_code_locations  # noqa: E402


def _sentry_message(*, with_stack: bool = False) -> str:
    alert = {
        "provider": "sentry",
        "parseable": True,
        "status": "New Alert",
        "organizationSlug": "greybox",
        "level": "error",
        "issue": {
            "id": "7639819969",
            "title": "TypeError",
            "transaction": "/console/products/[productId]/user-journey/[userJourneyId]/edit",
            "message": "Cannot read properties of undefined (reading 'map')",
            "url": "https://greybox.sentry.io/issues/7639819969/?secret=query",
        },
        "request": {
            "url": "https://console.notifly.tech/console/products/tripstore/user-journey/nmhvrw/edit",
            "query": "environment=1",
        },
        "tags": {
            "handled": "yes",
            "environment": "production",
        },
    }
    if with_stack:
        alert["exception"] = {
            "values": [
                {
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "node_modules/react/index.js",
                                "function": "renderWithHooks",
                                "lineno": 10,
                                "in_app": False,
                            },
                            {
                                "filename": "services/server/web-console/src/domains/user-journey/components/UserJourneyCreate/UserJourneyCreatePage.tsx",
                                "function": "UserJourneyCreatePage",
                                "lineno": 261,
                                "colno": 34,
                                "in_app": True,
                            },
                        ]
                    }
                }
            ]
        }
    return json.dumps(
        {
            "message": "Received Sentry email alert via SES",
            "routeName": "sentry",
            "sentryAlert": alert,
        }
    )


def test_parse_sentry_fact_keeps_page_scope_without_raw_urls() -> None:
    fact = parse_sentry_error_fact(
        _sentry_message(),
        timestamp="2026-07-29T11:17:55.585000+00:00",
        log_group="/aws/ecs/notifly-services-prod/web-console/sentry",
        log_stream="sentry/2026/07/29/example",
    )

    assert fact == {
        "source": "sentry",
        "issue_id": "7639819969",
        "title": "TypeError",
        "message": "Cannot read properties of undefined (reading 'map')",
        "transaction": "/console/products/[productId]/user-journey/[userJourneyId]/edit",
        "request_path": "/console/products/tripstore/user-journey/nmhvrw/edit",
        "product_id": "tripstore",
        "user_journey_id": "nmhvrw",
        "handled": True,
        "environment": "production",
        "status": "New Alert",
        "level": "error",
        "timestamp": "2026-07-29T11:17:55.585000+00:00",
        "log_group": "/aws/ecs/notifly-services-prod/web-console/sentry",
        "log_stream": "sentry/2026/07/29/example",
        "stack_location": None,
    }
    encoded = json.dumps(fact)
    assert "secret=query" not in encoded
    assert "environment=1" not in encoded


def test_parse_sentry_fact_prefers_complete_tag_url_over_truncated_request_url() -> None:
    payload = json.loads(_sentry_message())
    payload["sentryAlert"]["request"]["url"] = (
        "https://console.notifly.tech/console/products/tripstore/user-journey/nmhvr…"
    )
    payload["sentryAlert"]["tags"]["url"] = (
        "https://console.notifly.tech/console/products/tripstore/user-journey/nmhvrw/edit"
    )

    fact = parse_sentry_error_fact(json.dumps(payload))

    assert fact["request_path"] == "/console/products/tripstore/user-journey/nmhvrw/edit"
    assert fact["user_journey_id"] == "nmhvrw"


def test_parse_sentry_fact_prefers_last_in_app_stack_frame() -> None:
    fact = parse_sentry_error_fact(_sentry_message(with_stack=True))

    assert fact["stack_location"] == {
        "file": "services/server/web-console/src/domains/user-journey/components/UserJourneyCreate/UserJourneyCreatePage.tsx",
        "function": "UserJourneyCreatePage",
        "line": 261,
        "column": 34,
        "in_app": True,
        "evidence": "sentry_stack_frame",
    }


def test_trace_sentry_code_location_resolves_next_page_and_rendered_function(tmp_path: Path) -> None:
    page = tmp_path / "services/server/web-console/src/pages/console/products/[productId]/user-journey/[userJourneyId]/edit.tsx"
    component = tmp_path / "services/server/web-console/src/domains/user-journey/components/UserJourneyCreatePage.tsx"
    page.parent.mkdir(parents=True)
    component.parent.mkdir(parents=True)
    page.write_text(
        """import { UserJourneyCreatePage } from '@/domains/user-journey/components/UserJourneyCreatePage';
export default function Page() {
  return <UserJourneyCreatePage />;
}
"""
    )
    component.write_text("export function UserJourneyCreatePage() { return null; }\n")
    fact = parse_sentry_error_fact(_sentry_message())

    locations = trace_sentry_code_locations(tmp_path, [fact])

    assert locations == [
        {
            "issue_id": "7639819969",
            "transaction": "/console/products/[productId]/user-journey/[userJourneyId]/edit",
            "page": {
                "file": str(page.relative_to(tmp_path)),
                "function": "Page",
                "line": 2,
                "evidence": "next_route_match",
            },
            "error_location": None,
            "function_candidates": [
                {
                    "file": str(component.relative_to(tmp_path)),
                    "function": "UserJourneyCreatePage",
                    "line": 1,
                    "evidence": "rendered_component",
                }
            ],
            "trace_status": "route_and_component_only_stack_unavailable",
        }
    ]


def test_trace_sentry_code_location_resolves_next_api_handler(tmp_path: Path) -> None:
    handler = tmp_path / "services/server/web-console/src/pages/api/projects/[projectId]/campaigns.ts"
    handler.parent.mkdir(parents=True)
    handler.write_text(
        """export default async function handler(req, res) {
  return res.status(200).json({});
}
"""
    )
    fact = parse_sentry_error_fact(_sentry_message())
    fact["transaction"] = "PUT /api/projects/[projectId]/campaigns"

    locations = trace_sentry_code_locations(tmp_path, [fact])

    assert locations[0]["page"] == {
        "file": str(handler.relative_to(tmp_path)),
        "function": "handler",
        "line": 1,
        "evidence": "next_route_match",
    }
    assert locations[0]["trace_status"] == "route_and_component_only_stack_unavailable"


def test_compact_output_preserves_sentry_page_and_function_evidence_under_budget() -> None:
    fact = parse_sentry_error_fact(_sentry_message(with_stack=True))
    location = {
        "issue_id": fact["issue_id"],
        "transaction": fact["transaction"],
        "page": {
            "file": "services/server/web-console/src/pages/console/products/[productId]/user-journey/[userJourneyId]/edit.tsx",
            "function": "Page",
            "line": 14,
            "evidence": "next_route_match",
        },
        "error_location": fact["stack_location"],
        "function_candidates": [],
        "trace_status": "exact_stack_frame",
    }
    data = {
        "detected": {
            "alarm_name": "/aws/ecs/notifly-services-prod/web-console/sentry alert",
            "keywords": ["ERROR"],
            "service_names": [],
            "lambda_names": [],
            "project_ids": [],
        },
        "alarm_summary": {
            "AlarmName": "/aws/ecs/notifly-services-prod/web-console/sentry alert",
            "Namespace": "ConsoleErrors",
            "MetricName": "/aws/ecs/notifly-services-prod/web-console/sentry alert",
        },
        "alarm_history": {
            "latest_alarm_transition": {"timestamp": "2026-07-29T11:17:00Z"},
        },
        "metric_datapoints": {"datapoint_count": 1},
        "logs_insights": {
            "log_groups": ["/aws/ecs/notifly-services-prod/web-console/sentry"],
            "current_alarm_window": {
                "start": "2026-07-29T11:16:00Z",
                "end": "2026-07-29T11:19:00Z",
            },
            "current_error_details": [{"likely_error": "x" * 20_000}],
            "current_trigger_contexts": [{"trigger": "x" * 20_000}],
        },
        "current_error_facts": [fact],
        "current_code_locations": [location],
        "scope_attribution": {"service_indicators": ["sentry"]},
        "repo_code_hits": [{"line": "x" * 20_000}],
    }
    data["helper_assessment"] = assess_helper_context(data)

    result = compact_output(data)

    assert len(json.dumps(result, ensure_ascii=False, indent=2).encode()) <= COMPACT_OUTPUT_MAX_BYTES
    assert result["current_error_facts"][0]["message"] == "Cannot read properties of undefined (reading 'map')"
    assert result["current_code_locations"][0]["page"]["function"] == "Page"
    assert result["current_code_locations"][0]["error_location"]["function"] == "UserJourneyCreatePage"
    assert result["can_answer_root_cause"] is True
