from .common import *
from .text import normalize_ws, truncate

def print_section(title: str, obj: Any) -> None:
    print(f'# {title}')
    if obj is None:
        print('(none)')
    else:
        print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    print()

def object_has_error(obj: Any) -> bool:
    if isinstance(obj, dict):
        if obj.get('error'):
            return True
        return any(object_has_error(value) for value in obj.values())
    if isinstance(obj, list):
        return any(object_has_error(value) for value in obj)
    return False

def rds_pi_has_top_sql(pi_data: Any) -> bool:
    if not isinstance(pi_data, dict):
        return False
    for inst in pi_data.get('instances') or []:
        if isinstance(inst, dict) and inst.get('top_sql'):
            return True
    return False

def log_context_has_actionable_detail(contexts: Sequence[Dict[str, Any]]) -> bool:
    actionable = re.compile(
        r'(?i)\b(detail|code|routine|constraint|where|sqlstate|deadlock|duplicate|timeout|'
        r'etimedout|crossslot|exception|error from|typeerror|referenceerror|validationerror|'
        r'failed|denied)\b|/app/|\.js:\d+|\.ts:\d+'
    )
    low_signal = {
        "severity: 'ERROR',",
        'ERROR',
        'Error',
    }
    for ctx in contexts or []:
        block_lines = [
            line
            for block in ctx.get('error_blocks') or []
            if isinstance(block, dict)
            for line in block.get('lines') or []
        ]
        for line in [*block_lines, *(ctx.get('surrounding_lines') or [])]:
            text = normalize_ws(str(line))
            if not text or text in low_signal:
                continue
            if actionable.search(text):
                return True
    return False

def append_missing(missing: List[Dict[str, Any]], key: str, reason: str, severity: str = 'required') -> None:
    if any(item.get('key') == key for item in missing):
        return
    missing.append({'key': key, 'severity': severity, 'reason': reason})

def append_followup(
    followups: List[Dict[str, Any]],
    followup_id: str,
    data_source: str,
    action: str,
    fills: Sequence[str],
    reason: str,
) -> None:
    if any(item.get('id') == followup_id for item in followups):
        return
    followups.append({
        'id': followup_id,
        'data_source': data_source,
        'action': action,
        'fills': list(fills),
        'reason': reason,
    })

def assess_helper_context(data: Dict[str, Any]) -> Dict[str, Any]:
    detected = data.get('detected') or {}
    alarm = data.get('alarm_summary') or {}
    history = data.get('alarm_history') or {}
    metric = data.get('metric_datapoints') or {}
    logs = data.get('logs_insights') or {}
    rds = data.get('rds_context')
    pi_data = data.get('rds_performance_insights')
    http = data.get('http_context')
    sqs = data.get('sqs_context')
    lambda_context = data.get('lambda_context')
    scope = data.get('scope_attribution') or {}
    campaign_hints = data.get('campaign_scope_hints') or {}
    code_hits = data.get('repo_code_hits') or []

    missing: List[Dict[str, Any]] = []
    followups: List[Dict[str, Any]] = []
    root_cause_evidence: List[str] = []

    alarm_name = detected.get('alarm_name') or alarm.get('AlarmName')
    namespace = str((alarm or {}).get('Namespace') or '')
    metric_name = str((alarm or {}).get('MetricName') or '')
    dimensions = (alarm or {}).get('Dimensions') or []
    dim_names = {str(d.get('Name') or '').lower() for d in dimensions if isinstance(d, dict)}
    alarm_text = ' '.join([
        str(alarm_name or ''),
        namespace,
        metric_name,
        ' '.join(detected.get('keywords') or []),
        ' '.join(detected.get('service_names') or []),
        ' '.join(detected.get('queue_names') or []),
        ' '.join(detected.get('lambda_names') or []),
    ]).lower()

    if not alarm_name:
        append_missing(missing, 'alarm_name', 'CloudWatch alarm name was not parsed from the alert text.')
        append_followup(
            followups,
            'recover_alarm_name_from_slack_text',
            'Slack alert text',
            'Re-read the alert root text and pass --alarm-name explicitly if needed.',
            ['detected.alarm_name'],
            'CloudWatch APIs need the exact alarm name.',
        )
    if not isinstance(alarm, dict) or alarm.get('error') or not alarm.get('AlarmName'):
        append_missing(missing, 'alarm_metadata', 'CloudWatch describe_alarms did not return usable alarm metadata.')
        append_followup(
            followups,
            'describe_cloudwatch_alarm',
            'AWS CloudWatch',
            'Call describe_alarms for the exact alarm name and region.',
            ['alarm'],
            'Threshold, namespace, dimensions, and state are mandatory for final context.',
        )
    if not isinstance(history, dict) or history.get('error'):
        append_missing(missing, 'alarm_history', 'CloudWatch alarm history is unavailable or errored.')
        append_followup(
            followups,
            'describe_alarm_history',
            'AWS CloudWatch',
            'Call describe_alarm_history for the alarm over the configured lookback window.',
            ['history', 'history.latest_alarm_transition'],
            'The current investigation must be anchored to the latest ALARM transition.',
        )
    elif not history.get('latest_alarm_transition'):
        append_missing(missing, 'latest_alarm_transition', 'No latest ALARM transition was found in alarm history.')
        append_followup(
            followups,
            'extend_alarm_history_window',
            'AWS CloudWatch',
            'Increase --lookback-days or inspect alarm history around the Slack message timestamp.',
            ['history.latest_alarm_transition'],
            'Current root cause must be based on the latest ALARM transition window.',
        )
    if isinstance(alarm, dict) and alarm.get('MetricName') and (not isinstance(metric, dict) or metric.get('error')):
        append_missing(missing, 'metric_datapoints', 'CloudWatch datapoints for the alarm metric are unavailable.')
        append_followup(
            followups,
            'fetch_alarm_metric_datapoints',
            'AWS CloudWatch',
            'Fetch the alarm metric datapoints around the latest ALARM transition.',
            ['metric'],
            'Final answer needs the breached metric/threshold context.',
        )

    log_shaped = bool(logs or detected.get('log_groups') or data.get('metric_filters') or 'aws/logs' in namespace.lower())
    rds_shaped = bool(
        'aws/rds' in namespace.lower()
        or rds
        or pi_data
        or {'dbclusteridentifier', 'dbinstanceidentifier'} & dim_names
        or metric_name.lower() in {'cpuutilization', 'freeablememory', 'databaseload', 'readiops', 'writeiops', 'volumereadiops', 'volumewriteiops'}
    )
    http_shaped = bool(
        namespace in {'AWS/ApplicationELB', 'AWS/ApiGateway', 'AWS/CloudFront'}
        or {'statuscode', 'status_code', 'status', 'httpstatus', 'http_status', 'path', 'route', 'resource', 'normalizedpath', 'method'} & dim_names
        or re.search(r'(?i)(4xx|5xx|httpcode|http)', metric_name)
    )
    sqs_shaped = bool(detected.get('queue_names') or 'aws/sqs' in namespace.lower() or 'queuename' in dim_names)
    lambda_shaped = bool(detected.get('lambda_names') or 'aws/lambda' in namespace.lower() or 'functionname' in dim_names)

    if log_shaped:
        if not isinstance(logs, dict) or logs.get('skipped') or logs.get('errors'):
            append_missing(missing, 'logs_insights_summary', 'Logs Insights summary is missing, skipped, or errored.')
            append_followup(
                followups,
                'run_fixed_logs_insights_summary',
                'AWS CloudWatch Logs Insights',
                'Run the helper fixed Logs Insights count/sample queries using primary metric filter terms.',
                ['logs.count_7d', 'logs.count_30d', 'logs.top_signatures'],
                'Log-derived alerts need exact triggering log evidence, not alarm-name guesses.',
            )
        if not logs.get('current_alarm_window'):
            append_missing(missing, 'current_alarm_window', 'No current ALARM transition window was computed for log investigation.')
            append_followup(
                followups,
                'compute_current_alarm_window',
                'AWS CloudWatch alarm history',
                'Anchor the log query window to history.latest_alarm_transition and alarm Period/EvaluationPeriods.',
                ['logs.current_alarm_window'],
                'Root cause must be based on the error that triggered the latest ALARM transition.',
            )
        current_contexts = logs.get('current_trigger_contexts') or []
        current_error_details = logs.get('current_error_details') or []
        if not current_contexts:
            append_missing(missing, 'current_trigger_contexts', 'No CloudWatch log context was found in the current alarm window.')
            append_followup(
                followups,
                'query_current_alarm_log_contexts',
                'AWS CloudWatch Logs Insights',
                'Query the latest ALARM window with the primary metric filter, then fetch trigger-centered stream context.',
                ['logs.current_top_signatures', 'logs.current_trigger_contexts'],
                'The final root cause should cite the current triggering log body.',
            )
        elif current_error_details:
            root_cause_evidence.append('current_alarm_error_detail')
        elif not log_context_has_actionable_detail(current_contexts):
            append_missing(missing, 'current_error_detail', 'Current log context exists but lacks actionable error detail beyond generic severity/signature lines.')
            append_followup(
                followups,
                'expand_current_log_context',
                'AWS CloudWatch Logs Insights',
                'Expand the same log stream/time window and group sanitized lines around the trigger until error detail or code path appears.',
                ['logs.current_trigger_contexts', 'logs.current_error_details'],
                'Generic signatures such as severity=ERROR are insufficient for root cause.',
            )
        else:
            root_cause_evidence.append('current_alarm_log_context')

    if rds_shaped:
        if not isinstance(rds, dict) or rds.get('error') or not (rds.get('instance') or rds.get('instances')):
            append_missing(missing, 'rds_topology', 'RDS topology/instance role context is unavailable.')
            append_followup(
                followups,
                'describe_rds_topology',
                'AWS RDS',
                'Describe the DB cluster/instance from alarm dimensions and identify writer/reader roles.',
                ['rds'],
                'DB-shaped final answers must name the concrete instance/role.',
            )
        if not rds_pi_has_top_sql(pi_data):
            append_missing(missing, 'rds_pi_top_sql', 'Performance Insights top SQL is unavailable or empty.')
            append_followup(
                followups,
                'query_rds_performance_insights',
                'AWS Performance Insights',
                'Query db.load.avg grouped by db.sql around the latest ALARM transition.',
                ['rds_performance_insights.instances[].top_sql'],
                'DB-shaped final answers must name the SQL family/query fingerprint.',
            )
        else:
            root_cause_evidence.append('rds_performance_insights_top_sql')

    if http_shaped and (not isinstance(http, dict) or http.get('status') == 'not_applicable' or http.get('error')):
        append_missing(missing, 'http_peer_metrics', 'HTTP 4xx/5xx/request-count peer metrics are unavailable.')
        append_followup(
            followups,
            'fetch_http_peer_metrics',
            'AWS CloudWatch',
            'Fetch peer 4xx/5xx/request-count metrics for the alarm route/service dimensions.',
            ['http', 'five_xx'],
            'HTTP alerts need route/status context to distinguish client spikes from server regressions.',
        )

    if sqs_shaped and (not isinstance(sqs, dict) or sqs.get('error')):
        append_missing(missing, 'sqs_queue_context', 'SQS queue attributes/metrics are unavailable.')
        append_followup(
            followups,
            'describe_sqs_queue_context',
            'AWS SQS/CloudWatch',
            'Fetch queue attributes, redrive source hints, and safe queue metrics without receiving messages.',
            ['sqs'],
            'SQS/DLQ alerts need queue state and redrive context.',
        )
    elif sqs_shaped:
        root_cause_evidence.append('sqs_queue_metrics')

    if lambda_shaped and (not isinstance(lambda_context, dict) or lambda_context.get('error')):
        append_missing(missing, 'lambda_context', 'Lambda configuration/event-source/metric context is unavailable.')
        append_followup(
            followups,
            'describe_lambda_context',
            'AWS Lambda/CloudWatch',
            'Fetch Lambda configuration, event source mappings, async config, and error/throttle/duration metrics.',
            ['lambda'],
            'Lambda alerts need function/runtime/source context.',
        )
    elif lambda_shaped and isinstance(lambda_context, dict):
        root_cause_evidence.append('lambda_runtime_metrics')

    project_ids = detected.get('project_ids') or []
    projects = data.get('project_mappings') or []
    if project_ids and (not projects or object_has_error(projects)):
        append_missing(missing, 'project_mapping', 'One or more project_id values were found but DynamoDB project mapping is unavailable.')
        append_followup(
            followups,
            'map_project_ids',
            'DynamoDB project table',
            'Get id, product_id, and name for detected project_id values using projection expression.',
            ['projects', 'scope_attribution.projects'],
            'Final scope should report product/project names, not only raw IDs.',
        )

    scope_has_specific_project = bool(scope.get('project_count'))
    scope_is_common = bool(scope.get('service_indicators') or scope.get('infra_indicators'))
    if not scope_has_specific_project and not scope_is_common and not project_ids:
        append_missing(missing, 'scope_basis', 'No specific project scope or service/infra-wide basis was established.')
        append_followup(
            followups,
            'establish_scope_basis',
            'CloudWatch logs / PI / source context',
            'Look for project_id, sharded table suffixes, route/service dimensions, or explicit infra-wide dimensions.',
            ['scope_attribution'],
            'Final answer must include a defensible 범위 field.',
        )

    campaign_suggestions = campaign_hints.get('read_only_aggregate_suggestions') or []
    has_campaign_or_journey_scope = bool(
        detected.get('project_campaign_pairs')
        or detected.get('campaign_ids')
        or detected.get('user_journey_ids')
        or detected.get('user_journey_refs')
    )
    if campaign_suggestions and not has_campaign_or_journey_scope:
        append_missing(missing, 'campaign_or_user_journey_attribution', 'Campaign/user_journey-capable DB tables were detected but no top campaign or user_journey contributor was resolved.')
        append_followup(
            followups,
            'run_campaign_or_user_journey_aggregate',
            'Postgres or Athena',
            'Run the suggested read-only aggregate around logs.current_alarm_window or PI window.',
            ['scope_attribution.campaign_ids', 'scope_attribution.user_journey_ids'],
            'Final scope should name exactly one of campaign or user_journey when the table family can support it.',
        )

    if not code_hits and any(token in alarm_text for token in ['error', 'exception', 'timeout', 'slow', 'deadlock', 'duplicate']):
        append_missing(missing, 'implementation_context', 'No local implementation/Terraform context was found for the dominant signal.')
        append_followup(
            followups,
            'search_implementation_context',
            'local notifly-event repository',
            'Search exact error strings, code paths, metric filter names, and Terraform alarm/filter resources with narrow context.',
            ['code'],
            'Action recommendations should name a concrete code or Terraform target when possible.',
        )

    blocking_keys = {
        'alarm_metadata',
        'alarm_history',
        'latest_alarm_transition',
        'logs_insights_summary',
        'current_alarm_window',
        'current_trigger_contexts',
        'current_error_detail',
        'rds_topology',
        'rds_pi_top_sql',
    }
    blocking_missing = [item for item in missing if item.get('key') in blocking_keys]
    if root_cause_evidence:
        can_answer = not any(item.get('key') in {'alarm_metadata', 'alarm_history', 'latest_alarm_transition'} for item in missing)
    else:
        can_answer = not blocking_missing and not (log_shaped or rds_shaped)

    return {
        'can_answer_root_cause': bool(can_answer),
        'root_cause_evidence': root_cause_evidence,
        'missing_required_context': missing,
        'required_followups': followups,
        'note': 'If can_answer_root_cause is false, perform required_followups before finalizing when read-only and safe.',
    }

def compact_output(data: Dict[str, Any]) -> Dict[str, Any]:
    alarm = data.get('alarm_summary') or {}
    history = data.get('alarm_history') or {}
    metric = data.get('metric_datapoints') or {}
    logs_summary = data.get('logs_insights') or {}
    assessment = data.get('helper_assessment') or assess_helper_context(data)
    return {
        'can_answer_root_cause': assessment.get('can_answer_root_cause'),
        'missing_required_context': assessment.get('missing_required_context') or [],
        'required_followups': assessment.get('required_followups') or [],
        'detected': data.get('detected'),
        'aws': data.get('aws_caller_identity'),
        'alarm': {
            'name': alarm.get('AlarmName'),
            'state': alarm.get('StateValue'),
            'reason': truncate(str(alarm.get('StateReason') or ''), 260),
            'metric': {
                'namespace': alarm.get('Namespace'),
                'name': alarm.get('MetricName'),
                'statistic': alarm.get('Statistic'),
                'period': alarm.get('Period'),
                'threshold': alarm.get('Threshold'),
                'comparison': alarm.get('ComparisonOperator'),
                'dimensions': alarm.get('Dimensions'),
            },
        },
        'history': {
            'lookback_days': history.get('lookback_days'),
            'alarm_count_7d': history.get('alarm_count_7d'),
            'alarm_count_1d': history.get('alarm_count_1d'),
            'alarm_count_10m': history.get('alarm_count_10m'),
            'alarm_count_30d': history.get('alarm_count_lookback'),
            'state_transitions_1d': history.get('state_transitions_1d'),
            'state_transitions_7d': history.get('state_transitions_7d'),
            'state_transitions_30d': history.get('state_transitions_lookback'),
            'daily_alarm_counts': history.get('alarm_daily_counts'),
            'latest_alarm_transition': history.get('latest_alarm_transition'),
            'rapid_recurrence': history.get('rapid_recurrence'),
            'recent_items': (history.get('sample_items') or [])[:5],
        },
        'metric': {
            'days': metric.get('days'),
            'statistic': metric.get('statistic'),
            'period': metric.get('period'),
            'datapoint_count': metric.get('datapoint_count'),
            'threshold': metric.get('threshold'),
            'min': metric.get('min'),
            'max': metric.get('max'),
            'avg': metric.get('avg'),
            'latest': metric.get('latest'),
            'recent_points': (metric.get('recent_points') or [])[-6:],
        },
        'metric_filters': data.get('metric_filters'),
        'logs': logs_summary,
        'http': data.get('http_context'),
        'five_xx': data.get('five_xx_metrics'),
        'sqs': data.get('sqs_context'),
        'lambda': data.get('lambda_context'),
        'rds': data.get('rds_context'),
        'rds_performance_insights': data.get('rds_performance_insights'),
        'campaign_scope_hints': data.get('campaign_scope_hints'),
        'scope_attribution': data.get('scope_attribution'),
        'projects': data.get('project_mappings'),
        'code': data.get('repo_code_hits'),
        'root_cause_evidence': assessment.get('root_cause_evidence') or [],
        'helper_notes': [
            assessment.get('note'),
            'Logs Insights used fixed query templates only.',
            'Raw log dumps are suppressed; samples are sanitized and grouped by signature.',
            'If additional manual tool calls were needed, fold that reusable step back into this skill/helper.',
        ],
    }
