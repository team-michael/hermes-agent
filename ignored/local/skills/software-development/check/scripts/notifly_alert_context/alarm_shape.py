from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

from .config import DB_ALARM_NAME_TOKENS


TOKEN_SPLIT = re.compile(r'[^a-z0-9]+')
NAMESPACE_PATTERN = re.compile(r'''SCHEMA\(["']?([^,"')]+)''')
METRIC_PATTERN = re.compile(
    r'(?i)\b(MAX|MIN|SUM|AVG|AVERAGE)\s*\('
    r'\s*([A-Za-z][A-Za-z0-9_]*)\s*\)'
)
CLUSTER_PATTERN = re.compile(
    r'''(?i)(?:tag\.)?DBClusterIdentifier\s*=\s*["']([^"']+)["']'''
)
INSTANCE_PATTERN = re.compile(
    r'''(?i)DBInstanceIdentifier\s*=\s*["']([^"']+)["']'''
)
HERMES_INSTANCE_PATTERN = re.compile(
    r'''(?i)InstanceId\s*=\s*["']([^"']+)["']'''
)


def _append_unique(items: List[str], value: Any) -> None:
    text = str(value or '').strip()
    if text and text not in items:
        items.append(text)


def _dimension_values(
    dimensions: Sequence[Dict[str, Any]],
    name: str,
) -> List[str]:
    values: List[str] = []
    for dimension in dimensions:
        if not isinstance(dimension, dict) or dimension.get('Name') != name:
            continue
        _append_unique(values, dimension.get('Value'))
    return values


def _empty_shape(status: str) -> Dict[str, Any]:
    return {
        'status': status,
        'namespaces': [],
        'metric_names': [],
        'dimension_names': [],
        'expressions': [],
        'dimensionless_lambda': False,
        'hermes_profile_status': False,
        'hermes_instance_ids': [],
        'db_relevance': {
            'level': 'none',
            'evidence': [],
            'explicit_cluster_ids': [],
            'explicit_instance_ids': [],
        },
    }


def classify_alarm_shape(
    alarm: Any,
    *,
    text: str = '',
    service_names: Sequence[str] = (),
) -> Dict[str, Any]:
    del text  # Free-form alert text is deliberately not used for classification.
    if not isinstance(alarm, dict) or alarm.get('error'):
        return _empty_shape('unavailable')

    result = _empty_shape('classified')
    namespaces: List[str] = result['namespaces']
    metric_names: List[str] = result['metric_names']
    dimension_names: List[str] = result['dimension_names']
    expressions: List[str] = result['expressions']
    cluster_ids: List[str] = result['db_relevance']['explicit_cluster_ids']
    instance_ids: List[str] = result['db_relevance']['explicit_instance_ids']
    hermes_instance_ids: List[str] = result['hermes_instance_ids']

    _append_unique(namespaces, alarm.get('Namespace'))
    _append_unique(metric_names, alarm.get('MetricName'))
    top_dimensions = [
        item for item in alarm.get('Dimensions') or [] if isinstance(item, dict)
    ]

    all_dimensions = list(top_dimensions)
    for query in alarm.get('Metrics') or []:
        if not isinstance(query, dict):
            continue
        expression = str(query.get('Expression') or '').strip()
        if expression:
            _append_unique(expressions, expression)
            for match in NAMESPACE_PATTERN.finditer(expression):
                _append_unique(namespaces, match.group(1))
            for match in METRIC_PATTERN.finditer(expression):
                _append_unique(metric_names, match.group(2))
            for match in CLUSTER_PATTERN.finditer(expression):
                _append_unique(cluster_ids, match.group(1))
            for match in INSTANCE_PATTERN.finditer(expression):
                _append_unique(instance_ids, match.group(1))
            for match in HERMES_INSTANCE_PATTERN.finditer(expression):
                _append_unique(hermes_instance_ids, match.group(1))

        metric = (query.get('MetricStat') or {}).get('Metric') or {}
        if isinstance(metric, dict):
            _append_unique(namespaces, metric.get('Namespace'))
            _append_unique(metric_names, metric.get('MetricName'))
            all_dimensions.extend([
                item
                for item in metric.get('Dimensions') or []
                if isinstance(item, dict)
            ])

    for dimension in all_dimensions:
        _append_unique(dimension_names, dimension.get('Name'))
    for value in _dimension_values(all_dimensions, 'DBClusterIdentifier'):
        _append_unique(cluster_ids, value)
    for value in _dimension_values(all_dimensions, 'DBInstanceIdentifier'):
        _append_unique(instance_ids, value)
    for value in _dimension_values(all_dimensions, 'InstanceId'):
        _append_unique(hermes_instance_ids, value)

    namespace_lower = {namespace.lower() for namespace in namespaces}
    dimension_lower = {name.lower() for name in dimension_names}
    direct_rds = bool(
        'aws/rds' in namespace_lower
        or {'dbclusteridentifier', 'dbinstanceidentifier'} & dimension_lower
        or cluster_ids
        or instance_ids
    )
    evidence: List[str] = result['db_relevance']['evidence']
    if 'aws/rds' in namespace_lower:
        evidence.append('namespace:AWS/RDS')
    if cluster_ids:
        evidence.append('dimension_or_expression:DBClusterIdentifier')
    if instance_ids:
        evidence.append('dimension_or_expression:DBInstanceIdentifier')

    name_tokens = TOKEN_SPLIT.split(str(alarm.get('AlarmName') or '').lower())
    service_tokens = [
        token
        for service in service_names
        for token in TOKEN_SPLIT.split(str(service).lower())
        if token
    ]
    matched_tokens = sorted(
        DB_ALARM_NAME_TOKENS.intersection([*name_tokens, *service_tokens])
    )
    if direct_rds:
        result['db_relevance']['level'] = 'confirmed'
    elif matched_tokens:
        result['db_relevance']['level'] = 'candidate'
        evidence.extend(f'alarm_or_service_token:{token}' for token in matched_tokens)

    result['dimensionless_lambda'] = bool(
        'aws/lambda' in namespace_lower
        and 'functionname' not in dimension_lower
        and not any('FunctionName' in expression for expression in expressions)
    )
    result['hermes_profile_status'] = 'HermesProfileStatus' in metric_names
    return result
