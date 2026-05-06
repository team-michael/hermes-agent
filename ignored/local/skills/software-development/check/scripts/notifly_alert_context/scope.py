from .common import *
from .text import sanitize_sql_statement
from .detect import (
    alarm_dimension_value,
    detect_project_ids,
    detect_campaign_ids,
    detect_user_journey_ids,
    detect_user_journey_refs,
)

def project_display_label(project: Dict[str, Any]) -> str:
    product_id = project.get('product_id')
    name = project.get('name')
    project_id = project.get('project_id')
    reason = project.get('mapping_failure_reason') or project.get('error')
    if product_id and name and product_id != name:
        label = f'{product_id}/{name}'
    elif name:
        label = str(name)
    elif product_id:
        label = str(product_id)
    elif project_id:
        label = str(project_id)
    else:
        label = 'unknown_project'
    if project_id and label != str(project_id):
        label = f'{label} ({project_id})'
    if reason and project_id:
        label = f'{label} ({reason})'
    return label

def build_scope_attribution(
    detected: Dict[str, Any],
    alarm: Any,
    project_mappings: Optional[List[Dict[str, Any]]],
    rds_performance_insights: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    projects = []
    for item in project_mappings or []:
        if not isinstance(item, dict):
            continue
        projects.append({
            'project_id': item.get('project_id'),
            'product_id': item.get('product_id'),
            'name': item.get('name'),
            'mapping_status': item.get('mapping_status'),
            'mapping_failure_reason': item.get('mapping_failure_reason'),
            'error': item.get('error'),
        })

    campaign_ids = detected.get('campaign_ids') or []
    project_campaign_pairs = detected.get('project_campaign_pairs') or []
    user_journey_ids = detected.get('user_journey_ids') or []
    user_journey_refs = detected.get('user_journey_refs') or []

    namespace = alarm.get('Namespace') if isinstance(alarm, dict) else None
    metric_name = alarm.get('MetricName') if isinstance(alarm, dict) else None
    namespace_service_indicators: List[str] = []
    if namespace:
        parts = [part for part in str(namespace).split('/') if part]
        if len(parts) >= 2 and parts[0].lower() != 'aws':
            namespace_service_indicators.append(parts[1])
    service_indicators = unique([
        *(detected.get('service_names') or []),
        *namespace_service_indicators,
        *alarm_dimension_value(alarm, ['FunctionName', 'ServiceName', 'ClusterName']),
    ])
    infra_indicators = unique([
        *(detected.get('queue_names') or []),
        *alarm_dimension_value(alarm, ['DBClusterIdentifier', 'DBInstanceIdentifier', 'QueueName', 'CacheClusterId', 'ReplicationGroupId']),
    ])

    common_scope = []
    if service_indicators:
        service_label = ', '.join(service_indicators[:3])
        if len(service_indicators) > 3:
            service_label += f' 외 {len(service_indicators) - 3}개'
        common_scope.append(f'서비스 공통({service_label})')
    if infra_indicators or (namespace and any(token in str(namespace).lower() for token in ['rds', 'sqs', 'elasticache', 'lambda'])):
        common_scope.append('인프라 공통')
    common_scope = unique(common_scope)

    scoped_project_ids = [
        pair.get('project_id')
        for pair in project_campaign_pairs
        if isinstance(pair, dict) and pair.get('project_id')
    ]
    scoped_project_ids = unique(scoped_project_ids)
    scoped_projects = [
        project for project in projects
        if not scoped_project_ids or project.get('project_id') in scoped_project_ids
    ]

    current_top_projects = []
    if isinstance(rds_performance_insights, dict):
        rds_scope = rds_performance_insights.get('detected_scope_ids') or {}
        current_top_projects = [
            item for item in (rds_scope.get('current_top_projects_by_load') or [])
            if isinstance(item, dict) and item.get('project_id') and (item.get('focus_avg_load_sum') or 0) > 0
        ]
    current_load_by_project = {
        item['project_id']: item
        for item in current_top_projects
    }

    def project_label_with_current_load(project: Dict[str, Any]) -> str:
        label = project_display_label(project)
        load = current_load_by_project.get(project.get('project_id'))
        if not load:
            return label
        return (
            f"{label} "
            f"(focus_avg_load={load.get('focus_avg_load_sum')}, max={load.get('focus_max_load')})"
        )

    mapped_project_labels = [
        project_label_with_current_load(p) if current_load_by_project else project_display_label(p)
        for p in scoped_projects
    ]
    if len(mapped_project_labels) > 5:
        project_label = ', '.join(mapped_project_labels[:5]) + f' 외 {len(mapped_project_labels) - 5}개'
    else:
        project_label = ', '.join(mapped_project_labels) or '특정 불가'
    if current_load_by_project and project_label != '특정 불가':
        project_label = f'현재 알람창 부하 상위 {project_label}'
    project_lookup = {p.get('project_id'): p for p in projects if p.get('project_id')}
    pair_labels = []
    pair_keys = set()
    for pair in project_campaign_pairs:
        if not isinstance(pair, dict):
            continue
        project_id = pair.get('project_id')
        campaign_id = pair.get('campaign_id')
        if not project_id or not campaign_id:
            continue
        key = (project_id, campaign_id)
        if key in pair_keys:
            continue
        pair_keys.add(key)
        project = project_lookup.get(project_id) or {}
        project_label_for_pair = project_display_label(project) if project else project_id
        count = pair.get('count')
        suffix_count = f'({count}건)' if count is not None else ''
        pair_labels.append(f'{project_label_for_pair}/{campaign_id}{suffix_count}')
    if pair_labels:
        campaign_label = ', '.join(pair_labels[:5])
        if len(pair_labels) > 5:
            campaign_label += f' 외 {len(pair_labels) - 5}개'
    elif campaign_ids:
        campaign_label = ', '.join(campaign_ids[:5])
        if len(campaign_ids) > 5:
            campaign_label += f' 외 {len(campaign_ids) - 5}개'
    else:
        campaign_label = ''
    journey_values = unique([*user_journey_ids, *user_journey_refs])
    if campaign_label:
        scope_kind = 'campaign'
        scope_label = f'캠페인 {campaign_label}'
    elif journey_values:
        scope_kind = 'user_journey'
        scope_label = f'유저여정 {", ".join(journey_values[:5])}'
        if len(journey_values) > 5:
            scope_label += f' 외 {len(journey_values) - 5}개'
    else:
        scope_kind = 'unknown'
        scope_label = '캠페인/유저여정 특정 불가'
    suffix = f" ({', '.join(common_scope)})" if common_scope else ''

    return {
        'required_final_field': f'범위: 프로젝트 {project_label} / {scope_label}{suffix}',
        'scope_kind': scope_kind,
        'scope_label': scope_label,
        'projects': projects or None,
        'dominant_current_projects': [
            {
                'project_id': item.get('project_id'),
                'focus_avg_load_sum': item.get('focus_avg_load_sum'),
                'focus_max_load': item.get('focus_max_load'),
                'table_families': item.get('table_families'),
            }
            for item in current_top_projects[:5]
        ] or None,
        'project_count': len(projects),
        'project_mapping_failures': [
            {
                'project_id': p.get('project_id'),
                'status': p.get('mapping_status'),
                'reason': p.get('mapping_failure_reason') or p.get('error'),
            }
            for p in projects
            if p.get('mapping_status') and p.get('mapping_status') != 'found'
        ],
        'campaign_ids': campaign_ids,
        'project_campaign_pairs': project_campaign_pairs,
        'user_journey_ids': user_journey_ids,
        'user_journey_refs': user_journey_refs,
        'service_indicators': service_indicators,
        'infra_indicators': infra_indicators,
        'metric': {'namespace': namespace, 'name': metric_name},
        'note': 'Final response must include this scope field. Campaign and user_journey are mutually exclusive; print exactly one when known. For RDS alerts, dominant_current_projects is the current alarm-window scope, not a broad historical list.',
    }

def project_ids_from_rds_performance_insights(pi_data: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(pi_data, dict):
        return []
    ids: List[str] = []
    scope = pi_data.get('detected_scope_ids') or {}
    current_top = scope.get('current_top_projects_by_load') or []
    source_projects = current_top[:3] if current_top else (scope.get('top_projects_by_load') or [])[:3]
    for item in source_projects:
        if isinstance(item, dict) and item.get('project_id'):
            ids.append(item['project_id'])
    if not ids:
        ids.extend((scope.get('project_ids') or [])[:3])
    for inst in pi_data.get('instances') or []:
        if ids:
            break
        if not isinstance(inst, dict):
            continue
        for sql in inst.get('top_sql') or []:
            if not isinstance(sql, dict):
                continue
            for ref in sql.get('table_refs') or []:
                if isinstance(ref, dict) and ref.get('project_id'):
                    ids.append(ref['project_id'])
    return unique(ids)

def project_campaign_pairs_from_logs(logs_insights: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(logs_insights, dict):
        return []
    pairs: List[Dict[str, Any]] = []
    current = logs_insights.get('current_project_campaign_pairs') or []
    recent = logs_insights.get('project_campaign_pairs') or []
    source_rows = current or recent
    seen = set()
    for pair in source_rows:
        if not isinstance(pair, dict):
            continue
        project_id = pair.get('project_id')
        campaign_id = pair.get('campaign_id')
        if not project_id or not campaign_id:
            continue
        key = (project_id, campaign_id)
        if key in seen:
            continue
        seen.add(key)
        out = {'project_id': project_id, 'campaign_id': campaign_id}
        if pair.get('count') is not None:
            out['count'] = pair.get('count')
        if current:
            out['scope_window'] = 'current_alarm_window'
        else:
            out['scope_window'] = 'recent_sample'
        pairs.append(out)
    return pairs

def merge_scope_detections(
    text: str,
    logs_insights: Optional[Dict[str, Any]],
    rds_performance_insights: Optional[Dict[str, Any]],
    initial_project_ids: Sequence[str],
    initial_campaign_ids: Sequence[str],
    initial_user_journey_ids: Sequence[str],
    initial_user_journey_refs: Sequence[str],
) -> Dict[str, Any]:
    project_campaign_pairs = project_campaign_pairs_from_logs(logs_insights)
    pair_project_ids = [pair['project_id'] for pair in project_campaign_pairs if pair.get('project_id')]
    pair_campaign_ids = [pair['campaign_id'] for pair in project_campaign_pairs if pair.get('campaign_id')]

    current_detail_text_parts: List[str] = []
    current_detail_project_ids: List[str] = []
    for detail in (logs_insights or {}).get('current_error_details') or []:
        if not isinstance(detail, dict):
            continue
        current_detail_project_ids.extend(detail.get('project_ids') or [])
        current_detail_text_parts.extend([
            str(detail.get('likely_error') or ''),
            str(detail.get('root_cause_hint') or ''),
            *[str(line) for line in detail.get('context_lines') or []],
            *[str(line) for line in detail.get('error_lines') or []],
        ])
    current_detail_text = '\n'.join(current_detail_text_parts)
    current_detail_campaign_ids = detect_campaign_ids(current_detail_text)
    rds_project_ids = project_ids_from_rds_performance_insights(rds_performance_insights)
    candidate_text = '\n'.join([text, json.dumps(logs_insights, ensure_ascii=False, default=str)])

    if current_detail_project_ids or pair_project_ids:
        project_ids = unique([*initial_project_ids, *current_detail_project_ids, *pair_project_ids, *rds_project_ids])
    else:
        project_ids = unique([*initial_project_ids, *detect_project_ids(candidate_text), *rds_project_ids])
    if current_detail_campaign_ids or pair_campaign_ids:
        campaign_ids = unique([*initial_campaign_ids, *current_detail_campaign_ids, *pair_campaign_ids])
    else:
        campaign_ids = unique([*initial_campaign_ids, *detect_campaign_ids(candidate_text)])

    return {
        'project_ids': project_ids,
        'campaign_ids': campaign_ids,
        'project_campaign_pairs': project_campaign_pairs,
        'user_journey_ids': unique([*initial_user_journey_ids, *detect_user_journey_ids(candidate_text)]),
        'user_journey_refs': unique([*initial_user_journey_refs, *detect_user_journey_refs(candidate_text)]),
    }

def collect_campaign_scope_hints(
    logs_insights: Optional[Dict[str, Any]],
    rds_performance_insights: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    detected = (logs_insights or {}).get('detected_scope_ids') or {}
    hints: Dict[str, Any] = {
        'detected_from_logs': {
            'project_ids': detected.get('project_ids') or [],
            'campaign_ids': detected.get('campaign_ids') or [],
            'current_project_campaign_pairs': detected.get('current_project_campaign_pairs') or [],
            'project_campaign_pairs': detected.get('project_campaign_pairs') or [],
            'user_journey_ids': detected.get('user_journey_ids') or [],
            'user_journey_refs': detected.get('user_journey_refs') or [],
        },
        'campaign_capable_db_tables': [],
        'read_only_aggregate_suggestions': [],
        'note': 'Use these hints to decide whether campaign or user_journey can be narrowed; run read-only Postgres/Athena aggregates when credentials/client support is available.',
    }
    pi_scope = (rds_performance_insights or {}).get('detected_scope_ids') or {}
    refs_by_project = pi_scope.get('table_refs_by_project') or {}
    for project_id, families in refs_by_project.items():
        capable = [
            family for family in families
            if any(str(family).startswith(prefix) for prefix in CAMPAIGN_CAPABLE_TABLE_PREFIXES)
        ]
        if not capable:
            continue
        hints['campaign_capable_db_tables'].append({
            'project_id': project_id,
            'table_families': capable,
        })
        for family in capable[:3]:
            if str(family).startswith(('delivery_result', 'message_events', 'scheduled_messages')):
                hints['read_only_aggregate_suggestions'].append({
                    'project_id': project_id,
                    'table_family': family,
                    'purpose': 'top campaign/resource contributors around alarm window',
                    'sql_shape': (
                        f'SELECT campaign_id, resource_type, count(*) FROM {family.replace("<project_id>", project_id)} '
                        "WHERE created_at BETWEEN <alarm_start> AND <alarm_end> "
                        'GROUP BY campaign_id, resource_type ORDER BY count(*) DESC LIMIT 10'
                    ),
                })
            elif 'user_journey' in str(family):
                hints['read_only_aggregate_suggestions'].append({
                    'project_id': project_id,
                    'table_family': family,
                    'purpose': 'top user_journey contributors around alarm window',
                    'sql_shape': (
                        f'SELECT user_journey_id, count(*) FROM {family.replace("<project_id>", project_id)} '
                        'GROUP BY user_journey_id ORDER BY count(*) DESC LIMIT 10'
                    ),
                })
    return hints
