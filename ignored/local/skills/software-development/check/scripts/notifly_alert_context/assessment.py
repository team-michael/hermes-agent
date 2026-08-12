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

def lambda_context_has_signal(lambda_context: Any) -> bool:
    if not isinstance(lambda_context, dict):
        return False
    for fn in lambda_context.get('functions') or []:
        if not isinstance(fn, dict):
            continue
        if fn.get('configuration') and not fn.get('configuration_error'):
            return True
        for metric in fn.get('metrics') or []:
            summary = metric.get('summary') if isinstance(metric, dict) else None
            if isinstance(summary, dict) and (summary.get('datapoint_count') or 0) > 0:
                return True
    return False


def lambda_signatures_have_current_error(signatures: Any) -> bool:
    if not isinstance(signatures, dict):
        return False
    error_pattern = re.compile(
        r'(?i)\b(error|exception|timeout|timed out|failed|failure)\b|'
        r'status\s*:\s*(?:timeout|error)'
    )
    for item in signatures.get('signatures') or []:
        if not isinstance(item, dict):
            continue
        text = ' '.join([
            str(item.get('signature') or ''),
            *[str(line) for line in item.get('sample_lines') or []],
        ])
        if error_pattern.search(text):
            return True
    return False


def history_has_quick_recovery(
    history: Any,
    *,
    max_seconds: int = 15 * 60,
) -> bool:
    if not isinstance(history, dict):
        return False
    alarm_timestamp = (
        (history.get('latest_alarm_transition') or {}).get('timestamp')
    )
    try:
        alarm_time = datetime.fromisoformat(
            str(alarm_timestamp).replace('Z', '+00:00')
        )
        if alarm_time.tzinfo is None:
            alarm_time = alarm_time.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return False

    for item in history.get('sample_items') or []:
        if not isinstance(item, dict) or item.get('new_state') != 'OK':
            continue
        try:
            recovered_at = datetime.fromisoformat(
                str(item.get('timestamp')).replace('Z', '+00:00')
            )
            if recovered_at.tzinfo is None:
                recovered_at = recovered_at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        elapsed = (recovered_at - alarm_time).total_seconds()
        if 0 <= elapsed <= max_seconds:
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


def _safe_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_kst(value: Any) -> Optional[str]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(
            timezone(timedelta(hours=9))
        ).strftime('%Y-%m-%d %H:%M:%S KST')
    except (TypeError, ValueError):
        return None


def _sqs_rows_by_name(sqs_context: Any) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    if not isinstance(sqs_context, dict):
        return rows
    for group in sqs_context.get('queues') or []:
        if not isinstance(group, dict):
            continue
        for row in group.get('related_queues') or []:
            if not isinstance(row, dict) or not row.get('queue_name'):
                continue
            rows[str(row['queue_name'])] = row
    return rows


def _lambda_health_evidence(lambda_context: Any) -> List[Dict[str, Any]]:
    evidence = []
    if not isinstance(lambda_context, dict):
        return evidence
    for function in lambda_context.get('functions') or []:
        if not isinstance(function, dict):
            continue
        metrics = {}
        for metric in function.get('metrics') or []:
            if not isinstance(metric, dict) or not metric.get('metric_name'):
                continue
            summary = metric.get('summary') or {}
            metrics[str(metric['metric_name'])] = {
                'statistic': metric.get('statistic'),
                'latest': summary.get('latest'),
                'max': summary.get('max'),
            }
        evidence.append({
            'function_name': function.get('function_name')
            or (function.get('configuration') or {}).get('function_name'),
            'metrics': metrics,
            'interpretation': (
                'Inspection Lambda health only; not message-outcome evidence.'
            ),
        })
    return evidence


def decide_queue_recovery(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Classify a queue recovery candidate without authorizing a mutation."""
    failure_class = str(evidence.get('failure_class') or 'unknown')
    replay_safety = str(evidence.get('replay_safety') or 'unknown')
    obsolescence = str(evidence.get('obsolescence') or 'unknown')
    redrive_supported = evidence.get('technical_redrive_supported') is True
    evidence_preserved = evidence.get('evidence_preserved') is True

    missing_evidence = []
    if failure_class == 'unknown':
        missing_evidence.append('failure_class')
    if replay_safety == 'unknown':
        missing_evidence.append('replay_safety')
    if obsolescence == 'unknown':
        missing_evidence.append('obsolescence')
    if not evidence_preserved:
        missing_evidence.append('evidence_preservation')

    redrive_candidate = all([
        redrive_supported,
        failure_class == 'transient',
        replay_safety == 'idempotent',
        obsolescence == 'not_obsolete',
        evidence_preserved,
    ])
    purge_candidate = all([
        failure_class in {'terminal', 'permanent'},
        obsolescence == 'confirmed_obsolete',
        evidence_preserved,
    ])

    if purge_candidate:
        disposition = 'purge_candidate'
    elif redrive_candidate:
        disposition = 'redrive_candidate'
    else:
        disposition = 'hold_for_evidence'

    if disposition != 'hold_for_evidence':
        missing_evidence = []

    return {
        'disposition': disposition,
        'missing_evidence': missing_evidence,
        'action_candidates': {
            'hold_for_evidence': {
                'recommended': disposition == 'hold_for_evidence',
            },
            'redrive': {
                'recommended': redrive_candidate,
                'requirements': [
                    'technical_redrive_supported',
                    'transient_failure',
                    'idempotent_replay',
                    'not_obsolete',
                    'evidence_preserved',
                ],
            },
            'purge': {
                'recommended': purge_candidate,
                'requirements': [
                    'terminal_or_permanent_failure',
                    'confirmed_obsolete',
                    'evidence_preserved',
                ],
            },
        },
        'mutation_allowed': False,
    }


def _redrive_capability(
    dlq_name: str,
    dlq_row: Dict[str, Any],
    source_names: Sequence[str],
    sqs_rows: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    dlq_attrs = dlq_row.get('attributes') or {}
    raw_allow_policy = dlq_attrs.get('RedriveAllowPolicy')
    if raw_allow_policy is None:
        allow_policy: Dict[str, Any] = {}
        permission = 'allowAll'
    elif isinstance(raw_allow_policy, dict):
        allow_policy = raw_allow_policy
        permission = allow_policy.get('redrivePermission') or 'unknown'
    else:
        allow_policy = {}
        permission = 'unknown'
    allowed_sources = {
        str(arn).rsplit(':', 1)[-1]
        for arn in allow_policy.get('sourceQueueArns') or []
        if arn
    }
    sources = []
    for source_name in source_names:
        source_attrs = (sqs_rows.get(source_name) or {}).get('attributes') or {}
        policy = source_attrs.get('RedrivePolicy') or {}
        if not isinstance(policy, dict):
            policy = {}
        target_name = str(policy.get('deadLetterTargetArn') or '').rsplit(':', 1)[-1]
        target_matches = target_name == dlq_name
        source_allowed = (
            permission == 'allowAll'
            or (permission == 'byQueue' and source_name in allowed_sources)
        )
        sources.append({
            'queue_name': source_name,
            'target_matches': target_matches,
            'allowed_by_dlq': source_allowed,
            'max_receive_count': _safe_int(policy.get('maxReceiveCount')),
        })

    supported_sources = [
        source
        for source in sources
        if source['target_matches'] and source['allowed_by_dlq']
    ]
    return {
        'supported': bool(supported_sources),
        'permission': permission,
        'max_receive_count': (
            supported_sources[0].get('max_receive_count')
            if len(supported_sources) == 1
            else None
        ),
        'sources': sources,
        'interpretation': (
            'Technical redrive capability only; not replay-safety evidence.'
        ),
    }


def _consumer_contract(consumers: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    response_types = unique([
        str(response_type)
        for consumer in consumers
        for response_type in consumer.get('function_response_types') or []
        if response_type
    ])
    return {
        'partial_batch_failure_reporting': (
            'ReportBatchItemFailures' in response_types
            if consumers
            else None
        ),
        'function_response_types': response_types,
        'interpretation': (
            'Event-source response contract only; not consumer runtime health '
            'or replay-safety evidence.'
        ),
    }


def _live_queue_depth(queue_row: Dict[str, Any]) -> Optional[int]:
    attrs = queue_row.get('attributes') or {}
    keys = (
        'ApproximateNumberOfMessages',
        'ApproximateNumberOfMessagesNotVisible',
        'ApproximateNumberOfMessagesDelayed',
    )
    if not all(key in attrs for key in keys):
        return None
    values = [_safe_int(attrs.get(key)) for key in keys]
    if any(value is None for value in values):
        return None
    return sum(int(value) for value in values)


def _no_action_recovery_decision() -> Dict[str, Any]:
    return {
        'disposition': 'no_action',
        'missing_evidence': [],
        'action_candidates': {
            'hold_for_evidence': {'recommended': False},
            'redrive': {'recommended': False},
            'purge': {'recommended': False},
        },
        'mutation_allowed': False,
    }


def build_dlq_disposition(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    marker = data.get('dlq_backlog')
    if not isinstance(marker, dict):
        marker = (data.get('logs_insights') or {}).get('dlq_backlog')
    if not isinstance(marker, dict):
        return None

    current = marker.get('current') or {}
    if not current.get('marker_seen'):
        return None
    latest = current.get('latest_event')
    recent = marker.get('recent_sample') or {}
    sqs_rows = _sqs_rows_by_name(data.get('sqs_context'))

    queue_evidence = []
    for marker_queue in (latest or {}).get('queues') or []:
        if not isinstance(marker_queue, dict):
            continue
        queue_name = str(marker_queue.get('queue_name') or '')
        live_row = sqs_rows.get(queue_name) or {}
        attrs = live_row.get('attributes') or {}
        live_depth = _live_queue_depth(live_row)
        confirmed_sources = [
            str(name)
            for name in live_row.get('dead_letter_source_queues') or []
            if name
        ]
        inferred_source = (
            queue_name[:-4]
            if not confirmed_sources and queue_name.endswith('-dlq')
            else None
        )
        source_names = confirmed_sources or (
            [inferred_source] if inferred_source else []
        )
        consumers = []
        consumer_lookup_status = []
        for source_name in source_names:
            source_row = sqs_rows.get(source_name) or {}
            consumer_data = source_row.get('lambda_consumers') or {}
            consumer_lookup_status.append({
                'queue_name': source_name,
                'status': consumer_data.get('status') or 'unavailable',
            })
            consumers.extend([
                {
                    'source_queue': source_name,
                    'function_name': mapping.get('function_name'),
                    'function_arn': mapping.get('function_arn'),
                    'state': mapping.get('state'),
                    'last_processing_result': mapping.get(
                        'last_processing_result'
                    ),
                    'function_response_types': mapping.get(
                        'function_response_types'
                    ) or [],
                }
                for mapping in consumer_data.get('mappings') or []
                if isinstance(mapping, dict)
            ])
        redrive_capability = _redrive_capability(
            queue_name,
            live_row,
            source_names,
            sqs_rows,
        )
        consumer_contract = _consumer_contract(consumers)
        recovery_decision = (
            _no_action_recovery_decision()
            if live_depth == 0
            else decide_queue_recovery({
                'technical_redrive_supported': redrive_capability['supported'],
                'failure_class': 'unknown',
                'replay_safety': 'unknown',
                'obsolescence': 'unknown',
                'evidence_preserved': False,
            })
        )
        queue_evidence.append({
            'queue_name': queue_name,
            'marker_depth': marker_queue.get('message_count'),
            'depth': (
                live_depth
                if live_depth is not None
                else marker_queue.get('message_count')
            ),
            'depth_source': (
                'live_sqs_attributes'
                if live_depth is not None
                else 'marker_snapshot_fallback'
            ),
            'live_depth': live_depth,
            'marker_visible': marker_queue.get('visible_message_count'),
            'marker_not_visible': marker_queue.get(
                'not_visible_message_count'
            ),
            'marker_delayed': marker_queue.get('delayed_message_count'),
            'live_visible': _safe_int(
                attrs.get('ApproximateNumberOfMessages')
            ),
            'live_not_visible': _safe_int(
                attrs.get('ApproximateNumberOfMessagesNotVisible')
            ),
            'live_delayed': _safe_int(
                attrs.get('ApproximateNumberOfMessagesDelayed')
            ),
            'source_queue_status': (
                'confirmed'
                if confirmed_sources
                else 'inferred_from_dlq_name'
                if inferred_source
                else 'unavailable'
            ),
            'source_queues': source_names,
            'lambda_consumers': consumers,
            'consumer_lookup': consumer_lookup_status,
            'redrive_capability': redrive_capability,
            'consumer_contract': consumer_contract,
            'recovery_decision': recovery_decision,
        })

    marker_message_count = _safe_int((latest or {}).get('message_count'))
    if marker_message_count is None:
        marker_message_count = _safe_int(
            (latest or {}).get('calculated_message_count')
        )
    if marker_message_count is None:
        marker_message_count = sum(
            _safe_int(queue.get('message_count')) or 0
            for queue in (latest or {}).get('queues') or []
            if isinstance(queue, dict)
        )
    live_depths_known = bool(queue_evidence) and all(
        queue.get('live_depth') is not None
        for queue in queue_evidence
    )
    current_message_count = (
        sum(int(queue.get('live_depth') or 0) for queue in queue_evidence)
        if live_depths_known
        else marker_message_count
    )
    current_queue_count = (
        sum(1 for queue in queue_evidence if (queue.get('live_depth') or 0) > 0)
        if live_depths_known
        else _safe_int((latest or {}).get('queue_count')) or len(queue_evidence)
    )
    live_sqs_observed_empty = (
        live_depths_known and current_message_count == 0
    )
    active_backlog = current_message_count > 0
    judgment = 'no_action' if live_sqs_observed_empty else 'needs_fix'
    disposition = (
        'no_action' if live_sqs_observed_empty else 'hold_for_evidence'
    )

    parse_issues = current.get('parse_issues') or []
    event_type = (
        (latest or {}).get('event_type')
        or (
            parse_issues[0].get('event_type')
            if parse_issues and isinstance(parse_issues[0], dict)
            else None
        )
    )
    marker_backlog_detected = (
        event_type == 'DLQ_BACKLOG_DETECTED'
        and marker_message_count > 0
    )
    missing_evidence = (
        []
        if live_sqs_observed_empty
        else [
            'message_outcome',
            'side_effect_and_idempotency_safety',
        ]
    )
    if not live_depths_known:
        missing_evidence.append('live_queue_depths')
    if not queue_evidence:
        missing_evidence.append('queue_depths')
    if active_backlog and any(
        not item.get('source_queues') for item in queue_evidence
    ):
        missing_evidence.append('source_queue')
    if active_backlog and any(
        not item.get('lambda_consumers') for item in queue_evidence
    ):
        missing_evidence.append(
            'consumer_identity_when_not_lambda_event_source'
        )
    monitor_lambda_health = _lambda_health_evidence(
        data.get('lambda_context')
    )
    live_observed_at = (data.get('sqs_context') or {}).get('observed_at')
    response_facts = {
        'processing_status': judgment,
        'backlog_status': (
            'empty_in_live_snapshot'
            if live_sqs_observed_empty
            else 'active_backlog'
        ),
        'judgment': judgment,
        'disposition': disposition,
        'confirmed_signal': (
            'live_sqs_snapshot_empty'
            if live_sqs_observed_empty
            else 'live_sqs_backlog_present'
            if live_depths_known
            else event_type or 'dlq_marker_unparsed'
        ),
        'underlying_failure_cause': 'unconfirmed',
        'observed_at_kst': _format_kst(
            live_observed_at or (latest or {}).get('observed_at')
        ),
        'marker_observed_at_kst': _format_kst(
            (latest or {}).get('observed_at')
        ),
        'total_message_count': current_message_count,
        'marker_message_count': marker_message_count,
        'live_sqs_snapshot_complete': live_depths_known,
        'current_state_unavailable_queues': [
            queue.get('queue_name')
            for queue in queue_evidence
            if queue.get('live_depth') is None
        ],
        'live_sqs_observed_empty': live_sqs_observed_empty,
        'inspection_issues': parse_issues,
        'queues': [
            {
                'queue_name': queue.get('queue_name'),
                'depth': queue.get('depth'),
                'marker_depth': queue.get('marker_depth'),
                'depth_source': queue.get('depth_source'),
                'depth_is_approximate': True,
                'source_queues': queue.get('source_queues') or [],
                'consumers': [
                    {
                        'function_name': consumer.get('function_name'),
                        'mapping_state': consumer.get('state'),
                    }
                    for consumer in queue.get('lambda_consumers') or []
                ],
                'redrive_capability': queue.get('redrive_capability'),
                'consumer_contract': queue.get('consumer_contract'),
                'recovery_decision': queue.get('recovery_decision'),
                'consumer_runtime_metrics_collected': False,
            }
            for queue in queue_evidence
        ],
        'scope': (
            'infra_common; project/campaign/user_journey unconfirmed'
        ),
        'frequency_summary_ko': (
            '제한된 최근 표본: 이벤트 '
            f"{_safe_int(recent.get('event_count_in_sample')) or 0}건, "
            '최신과 같은 스냅샷 '
            f"{_safe_int(recent.get('same_as_latest_count')) or 0}건, "
            '서로 다른 스냅샷 '
            f"{_safe_int(recent.get('distinct_snapshot_count')) or 0}종. "
            '연속 지속 여부 미확인.'
        ),
        'recurrence_sample': {
            'sample_is_complete_history': False,
            'continuity_confirmed': False,
            'persistence_duration_confirmed': False,
            'event_count': recent.get('event_count_in_sample'),
            'same_as_latest_snapshot_count': recent.get(
                'same_as_latest_count'
            ),
            'distinct_snapshot_count': recent.get(
                'distinct_snapshot_count'
            ),
            'sample_start_kst': _format_kst(
                recent.get('first_observed_at_in_sample')
            ),
            'sample_end_kst': _format_kst(
                recent.get('last_observed_at_in_sample')
            ),
        },
        'monitor_lambda_health': monitor_lambda_health,
        'customer_impact': 'unconfirmed',
        'immediate_action_label_ko': (
            '불필요' if live_sqs_observed_empty else '추적 필요'
        ),
        'immediate_action_reason_ko': (
            '현재 SQS 표본에서 적체가 관측되지 않음'
            if live_sqs_observed_empty
            else '현재 적체가 남아 있고 메시지 결과와 재처리 안전성이 미확인'
        ),
        'action_owner': 'unconfirmed',
        'mutation_allowed': False,
        'next_action': (
            'No queue mutation. Continue scheduled monitoring.'
            if live_sqs_observed_empty
            else 'Confirm outcome and replay safety from existing consumer '
            'logs and metrics. Payload inspection requires explicit approval '
            'because receive_message changes visibility.'
        ),
    }

    return {
        'judgment': judgment,
        'disposition': disposition,
        'event_type': event_type,
        'marker_status': (
            'parsed'
            if latest
            else 'rejected'
            if parse_issues
            else 'missing_payload'
        ),
        'message_count': current_message_count,
        'marker_message_count': marker_message_count,
        'queue_count': current_queue_count,
        'marker_queue_count': (latest or {}).get('queue_count'),
        'live_sqs_snapshot_complete': live_depths_known,
        'live_sqs_observed_empty': live_sqs_observed_empty,
        'queues': queue_evidence,
        'recurrence': {
            'event_count_in_recent_sample': recent.get(
                'event_count_in_sample'
            ),
            'same_as_latest_count': recent.get('same_as_latest_count'),
            'distinct_snapshot_count': recent.get(
                'distinct_snapshot_count'
            ),
            'first_observed_at_in_sample': recent.get(
                'first_observed_at_in_sample'
            ),
            'last_observed_at_in_sample': recent.get(
                'last_observed_at_in_sample'
            ),
        },
        'customer_impact': (
            'unconfirmed_backlog_present'
            if active_backlog
            else 'no_active_backlog_observed'
            if live_sqs_observed_empty
            else 'unconfirmed'
        ),
        'confirmed_cause': (
            'Live SQS approximate attributes show a non-empty DLQ backlog.'
            if active_backlog and live_depths_known
            else 'A prior marker detected backlog, and the current SQS approximate snapshot reports zero messages.'
            if live_sqs_observed_empty
            else 'A structured marker confirmed a non-empty DLQ backlog.'
            if marker_backlog_detected
            else 'The DLQ inspection marker could not confirm queue contents.'
        ),
        'underlying_failure_cause': 'unconfirmed',
        'monitor_lambda_health': monitor_lambda_health,
        'alarm_ok_means_resolved': False,
        'alarm_state_explanation': marker.get('alarm_state_note'),
        'missing_evidence': unique(missing_evidence),
        'action_candidates': {
            'hold_for_evidence': {
                'recommended': active_backlog,
                'reason': (
                    'Backlog is confirmed, but message outcome and replay '
                    'side-effect safety are not.'
                    if active_backlog
                    else 'Live SQS attributes show no active backlog.'
                ),
            },
            'redrive': {
                'recommended': False,
                'reason': 'Requires confirmed outcome and idempotent replay.',
            },
            'purge': {
                'recommended': False,
                'reason': 'Requires proof that every message is obsolete.',
            },
            'stream_replay': {
                'recommended': False,
                'reason': (
                    'Requires source-record identity and downstream replay '
                    'safety evidence.'
                ),
            },
        },
        'recommended_next_action': (
            'No queue mutation. Continue scheduled monitoring.'
            if live_sqs_observed_empty
            else 'Confirm outcome and replay safety from consumer logs/metrics. '
            'Payload inspection requires approval because receive_message '
            'changes visibility. No redrive, purge, delete, or replay yet.'
        ),
        'response_guardrails': [
            'Do not invent an underlying failure cause or call the messages stale.',
            'Use exact queue and consumer identifiers; do not infer a product subtype.',
            'Do not describe receive_message or payload inspection as read-only.',
            'Do not call Lambda duration normal without an explicit baseline.',
            'An Enabled event-source mapping is not consumer runtime-health evidence.',
            'Do not call a bounded recent sample complete 7-day history or consecutive events.',
            'Do not turn the sample start/end span into a persistence duration.',
            'Do not assign an owner unless response_facts provides one.',
            'Do not downgrade needs_fix to immediate action unnecessary based only on queue depth.',
            'Use provided KST fields verbatim; do not convert timestamps manually.',
            'Use Korean only except exact technical identifiers.',
        ],
        'response_facts': response_facts,
        'mutation_performed': False,
        'parse_issues': parse_issues,
    }


def assess_helper_context(data: Dict[str, Any]) -> Dict[str, Any]:
    detected = data.get('detected') or {}
    alarm = data.get('alarm_summary') or {}
    alarm_shape = data.get('alarm_shape') or {}
    history = data.get('alarm_history') or {}
    metric = data.get('metric_datapoints') or {}
    hermes_observability = data.get('hermes_observability') or {}
    lambda_discovery = data.get('lambda_discovery') or {}
    lambda_log_signatures = data.get('lambda_log_signatures') or {}
    logs = data.get('logs_insights') or {}
    rds = data.get('rds_context')
    pi_data = data.get('rds_performance_insights')
    http = data.get('http_context')
    sqs = data.get('sqs_context')
    lambda_context = data.get('lambda_context')
    scope = data.get('scope_attribution') or {}
    campaign_hints = data.get('campaign_scope_hints') or {}
    code_hits = data.get('repo_code_hits') or []
    current_error_facts = data.get('current_error_facts') or []
    current_code_locations = data.get('current_code_locations') or []
    dlq_disposition = build_dlq_disposition(data)

    missing: List[Dict[str, Any]] = []
    followups: List[Dict[str, Any]] = []
    root_cause_evidence: List[str] = []
    if dlq_disposition:
        root_cause_evidence.append('dlq_backlog_marker')

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

    hermes_profile_status = bool(alarm_shape.get('hermes_profile_status'))
    hermes_shaped = hermes_profile_status or metric_name == 'HermesServiceHealthy'
    if hermes_shaped:
        breaching_profiles = (
            hermes_observability.get('breaching_profiles')
            if isinstance(hermes_observability, dict)
            else None
        ) or []
        pressure_incidents = (
            hermes_observability.get('pressure_incidents')
            if isinstance(hermes_observability, dict)
            else None
        ) or []
        session_candidates = (
            hermes_observability.get('session_candidates')
            if isinstance(hermes_observability, dict)
            else None
        ) or []
        if breaching_profiles:
            root_cause_evidence.append('hermes_breaching_profiles')
        if pressure_incidents:
            root_cause_evidence.append('hermes_profile_pressure_events')
            if any(incident.get('session_context') for incident in pressure_incidents):
                root_cause_evidence.append('hermes_session_attribution')
        if session_candidates:
            root_cause_evidence.append('hermes_session_candidates')
        if (
            hermes_profile_status
            and breaching_profiles
            and 'hermes_session_attribution' not in root_cause_evidence
        ):
            append_missing(
                missing,
                'hermes_session_attribution',
                'Breaching Hermes profiles were observed, but no exact pressure-event session attribution was resolved.',
            )
            append_followup(
                followups,
                'resolve_hermes_session_attribution',
                'Hermes observability log and profile state.db',
                'Resolve a pressure-event/tool interval for the breaching profile; retain time-overlap sessions as candidates only.',
                ['hermes_observability.pressure_incidents[].session_context'],
                'A time-overlap candidate is not causal session attribution.',
            )
        elif not isinstance(hermes_observability, dict) or hermes_observability.get('status') == 'error':
            append_missing(
                missing,
                'hermes_observability_context',
                'Hermes profile-pressure events or local session attribution are unavailable.',
            )
            append_followup(
                followups,
                'collect_hermes_profile_pressure_context',
                'Hermes observability log and profile state.db',
                'Query the fixed profile_pressure window and resolve the indexed session prefix/tool interval.',
                ['hermes_observability.pressure_incidents', 'hermes_observability.report_facts'],
                'Host-health responses should name the profile and full parent/subagent sessions when available.',
            )

    dimensionless_lambda = bool(alarm_shape.get('dimensionless_lambda'))
    log_shaped = bool(
        logs
        or data.get('metric_filters')
        or 'aws/logs' in namespace.lower()
        or (detected.get('log_groups') and not dimensionless_lambda)
    )
    db_relevance = (
        rds.get('db_relevance')
        if isinstance(rds, dict)
        else None
    ) or alarm_shape.get('db_relevance') or {}
    db_level = str(db_relevance.get('level') or 'none')
    fallback_pi = bool(
        isinstance(rds, dict)
        and rds.get('target_source') == 'production_default_correlation'
    )
    rds_shaped = bool(
        'aws/rds' in namespace.lower()
        or db_level in {'candidate', 'confirmed'}
        or {'dbclusteridentifier', 'dbinstanceidentifier'} & dim_names
        or metric_name.lower() in {'cpuutilization', 'freeablememory', 'databaseload', 'readiops', 'writeiops', 'volumereadiops', 'volumewriteiops'}
    )
    http_shaped = bool(
        namespace in {'AWS/ApplicationELB', 'AWS/ApiGateway', 'AWS/CloudFront'}
        or {'statuscode', 'status_code', 'status', 'httpstatus', 'http_status', 'path', 'route', 'resource', 'normalizedpath', 'method'} & dim_names
        or re.search(r'(?i)(4xx|5xx|httpcode|http)', metric_name)
    )
    sqs_shaped = bool(detected.get('queue_names') or 'aws/sqs' in namespace.lower() or 'queuename' in dim_names)
    lambda_shaped = bool(
        dimensionless_lambda
        or detected.get('lambda_names')
        or 'aws/lambda' in namespace.lower()
        or 'functionname' in dim_names
    )

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
        current_top_signatures = logs.get('current_top_signatures') or []

        if current_top_signatures:
            root_cause_evidence.append('current_alarm_log_signature')
            if current_error_details:
                root_cause_evidence.append('current_alarm_error_detail')
        elif not current_contexts:
            append_missing(missing, 'current_trigger_contexts', 'No CloudWatch log context was found in the current alarm window.')
            append_followup(
                followups,
                'query_current_alarm_log_contexts',
                'AWS CloudWatch Logs Insights',
                'Query the latest ALARM breaching datapoint window with the primary metric filter, then fetch trigger-centered stream context.',
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

        if log_shaped and not current_top_signatures and not current_contexts:
            append_missing(
                missing,
                'current_alarm_signature',
                'Log-derived alarm but no current alarm-window signature or context was produced. The metric filter may be too narrow or the log events may still be ingesting.',
                severity='required',
            )
            append_followup(
                followups,
                'fallback_current_signature_query',
                'AWS CloudWatch Logs Insights',
                'Re-query the current alarm window with a broader ERROR/Exception filter to capture the concrete triggering message.',
                ['logs.current_top_signatures', 'logs.current_error_details'],
                'The final cause must start with the exact trigger signature; frequency/state are not sufficient.',
            )

        if current_error_facts:
            root_cause_evidence.append('current_sentry_error_facts')
            has_code_location = any(
                isinstance(location, dict)
                and (
                    isinstance(location.get('error_location'), dict)
                    or isinstance(location.get('page'), dict)
                )
                for location in current_code_locations
            )
            if has_code_location:
                root_cause_evidence.append('current_sentry_code_location')
            else:
                append_missing(
                    missing,
                    'current_sentry_code_location',
                    'Sentry issue facts were parsed but no stack frame or matching page route was resolved.',
                )
                append_followup(
                    followups,
                    'resolve_sentry_code_location',
                    'Sentry stack trace or local notifly-event repository',
                    'Fetch the latest Sentry event stack frame, or match its transaction to a Next.js page and rendered component.',
                    ['current_code_locations'],
                    'The final cause should distinguish the matched page from the exact throwing function.',
                )

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
        elif fallback_pi:
            root_cause_evidence.append('rds_correlated_top_sql')
            has_current_db_evidence = any(
                str(item).startswith('current_log:')
                for item in db_relevance.get('evidence') or []
            )
            if not has_current_db_evidence:
                append_missing(
                    missing,
                    'db_causal_link',
                    'Production-default PI data is correlated context only; no current alarm-window DB evidence links it to this alarm.',
                )
                append_followup(
                    followups,
                    'confirm_current_db_causal_link',
                    'Current Lambda/service logs',
                    'Confirm a query, connection, deadlock, or DB timeout signature in the current alarm window before treating fallback PI as causal.',
                    ['rds.db_relevance.evidence', 'lambda_log_signatures.db_evidence'],
                    'Production-default correlation cannot establish root cause by itself.',
                )
        else:
            root_cause_evidence.append('rds_explicit_top_sql')

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
        append_missing(
            missing,
            'sqs_queue_context',
            'SQS queue attributes/metrics are unavailable.',
            severity='informational' if dlq_disposition else 'required',
        )
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

    offenders = (
        lambda_discovery.get('offenders')
        if isinstance(lambda_discovery, dict)
        else None
    ) or []
    discovery_resolved = bool(
        offenders
        or (
            isinstance(lambda_discovery, dict)
            and lambda_discovery.get('derived_lambda_names')
        )
    )
    if offenders:
        root_cause_evidence.append('lambda_top_offender')

    current_lambda_error = lambda_signatures_have_current_error(
        lambda_log_signatures
    )
    healthy_lambda_batch = bool(
        dimensionless_lambda
        and offenders
        and all(
            _safe_int(item.get('errors')) == 0
            and _safe_int(item.get('throttles')) == 0
            for item in offenders
            if isinstance(item, dict)
        )
        and history_has_quick_recovery(history)
        and (_safe_int(history.get('alarm_count_7d')) or 0) >= 2
    )
    if current_lambda_error:
        root_cause_evidence.append('lambda_current_error')
    elif healthy_lambda_batch:
        root_cause_evidence.append('healthy_lambda_batch_pattern')
    elif dimensionless_lambda:
        append_missing(
            missing,
            'lambda_execution_mechanism',
            'The aggregate Lambda offender is known, but neither a current error/timeout nor the complete healthy recurring-batch pattern was established.',
        )
        append_followup(
            followups,
            'resolve_lambda_execution_mechanism',
            'Current-window Lambda logs and peer metrics',
            'Use the discovered functions and fixed current-window signatures to distinguish timeout/error from a healthy high-volume batch.',
            ['lambda_log_signatures.signatures', 'lambda_discovery.offenders'],
            'Aggregate Duration alone does not identify the execution mechanism.',
        )

    if (
        lambda_shaped
        and not discovery_resolved
        and (not isinstance(lambda_context, dict) or lambda_context.get('error'))
    ):
        append_missing(missing, 'lambda_context', 'Lambda configuration/event-source/metric context is unavailable.')
        append_followup(
            followups,
            'describe_lambda_context',
            'AWS Lambda/CloudWatch',
            'Fetch Lambda configuration, event source mappings, async config, and error/throttle/duration metrics.',
            ['lambda'],
            'Lambda alerts need function/runtime/source context.',
        )
    elif lambda_shaped and isinstance(lambda_context, dict) and lambda_context_has_signal(lambda_context):
        root_cause_evidence.append('lambda_runtime_metrics')
    elif lambda_shaped and not discovery_resolved:
        append_missing(missing, 'lambda_context', 'Lambda context was inferred but no matching function configuration or runtime datapoints were found.')
        append_followup(
            followups,
            'verify_lambda_identity',
            'AWS Lambda/CloudWatch',
            'Verify that the detected name is a real Lambda FunctionName, log group, or alarm dimension before doing Lambda-specific follow-up.',
            ['detected.lambda_names', 'lambda'],
            'Do not treat service alarm names as Lambda function names.',
        )

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
    scope_is_common = bool(
        scope.get('service_indicators')
        or scope.get('infra_indicators')
        or hermes_shaped
    )
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
    required_missing = [
        item for item in missing
        if str(item.get('severity') or 'required').lower() == 'required'
    ]
    if root_cause_evidence:
        evidence_is_sufficient = not any(
            item.get('key') in {
                'alarm_metadata',
                'alarm_history',
                'latest_alarm_transition',
            }
            for item in missing
        )
    else:
        evidence_is_sufficient = (
            not blocking_missing and not (log_shaped or rds_shaped)
        )

    can_answer = bool(evidence_is_sufficient and not required_missing)
    selected_followups = [] if can_answer else followups[:2]

    return {
        'can_answer_root_cause': bool(can_answer),
        'next_action': (
            'finalize_now_no_more_tools'
            if can_answer
            else 'run_only_listed_followups_then_finalize'
        ),
        'root_cause_evidence': root_cause_evidence,
        'dlq_disposition': dlq_disposition,
        'missing_required_context': missing,
        'required_followups': selected_followups,
        'omitted_followup_count': max(0, len(followups) - len(selected_followups)),
        'note': (
            'STOP: evidence is sufficient. Do not call another tool; produce '
            'the final response now.'
            if can_answer
            else 'Perform only the listed read-only follow-ups, then finalize '
            'with unavailable fields stated explicitly.'
        ),
    }

COMPACT_OUTPUT_MAX_BYTES = 10_000


def _bounded_value(
    value: Any,
    *,
    depth: int = 0,
    max_depth: int = 3,
    max_items: int = 3,
    max_keys: int = 12,
    max_string: int = 420,
) -> Any:
    if isinstance(value, str):
        return truncate(value, max_string)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if depth >= max_depth:
        if isinstance(value, dict):
            return {'summary': f'{len(value)} keys omitted'}
        if isinstance(value, (list, tuple)):
            return [f'{len(value)} items omitted']
        return truncate(str(value), max_string)
    if isinstance(value, dict):
        compact: Dict[str, Any] = {}
        for key, item in list(value.items())[:max_keys]:
            compact[str(key)] = _bounded_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
                max_keys=max_keys,
                max_string=max_string,
            )
        if len(value) > max_keys:
            compact['_omitted_key_count'] = len(value) - max_keys
        return compact
    if isinstance(value, (list, tuple)):
        compact_items = [
            _bounded_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
                max_keys=max_keys,
                max_string=max_string,
            )
            for item in list(value)[:max_items]
        ]
        if len(value) > max_items:
            compact_items.append(
                {'_omitted_item_count': len(value) - max_items}
            )
        return compact_items
    return truncate(str(value), max_string)


def _compact_logs(logs_summary: Any) -> Any:
    if not isinstance(logs_summary, dict):
        return _bounded_value(logs_summary)
    keys = (
        'log_groups',
        'filter_terms',
        'skipped',
        'count_7d',
        'count_30d',
        'daily_counts_30d',
        'current_alarm_window',
        'current_top_signatures',
        'current_trigger_contexts',
        'current_error_details',
        'current_project_campaign_pairs',
        'detected_scope_ids',
        'query_status',
        'errors',
    )
    return _bounded_value(
        {key: logs_summary.get(key) for key in keys if key in logs_summary},
        max_items=2,
        max_keys=len(keys),
        max_string=360,
    )


def _compact_dlq_backlog(marker: Any) -> Any:
    if not isinstance(marker, dict):
        return None
    current = marker.get('current') or {}
    recent = marker.get('recent_sample') or {}
    latest = current.get('latest_event') or {}
    return {
        'marker_seen': current.get('marker_seen'),
        'event_type': latest.get('event_type'),
        'observed_at': latest.get('observed_at'),
        'region': latest.get('region'),
        'message_count': latest.get('message_count'),
        'calculated_message_count': latest.get(
            'calculated_message_count'
        ),
        'count_consistent': latest.get('count_consistent'),
        'queue_count': latest.get('queue_count'),
        'queues': [
            {
                'queue_name': queue.get('queue_name'),
                'message_count': queue.get('message_count'),
                'visible_message_count': queue.get(
                    'visible_message_count'
                ),
                'not_visible_message_count': queue.get(
                    'not_visible_message_count'
                ),
                'delayed_message_count': queue.get(
                    'delayed_message_count'
                ),
                'message_retention_period_seconds': queue.get(
                    'message_retention_period_seconds'
                ),
            }
            for queue in latest.get('queues') or []
            if isinstance(queue, dict)
        ],
        'recent_sample': {
            'event_count': recent.get('event_count_in_sample'),
            'same_as_latest_count': recent.get('same_as_latest_count'),
            'distinct_snapshot_count': recent.get(
                'distinct_snapshot_count'
            ),
            'first_observed_at': recent.get(
                'first_observed_at_in_sample'
            ),
            'last_observed_at': recent.get(
                'last_observed_at_in_sample'
            ),
        },
        'parse_issues': current.get('parse_issues') or [],
        'alarm_state_note': marker.get('alarm_state_note'),
    }


def _compact_dlq_disposition(disposition: Any) -> Any:
    if not isinstance(disposition, dict):
        return None
    response_facts = disposition.get('response_facts') or {}
    compact_queues = []
    for queue in response_facts.get('queues') or []:
        if not isinstance(queue, dict):
            continue
        capability = queue.get('redrive_capability') or {}
        contract = queue.get('consumer_contract') or {}
        decision = queue.get('recovery_decision') or {}
        compact_queues.append({
            'queue_name': queue.get('queue_name'),
            'depth': queue.get('depth'),
            'marker_depth': queue.get('marker_depth'),
            'depth_source': queue.get('depth_source'),
            'depth_is_approximate': queue.get('depth_is_approximate'),
            'source_queues': queue.get('source_queues') or [],
            'consumers': queue.get('consumers') or [],
            'technical_redrive_supported': capability.get('supported'),
            'max_receive_count': capability.get('max_receive_count'),
            'partial_batch_failure_reporting': contract.get(
                'partial_batch_failure_reporting'
            ),
            'recovery_disposition': decision.get('disposition'),
            'missing_recovery_evidence': decision.get(
                'missing_evidence'
            ) or [],
            'mutation_allowed': decision.get('mutation_allowed'),
        })
    compact_response_facts = {
        key: response_facts.get(key)
        for key in (
            'processing_status',
            'backlog_status',
            'judgment',
            'disposition',
            'confirmed_signal',
            'underlying_failure_cause',
            'observed_at_kst',
            'marker_observed_at_kst',
            'total_message_count',
            'marker_message_count',
            'live_sqs_snapshot_complete',
            'current_state_unavailable_queues',
            'live_sqs_observed_empty',
            'inspection_issues',
            'scope',
            'frequency_summary_ko',
            'recurrence_sample',
            'customer_impact',
            'immediate_action_label_ko',
            'immediate_action_reason_ko',
            'action_owner',
            'mutation_allowed',
            'next_action',
        )
    }
    recurrence_sample = response_facts.get('recurrence_sample') or {}
    compact_response_facts['recurrence_sample'] = {
        key: recurrence_sample.get(key)
        for key in (
            'sample_is_complete_history',
            'continuity_confirmed',
            'persistence_duration_confirmed',
            'event_count',
            'same_as_latest_snapshot_count',
            'distinct_snapshot_count',
        )
    }
    compact_response_facts['queues'] = compact_queues
    return {
        'judgment': disposition.get('judgment'),
        'disposition': disposition.get('disposition'),
        'event_type': disposition.get('event_type'),
        'marker_status': disposition.get('marker_status'),
        'message_count': disposition.get('message_count'),
        'marker_message_count': disposition.get('marker_message_count'),
        'queue_count': disposition.get('queue_count'),
        'marker_queue_count': disposition.get('marker_queue_count'),
        'live_sqs_snapshot_complete': disposition.get(
            'live_sqs_snapshot_complete'
        ),
        'live_sqs_observed_empty': disposition.get(
            'live_sqs_observed_empty'
        ),
        'customer_impact': disposition.get('customer_impact'),
        'alarm_ok_means_resolved': disposition.get(
            'alarm_ok_means_resolved'
        ),
        'alarm_state_explanation': disposition.get(
            'alarm_state_explanation'
        ),
        'missing_evidence': disposition.get('missing_evidence') or [],
        'response_guardrails': disposition.get(
            'response_guardrails'
        ) or [],
        'response_facts': compact_response_facts,
        'mutation_performed': disposition.get('mutation_performed'),
        'parse_issues': disposition.get('parse_issues') or [],
    }


def _compact_sqs_context(sqs_context: Any) -> Any:
    if not isinstance(sqs_context, dict):
        return sqs_context
    queues = []
    for group in sqs_context.get('queues') or []:
        if not isinstance(group, dict):
            continue
        related = []
        for row in group.get('related_queues') or []:
            if not isinstance(row, dict):
                continue
            attrs = row.get('attributes') or {}
            related.append({
                'queue_name': row.get('queue_name'),
                'attributes': {
                    key: attrs.get(key)
                    for key in (
                        'ApproximateNumberOfMessages',
                        'ApproximateNumberOfMessagesNotVisible',
                        'ApproximateNumberOfMessagesDelayed',
                        'MessageRetentionPeriod',
                        'VisibilityTimeout',
                        'RedrivePolicy',
                        'RedriveAllowPolicy',
                    )
                    if key in attrs
                },
                'dead_letter_source_queues': (
                    row.get('dead_letter_source_queues') or []
                ),
                'lambda_consumers': row.get('lambda_consumers'),
                'error': row.get('error'),
            })
        queues.append({
            'detected_queue': group.get('detected_queue'),
            'related_queues': related,
        })
    return {
        'observed_at': sqs_context.get('observed_at'),
        'days': sqs_context.get('days'),
        'requested_queue_count': sqs_context.get('requested_queue_count'),
        'collected_queue_count': sqs_context.get('collected_queue_count'),
        'omitted_queue_names': sqs_context.get('omitted_queue_names') or [],
        'queues': queues,
        'note': sqs_context.get('note'),
    }


def _compact_lambda_log_signatures(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    signatures = []
    for item in (value.get('signatures') or [])[:10]:
        if not isinstance(item, dict):
            continue
        signatures.append({
            'signature': truncate(str(item.get('signature') or ''), 220),
            'count_in_current_alarm_window': item.get(
                'count_in_current_alarm_window'
            ),
            'sample_lines': [
                truncate(str(line), 220)
                for line in (item.get('sample_lines') or [])[:1]
            ],
        })
    return {
        'status': value.get('status'),
        'window_start': value.get('window_start'),
        'window_end': value.get('window_end'),
        'log_groups': (value.get('log_groups') or [])[:5],
        'signatures': signatures,
        'db_evidence': [
            truncate(str(line), 220)
            for line in (value.get('db_evidence') or [])[:3]
        ],
        'query_status': value.get('query_status'),
        'error': truncate(str(value.get('error') or ''), 220) or None,
    }


def _compact_rds_performance_insights(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    instances = []
    for item in (value.get('instances') or [])[:4]:
        if not isinstance(item, dict):
            continue
        top_sql = []
        for sql in (item.get('top_sql') or [])[:1]:
            if not isinstance(sql, dict):
                continue
            top_sql.append({
                key: (
                    truncate(str(sql.get(key) or ''), 220)
                    if key == 'statement'
                    else sql.get(key)
                )
                for key in (
                    'sql_id',
                    'statement',
                    'table_refs',
                    'focus_avg_load',
                    'focus_max_load',
                    'avg_load',
                    'max_load',
                )
                if sql.get(key) is not None
            })
        instances.append({
            'instance_id': item.get('instance_id'),
            'role_hint': item.get('role_hint'),
            'dbi_resource_id': item.get('dbi_resource_id'),
            'top_sql': top_sql,
            'error': truncate(str(item.get('error') or ''), 220) or None,
        })
    scope = value.get('detected_scope_ids') or {}
    compact_scope = None
    if isinstance(scope, dict):
        compact_scope = {
            'project_ids': (scope.get('project_ids') or [])[:5],
            'current_top_projects_by_load': [
                {
                    key: item.get(key)
                    for key in (
                        'project_id',
                        'focus_avg_load_sum',
                        'focus_max_load',
                        'focus_points',
                    )
                    if item.get(key) is not None
                }
                for item in (
                    scope.get('current_top_projects_by_load') or []
                )[:3]
                if isinstance(item, dict)
            ],
        }
    return {
        'window_start': value.get('window_start'),
        'window_end': value.get('window_end'),
        'focus_window_start': value.get('focus_window_start'),
        'focus_window_end': value.get('focus_window_end'),
        'source': value.get('source'),
        'target_source': value.get('target_source'),
        'evidence_level': value.get('evidence_level'),
        'instances': instances,
        'detected_scope_ids': compact_scope,
    }


def _serialized_size(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            default=str,
        ).encode('utf-8')
    )


def _minimal_dlq_budget_output(
    result: Dict[str, Any],
    omitted: Sequence[str],
) -> Dict[str, Any]:
    disposition = result.get('dlq_disposition') or {}
    facts = disposition.get('response_facts') or {}
    queue_rows = []
    recovery_overrides: Dict[str, List[str]] = {}
    for queue in facts.get('queues') or []:
        if not isinstance(queue, dict):
            continue
        row = {
            'queue_name': queue.get('queue_name'),
            'depth': queue.get('depth'),
        }
        if queue.get('marker_depth') != queue.get('depth'):
            row['marker_depth'] = queue.get('marker_depth')
        if queue.get('depth_source') != 'live_sqs_attributes':
            row['depth_source'] = 'marker'
        queue_rows.append(row)
        queue_disposition = queue.get('recovery_disposition')
        if (
            queue_disposition
            and queue_disposition != disposition.get('disposition')
        ):
            recovery_overrides.setdefault(queue_disposition, []).append(
                str(queue.get('queue_name') or '')
            )

    minimal_facts = {
        'processing_status': facts.get('processing_status'),
        'backlog_status': facts.get('backlog_status'),
        'total_message_count': facts.get('total_message_count'),
        'marker_message_count': facts.get('marker_message_count'),
        'live_sqs_snapshot_complete': facts.get(
            'live_sqs_snapshot_complete'
        ),
        'live_sqs_observed_empty': facts.get('live_sqs_observed_empty'),
        'queues': queue_rows,
        'customer_impact': facts.get('customer_impact'),
        'mutation_allowed': facts.get('mutation_allowed'),
        'next_action': facts.get('next_action'),
    }
    if recovery_overrides:
        minimal_facts['recovery_disposition_overrides'] = recovery_overrides

    alarm = result.get('alarm') or {}
    omitted_sections = sorted(
        set([*omitted, 'nonessential_evidence', 'verbose_dlq_evidence'])
    )
    minimal = {
        'can_answer_root_cause': result.get('can_answer_root_cause'),
        'next_action': result.get('next_action'),
        'dlq_disposition': {
            'judgment': disposition.get('judgment'),
            'disposition': disposition.get('disposition'),
            'event_type': disposition.get('event_type'),
            'message_count': disposition.get('message_count'),
            'marker_message_count': disposition.get('marker_message_count'),
            'queue_count': disposition.get('queue_count'),
            'live_sqs_snapshot_complete': disposition.get(
                'live_sqs_snapshot_complete'
            ),
            'live_sqs_observed_empty': disposition.get(
                'live_sqs_observed_empty'
            ),
            'response_facts': minimal_facts,
            'mutation_performed': disposition.get('mutation_performed'),
        },
        'alarm': {
            'name': alarm.get('name'),
            'state': alarm.get('state'),
        },
        'omitted_sections': omitted_sections,
    }
    if result.get('missing_required_context'):
        minimal['missing_required_context'] = result['missing_required_context']
    if result.get('required_followups'):
        minimal['required_followups'] = result['required_followups']
    if _serialized_size(minimal) <= COMPACT_OUTPUT_MAX_BYTES:
        return minimal

    queue_matrix = [
        [
            queue.get('queue_name'),
            queue.get('depth'),
            queue.get('marker_depth'),
            {
                'redrive_candidate': 'r',
                'purge_candidate': 'p',
                'hold_for_evidence': 'h',
                'no_action': 'n',
            }.get(queue.get('recovery_disposition'), '?'),
            (
                'l'
                if queue.get('depth_source') == 'live_sqs_attributes'
                else 'm'
            ),
        ]
        for queue in facts.get('queues') or []
        if isinstance(queue, dict)
    ]
    minimal['omitted_sections'] = [
        'nonessential_evidence',
        'verbose_dlq_evidence',
    ]
    minimal['dlq_disposition']['response_facts'] = {
        'processing_status': facts.get('processing_status'),
        'queue_fields': [
            'queue_name',
            'depth',
            'marker_depth',
            'recovery_disposition',
            'depth_source',
        ],
        'queue_value_codes': {
            'recovery_disposition': (
                'r=redrive_candidate,p=purge_candidate,'
                'h=hold_for_evidence,n=no_action,?=unknown'
            ),
            'depth_source': (
                'l=live_sqs_attributes,m=marker_snapshot_fallback'
            ),
        },
        'queues': queue_matrix,
        'mutation_allowed': facts.get('mutation_allowed'),
    }
    return minimal


def _minimal_non_dlq_budget_output(
    result: Dict[str, Any],
    omitted: Sequence[str],
) -> Dict[str, Any]:
    discovery = result.get('lambda_discovery') or {}
    signatures = result.get('lambda_log_signatures') or {}
    rds = result.get('rds') or {}
    pi_data = result.get('rds_performance_insights') or {}
    hermes = result.get('hermes_observability') or {}
    history = result.get('history') or {}

    compact_discovery = {
        'status': discovery.get('status'),
        'window_start': discovery.get('window_start'),
        'window_end': discovery.get('window_end'),
        'offenders': [
            {
                key: row.get(key)
                for key in (
                    'function_name',
                    'duration_sum_ms',
                    'duration_avg_ms',
                    'invocations',
                    'errors',
                    'throttles',
                    'evidence_level',
                )
                if row.get(key) is not None
            }
            for row in (discovery.get('offenders') or [])[:5]
            if isinstance(row, dict)
        ],
    }
    compact_signatures = {
        'status': signatures.get('status'),
        'window_start': signatures.get('window_start'),
        'window_end': signatures.get('window_end'),
        'log_groups': (signatures.get('log_groups') or [])[:5],
        'signatures': [
            {
                'signature': truncate(str(row.get('signature') or ''), 180),
                'count_in_current_alarm_window': row.get(
                    'count_in_current_alarm_window'
                ),
            }
            for row in (signatures.get('signatures') or [])[:5]
            if isinstance(row, dict)
        ],
        'db_evidence': [
            truncate(str(line), 180)
            for line in (signatures.get('db_evidence') or [])[:2]
        ],
        'error': signatures.get('error'),
    }
    compact_rds = {
        'status': rds.get('status'),
        'target_source': rds.get('target_source'),
        'db_relevance': _bounded_value(
            rds.get('db_relevance'),
            max_depth=3,
            max_items=5,
            max_string=140,
        ),
        'cluster': {
            'id': (rds.get('cluster') or {}).get('id'),
            'status': (rds.get('cluster') or {}).get('status'),
        } if isinstance(rds.get('cluster'), dict) else None,
        'instances': [
            {
                key: row.get(key)
                for key in ('id', 'role_hint', 'class', 'pi_enabled')
                if row.get(key) is not None
            }
            for row in (rds.get('instances') or [])[:4]
            if isinstance(row, dict)
        ],
    }
    compact_pi = _compact_rds_performance_insights(pi_data)
    compact_history = {
        key: history.get(key)
        for key in (
            'alarm_count_7d',
            'alarm_count_1d',
            'alarm_count_10m',
            'alarm_count_30d',
            'latest_alarm_transition',
            'rapid_recurrence',
        )
        if history.get(key) is not None
    }
    minimal = {
        key: result.get(key)
        for key in (
            'can_answer_root_cause',
            'next_action',
            'input_integrity',
            'missing_required_context',
            'required_followups',
            'omitted_followup_count',
            'root_cause_evidence',
            'alarm',
            'alarm_shape',
            'metric',
            'current_error_facts',
            'current_code_locations',
        )
    }
    minimal.update({
        'history': compact_history,
        'lambda_discovery': compact_discovery,
        'lambda_log_signatures': compact_signatures,
        'rds': compact_rds,
        'rds_performance_insights': compact_pi,
        'hermes_observability': _bounded_value(
            hermes,
            max_depth=6,
            max_items=3,
            max_keys=20,
            max_string=180,
        ),
        'logs': _bounded_value(
            result.get('logs'),
            max_depth=4,
            max_items=2,
            max_keys=12,
            max_string=180,
        ),
        'scope_attribution': _bounded_value(
            result.get('scope_attribution'),
            max_depth=3,
            max_items=3,
            max_keys=12,
            max_string=160,
        ),
        'omitted_sections': sorted(
            set(omitted + ['nonessential_evidence', 'verbose_samples'])
        ),
    })
    if _serialized_size(minimal) <= COMPACT_OUTPUT_MAX_BYTES:
        return minimal

    emergency = {
        key: minimal.get(key)
        for key in (
            'can_answer_root_cause',
            'next_action',
            'input_integrity',
            'missing_required_context',
            'required_followups',
            'omitted_followup_count',
            'root_cause_evidence',
            'alarm',
            'alarm_shape',
        )
    }
    emergency.update({
        'lambda_discovery': {
            **{key: compact_discovery.get(key) for key in ('status', 'window_start', 'window_end')},
            'offenders': (compact_discovery.get('offenders') or [])[:1],
        },
        'lambda_log_signatures': {
            **{key: compact_signatures.get(key) for key in ('status', 'window_start', 'window_end')},
            'signatures': (compact_signatures.get('signatures') or [])[:3],
            'db_evidence': (compact_signatures.get('db_evidence') or [])[:1],
        },
        'rds': {
            'status': compact_rds.get('status'),
            'target_source': compact_rds.get('target_source'),
            'db_relevance': compact_rds.get('db_relevance'),
            'instances': (compact_rds.get('instances') or [])[:2],
        },
        'rds_performance_insights': {
            key: compact_pi.get(key)
            for key in ('target_source', 'evidence_level', 'focus_window_start', 'focus_window_end')
        } if isinstance(compact_pi, dict) else compact_pi,
        'hermes_observability': {
            'status': hermes.get('status'),
            'breaching_profiles': (hermes.get('breaching_profiles') or [])[:3],
            'pressure_incidents': _bounded_value(
                (hermes.get('pressure_incidents') or [])[:1],
                max_depth=5,
                max_items=2,
                max_string=160,
            ),
            'session_candidates': _bounded_value(
                (hermes.get('session_candidates') or [])[:1],
                max_depth=4,
                max_items=2,
                max_string=160,
            ),
            'report_facts': _bounded_value(
                hermes.get('report_facts'),
                max_depth=4,
                max_items=2,
                max_string=160,
            ),
        },
        'omitted_sections': sorted(
            set(omitted + ['nonessential_evidence', 'verbose_samples'])
        ),
    })
    return _bounded_value(
        emergency,
        max_depth=7,
        max_items=5,
        max_keys=24,
        max_string=160,
    )


def _fit_compact_budget(result: Dict[str, Any]) -> Dict[str, Any]:
    if _serialized_size(result) <= COMPACT_OUTPUT_MAX_BYTES:
        return result

    omitted: List[str] = []
    optional = (
        'campaign_scope_hints',
        'five_xx',
        'http',
        'lambda',
        'sqs',
        'metric_filters',
        'code',
        'projects',
        'aws',
    )
    while _serialized_size(result) > COMPACT_OUTPUT_MAX_BYTES:
        candidates = [
            (key, _serialized_size(result.get(key)))
            for key in optional
            if key in result
        ]
        if not candidates:
            break
        largest = max(candidates, key=lambda item: item[1])[0]
        result.pop(largest, None)
        omitted.append(largest)

    if _serialized_size(result) > COMPACT_OUTPUT_MAX_BYTES:
        result['logs'] = _bounded_value(
            result.get('logs'),
            max_depth=2,
            max_items=1,
            max_keys=8,
            max_string=220,
        )
        result['scope_attribution'] = _bounded_value(
            result.get('scope_attribution'),
            max_depth=2,
            max_items=2,
            max_keys=8,
            max_string=220,
        )

    if omitted:
        result['omitted_sections'] = omitted
    if _serialized_size(result) <= COMPACT_OUTPUT_MAX_BYTES:
        return result

    essential_keys = [
        'can_answer_root_cause',
        'next_action',
        'input_integrity',
        'missing_required_context',
        'required_followups',
        'omitted_followup_count',
        'root_cause_evidence',
        'dlq_backlog',
        'dlq_disposition',
        'alarm',
        'scope_attribution',
        'current_error_facts',
        'current_code_locations',
        'hermes_observability',
        'alarm_shape',
        'lambda_discovery',
        'lambda_log_signatures',
        'rds',
        'rds_performance_insights',
    ]
    if not result.get('dlq_disposition'):
        essential_keys.extend(['history', 'metric', 'logs'])
    essential = {
        key: result.get(key)
        for key in essential_keys
    }
    essential['omitted_sections'] = sorted(
        set(omitted + ['nonessential_evidence'])
    )
    bounded = _bounded_value(
        essential,
        max_depth=7,
        max_items=5,
        max_keys=30,
        max_string=180,
    )
    if _serialized_size(bounded) <= COMPACT_OUTPUT_MAX_BYTES:
        return bounded
    if result.get('dlq_disposition'):
        return _minimal_dlq_budget_output(result, omitted)
    return _minimal_non_dlq_budget_output(result, omitted)


def compact_output(data: Dict[str, Any]) -> Dict[str, Any]:
    alarm = data.get('alarm_summary') or {}
    history = data.get('alarm_history') or {}
    metric = data.get('metric_datapoints') or {}
    logs_summary = data.get('logs_insights') or {}
    assessment = data.get('helper_assessment') or assess_helper_context(data)
    result = {
        'can_answer_root_cause': assessment.get('can_answer_root_cause'),
        'next_action': assessment.get('next_action'),
        'input_integrity': _bounded_value(data.get('input_integrity')),
        'missing_required_context': assessment.get('missing_required_context') or [],
        'required_followups': assessment.get('required_followups') or [],
        'omitted_followup_count': assessment.get('omitted_followup_count') or 0,
        'dlq_backlog': _compact_dlq_backlog(data.get('dlq_backlog')),
        'dlq_disposition': _compact_dlq_disposition(
            assessment.get('dlq_disposition')
        ),
        'detected': _bounded_value(data.get('detected')),
        'alarm_shape': _bounded_value(
            data.get('alarm_shape'),
            max_depth=4,
        ),
        'lambda_discovery': _bounded_value(
            data.get('lambda_discovery'),
            max_depth=5,
            max_items=5,
        ),
        'lambda_log_signatures': _bounded_value(
            _compact_lambda_log_signatures(data.get('lambda_log_signatures')),
            max_depth=5,
            max_items=10,
        ),
        'aws': _bounded_value(data.get('aws_caller_identity')),
        'alarm': {
            'name': alarm.get('AlarmName'),
            'state': alarm.get('StateValue'),
            'reason': truncate(str(alarm.get('StateReason') or ''), 260),
            'metric': {
                'namespace': alarm.get('Namespace'),
                'name': alarm.get('MetricName'),
                'statistic': alarm.get('Statistic') or alarm.get('ExtendedStatistic'),
                'period': alarm.get('Period'),
                'threshold': alarm.get('Threshold'),
                'comparison': alarm.get('ComparisonOperator'),
                'dimensions': _bounded_value(alarm.get('Dimensions')),
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
            'daily_alarm_counts': _bounded_value(
                history.get('alarm_daily_counts'),
                max_items=7,
            ),
            'latest_alarm_transition': _bounded_value(
                history.get('latest_alarm_transition')
            ),
            'rapid_recurrence': _bounded_value(history.get('rapid_recurrence')),
            'recent_items': _bounded_value(
                history.get('sample_items'),
                max_items=3,
            ),
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
            'recent_points': _bounded_value(
                (metric.get('recent_points') or [])[-4:],
                max_items=4,
            ),
        },
        'hermes_observability': _bounded_value(
            data.get('hermes_observability'),
            max_depth=7,
            max_items=8,
            max_keys=24,
            max_string=420,
        ),
        'metric_filters': _bounded_value(data.get('metric_filters')),
        'logs': _compact_logs(logs_summary),
        'http': _bounded_value(data.get('http_context')),
        'five_xx': _bounded_value(data.get('five_xx_metrics')),
        'sqs': _compact_sqs_context(data.get('sqs_context')),
        'lambda': _bounded_value(data.get('lambda_context')),
        'rds': _bounded_value(data.get('rds_context')),
        'rds_performance_insights': _compact_rds_performance_insights(
            data.get('rds_performance_insights')
        ),
        'campaign_scope_hints': _bounded_value(
            data.get('campaign_scope_hints')
        ),
        'scope_attribution': _bounded_value(data.get('scope_attribution')),
        'projects': _bounded_value(data.get('project_mappings')),
        'current_error_facts': _bounded_value(
            data.get('current_error_facts'),
            max_depth=5,
            max_items=3,
            max_keys=24,
            max_string=500,
        ),
        'current_code_locations': _bounded_value(
            data.get('current_code_locations'),
            max_depth=5,
            max_items=4,
            max_keys=20,
            max_string=400,
        ),
        'code': _bounded_value(data.get('repo_code_hits')),
        'root_cause_evidence': assessment.get('root_cause_evidence') or [],
        'helper_notes': [
            assessment.get('note'),
            'Logs Insights used fixed query templates only.',
            'Raw log dumps are suppressed; samples are sanitized and grouped by signature.',
            'The compact payload is capped at 10,000 UTF-8 bytes.',
        ],
    }
    return _fit_compact_budget(result)
