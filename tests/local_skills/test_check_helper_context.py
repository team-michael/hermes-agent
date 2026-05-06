import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


CHECK_SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / 'local'
    / 'skills'
    / 'software-development'
    / 'check'
    / 'scripts'
)
sys.path.insert(0, str(CHECK_SCRIPTS))

from notifly_alert_context.detect import (  # noqa: E402
    detect_project_campaign_pairs,
    detect_project_ids,
    detect_sharded_table_refs,
)
from notifly_alert_context.collectors import (  # noqa: E402
    COLLECTOR_REGISTRY,
    CollectorContext,
    CollectorSpec,
    collector_keys,
    run_collectors,
)
from notifly_alert_context.assessment import log_context_has_actionable_detail  # noqa: E402
from notifly_alert_context.aws_collectors import collect_alarm_history  # noqa: E402
from notifly_alert_context.logs import (  # noqa: E402
    centered_log_context_lines,
    current_error_details_from_contexts,
)
from notifly_alert_context.scope import build_scope_attribution, merge_scope_detections  # noqa: E402


PROJECT_FRESHEASY = 'f3d350d0d5bb50ccaf875b6bafd1442c'
PROJECT_QMARKET = 'f2e198e2448959908fe4f8e540f4057f'
UNRELATED_SHARD = 'da4fb76c45d75b96a7792098b581c70d'


def test_log_style_project_campaign_pairs_are_line_bound():
    text = (
        f'Anomaly delivery detected for campaign_id: WHVsPV, project_id: {PROJECT_FRESHEASY}, reason: x\n'
        f'Anomaly delivery detected for campaign_id: Whb9YR, project_id: {PROJECT_QMARKET}, reason: y\n'
        f'error: relation "delivery_result_{UNRELATED_SHARD}" does not exist'
    )

    assert detect_project_campaign_pairs(text) == [
        {'project_id': PROJECT_FRESHEASY, 'campaign_id': 'WHVsPV'},
        {'project_id': PROJECT_QMARKET, 'campaign_id': 'Whb9YR'},
    ]


def test_project_ids_ignore_sharded_table_suffixes():
    text = f'error: relation "delivery_result_{UNRELATED_SHARD}" does not exist'

    assert detect_project_ids(text) == []
    assert detect_sharded_table_refs(text) == [
        {
            'table_family': 'delivery_result',
            'project_id': UNRELATED_SHARD,
            'table_pattern': 'delivery_result_<project_id>',
        }
    ]


def test_current_error_details_preserve_raw_scope_pairs_after_sanitized_context():
    details = current_error_details_from_contexts([
        {
            'timestamp': 1777253498091,
            'log_group': '/aws/lambda/anomaly-delivery-monitoring',
            'log_stream': '2026/04/27/[$LATEST]abc',
            'trigger': (
                f'Anomaly delivery detected for campaign_id: WHVsPV, '
                f'project_id: {PROJECT_FRESHEASY}, reason: duplicate send'
            ),
            'surrounding_lines': [
                (
                    f'Anomaly delivery detected for campaign_id: Whb9YR, '
                    f'project_id: {PROJECT_QMARKET}, reason: duplicate send'
                ),
                f'error: relation "delivery_result_{UNRELATED_SHARD}" does not exist',
            ],
            'project_ids': [PROJECT_FRESHEASY, PROJECT_QMARKET],
            'project_campaign_pairs': [
                {'project_id': PROJECT_FRESHEASY, 'campaign_id': 'WHVsPV'},
                {'project_id': PROJECT_QMARKET, 'campaign_id': 'Whb9YR'},
            ],
            'table_refs': [
                {
                    'table_family': 'delivery_result',
                    'project_id': UNRELATED_SHARD,
                    'table_name': f'delivery_result_{UNRELATED_SHARD}',
                }
            ],
        }
    ])

    assert details
    pairs = [
        (pair['project_id'], pair['campaign_id'])
        for pair in details[0]['project_campaign_pairs']
    ]
    assert pairs == [
        (PROJECT_FRESHEASY, 'WHVsPV'),
        (PROJECT_QMARKET, 'Whb9YR'),
    ]
    assert details[0]['project_ids'] == [PROJECT_FRESHEASY, PROJECT_QMARKET]
    assert details[0]['table_refs'][0]['project_id'] == UNRELATED_SHARD


def test_centered_log_context_reanchors_generic_pg_error_property_line():
    trigger_ms = 1777366975138
    project_id = 'b2b4a8f879a75673b755bff42fc1deb6'
    events = [
        {
            'timestamp': trigger_ms - 40,
            'message': '{"_aws":{"Timestamp":1777366975098},"StatusCode":"200"}',
        },
        {
            'timestamp': trigger_ms - 21,
            'message': f'duplicate key value violates unique constraint "users_{project_id}_pkey"',
        },
        {
            'timestamp': trigger_ms - 20,
            'message': (
                f'Query: INSERT INTO "users_{project_id}" '
                '(notifly_user_id, external_user_id) VALUES ($1,$2)'
            ),
        },
        {'timestamp': trigger_ms - 19, 'message': 'Params: external-user-id,secret'},
        {'timestamp': trigger_ms, 'message': "  severity: 'ERROR',"},
        {'timestamp': trigger_ms + 1, 'message': "  code: '23505',"},
        {
            'timestamp': trigger_ms + 2,
            'message': f"  constraint: 'users_{project_id}_pkey',",
        },
    ]

    centered = centered_log_context_lines(events, trigger_ms, "severity: 'ERROR',", radius=6)

    joined = '\n'.join(centered['lines'])
    assert centered['anchor_shifted'] is True
    assert 'duplicate key value violates unique constraint' in joined
    assert f'Query: INSERT INTO "users_{project_id}"' in joined
    assert "severity: 'ERROR'," in joined
    assert 'Params:' not in joined


def test_current_error_details_uses_error_blocks_when_trigger_is_generic_pg_field():
    project_id = 'b2b4a8f879a75673b755bff42fc1deb6'
    details = current_error_details_from_contexts([
        {
            'timestamp': '2026-04-28T09:02:55.138000+00:00',
            'log_group': '/aws/ecs/notifly-services-prod/api-service',
            'log_stream': 'prod/api-service/example',
            'trigger': "severity: 'ERROR',",
            'surrounding_lines': ["severity: 'ERROR',"],
            'error_blocks': [
                {
                    'anchor': f'duplicate key value violates unique constraint "users_{project_id}_pkey"',
                    'lines': [
                        f'duplicate key value violates unique constraint "users_{project_id}_pkey"',
                        f'Query: INSERT INTO "users_{project_id}" (notifly_user_id, external_user_id)',
                        "code: '23505',",
                        f"constraint: 'users_{project_id}_pkey',",
                        "routine: '_bt_check_unique'",
                    ],
                }
            ],
            'table_refs': [
                {
                    'table_family': 'users',
                    'project_id': project_id,
                    'table_pattern': 'users_<project_id>',
                }
            ],
        }
    ])

    assert details
    assert details[0]['likely_error'].startswith('duplicate key value violates unique constraint')
    assert details[0]['table_refs'][0]['project_id'] == project_id
    assert "severity: 'ERROR'," not in details[0]['error_lines']


def test_log_context_assessment_treats_error_blocks_as_actionable_detail():
    assert log_context_has_actionable_detail([
        {
            'trigger': "severity: 'ERROR',",
            'surrounding_lines': ["severity: 'ERROR',"],
            'error_blocks': [
                {'lines': ['duplicate key value violates unique constraint "users_<project_id>_pkey"']}
            ],
        }
    ])


def test_scope_prefers_current_project_campaign_pairs_over_unrelated_table_refs():
    detected = {
        'service_names': [],
        'queue_names': [],
        'project_campaign_pairs': [
            {'project_id': PROJECT_FRESHEASY, 'campaign_id': 'WHVsPV', 'count': 1},
            {'project_id': PROJECT_QMARKET, 'campaign_id': 'Whb9YR', 'count': 1},
        ],
        'campaign_ids': [],
        'user_journey_ids': [],
        'user_journey_refs': [],
    }
    projects = [
        {'project_id': PROJECT_FRESHEASY, 'name': 'fresheasy', 'product_id': 'notifly', 'mapping_status': 'found'},
        {'project_id': PROJECT_QMARKET, 'name': 'qmarket', 'product_id': 'notifly', 'mapping_status': 'found'},
        {'project_id': UNRELATED_SHARD, 'name': 'unrelated', 'product_id': 'notifly', 'mapping_status': 'found'},
    ]

    scope = build_scope_attribution(
        detected,
        {'Namespace': 'AWS/Logs', 'MetricName': 'ErrorCount', 'Dimensions': []},
        projects,
    )

    assert '/WHVsPV(1건)' in scope['required_final_field']
    assert '/Whb9YR(1건)' in scope['required_final_field']
    assert 'fresheasy' in scope['required_final_field']
    assert 'qmarket' in scope['required_final_field']
    assert 'unrelated' not in scope['required_final_field']


def test_merge_scope_detections_keeps_current_pairs_as_primary_scope():
    logs_insights = {
        'current_project_campaign_pairs': [
            {'project_id': PROJECT_FRESHEASY, 'campaign_id': 'WHVsPV', 'count': 1},
            {'project_id': PROJECT_QMARKET, 'campaign_id': 'Whb9YR', 'count': 1},
        ],
        'current_error_details': [
            {
                'project_ids': [PROJECT_FRESHEASY, PROJECT_QMARKET],
                'error_lines': [f'error: relation "delivery_result_{UNRELATED_SHARD}" does not exist'],
            }
        ],
    }

    merged = merge_scope_detections(
        '',
        logs_insights,
        None,
        [],
        [],
        [],
        [],
    )

    assert merged['project_ids'] == [PROJECT_FRESHEASY, PROJECT_QMARKET]
    assert merged['campaign_ids'] == ['WHVsPV', 'Whb9YR']
    assert [
        (pair['project_id'], pair['campaign_id'], pair['count'], pair['scope_window'])
        for pair in merged['project_campaign_pairs']
    ] == [
        (PROJECT_FRESHEASY, 'WHVsPV', 1, 'current_alarm_window'),
        (PROJECT_QMARKET, 'Whb9YR', 1, 'current_alarm_window'),
    ]


def test_collect_notifly_alert_context_wrapper_keeps_cli_path_stable():
    result = subprocess.run(
        [sys.executable, str(CHECK_SCRIPTS / 'collect_notifly_alert_context.py'), '--help'],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert 'Collect first-pass live alert context' in result.stdout


def test_alarm_history_exposes_fixed_frequency_windows():
    now = datetime.now(timezone.utc)

    class FakeCloudWatch:
        def describe_alarm_history(self, **_kwargs):
            return {
                'AlarmHistoryItems': [
                    {
                        'Timestamp': now - timedelta(minutes=5),
                        'HistoryItemType': 'StateUpdate',
                        'HistorySummary': 'State updated to ALARM',
                        'HistoryData': json.dumps({'newState': {'stateValue': 'ALARM'}}),
                    },
                    {
                        'Timestamp': now - timedelta(minutes=8),
                        'HistoryItemType': 'StateUpdate',
                        'HistorySummary': 'State updated to ALARM',
                        'HistoryData': json.dumps({'newState': {'stateValue': 'ALARM'}}),
                    },
                    {
                        'Timestamp': now - timedelta(hours=2),
                        'HistoryItemType': 'StateUpdate',
                        'HistorySummary': 'State updated to ALARM',
                        'HistoryData': json.dumps({'newState': {'stateValue': 'ALARM'}}),
                    },
                    {
                        'Timestamp': now - timedelta(days=3),
                        'HistoryItemType': 'StateUpdate',
                        'HistorySummary': 'State updated to ALARM',
                        'HistoryData': json.dumps({'newState': {'stateValue': 'ALARM'}}),
                    },
                    {
                        'Timestamp': now - timedelta(days=10),
                        'HistoryItemType': 'StateUpdate',
                        'HistorySummary': 'State updated to ALARM',
                        'HistoryData': json.dumps({'newState': {'stateValue': 'ALARM'}}),
                    },
                ],
            }

    class FakeSession:
        def client(self, name):
            assert name == 'cloudwatch'
            return FakeCloudWatch()

    history = collect_alarm_history(FakeSession(), 'example-alarm', 30)

    assert history['alarm_count_10m'] == 2
    assert history['alarm_count_1d'] == 3
    assert history['alarm_count_7d'] == 4
    assert history['alarm_count_lookback'] == 5
    assert history['rapid_recurrence']['status'] == 'rapid'


def test_collector_registry_has_unique_ordered_keys():
    keys = collector_keys()

    assert len(keys) == len(set(keys))
    assert keys.index('metric_filters') < keys.index('logs_insights')
    assert keys.index('rds_context') < keys.index('rds_performance_insights')
    assert keys.index('rds_performance_insights') < keys.index('campaign_scope_hints')
    assert set(keys) >= {
        'metric_datapoints',
        'logs_insights',
        'http_context',
        'sqs_context',
        'lambda_context',
        'rds_performance_insights',
    }
    assert all(isinstance(spec, CollectorSpec) for spec in COLLECTOR_REGISTRY)


def test_run_collectors_allows_later_collectors_to_use_prior_results():
    ctx = CollectorContext(
        session=None,
        text='',
        alarm=None,
        log_groups=[],
        keywords=[],
        queue_names=[],
        lambda_names=[],
        history=None,
    )
    specs = [
        CollectorSpec('first', lambda c: {'value': 3}),
        CollectorSpec('second', lambda c: c.results['first']['value'] + 4),
    ]

    assert run_collectors(ctx, specs) == {
        'first': {'value': 3},
        'second': 7,
    }
