from .common import *
from .text import normalize_ws

def detect_alarm_name(text: str, override: Optional[str]) -> Optional[str]:
    if override:
        return override
    patterns = [
        r'CloudWatch Alarm\s*\|\s*(.*?)\s*\|\s*[a-z]{2}-[a-z]+-\d\s*\|\s*Account',
        r'"AlarmName"\s*:\s*"([^"]+)"',
        r'AlarmName\s*[:=]\s*([^\n]+)',
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I | re.S)
        if m:
            return normalize_ws(m.group(1))
    return None

def detect_region(text: str, override: Optional[str]) -> str:
    if override:
        return override
    m = re.search(r'region=([a-z]{2}-[a-z]+-\d)', text)
    if m:
        return m.group(1)
    m = re.search(r'\|\s*([a-z]{2}-[a-z]+-\d)\s*\|\s*Account', text)
    if m:
        return m.group(1)
    m = re.search(r'\b([a-z]{2}-[a-z]+-\d)\b', text)
    if m:
        return m.group(1)
    return os.environ.get('AWS_DEFAULT_REGION', DEFAULT_AWS_REGION)

def detect_log_groups(text: str) -> List[str]:
    return unique(re.findall(r'/aws/[A-Za-z0-9._/\-]+', text))

def detect_project_ids(text: str) -> List[str]:
    """Extract project_ids from explicit key=value / JSON / log-style fields only.

    Sharded table-name suffixes (e.g. delivery_result_<id>) are intentionally
    excluded.  A project_id that appears only inside a
    "relation <table>_<id> does not exist" error message belongs to a
    deleted/absent table and must NOT be promoted to the primary alarm scope.
    Those IDs would produce a false scope attribution — the alarm that fired
    is unrelated to those deleted projects.

    Use detect_sharded_table_refs() separately when table-family attribution
    is explicitly needed.
    """
    patterns = [
        r'\bproject[_\s-]*id\b\s*[:=#-]?\s*[`"\']?([0-9a-f]{32})',
        r'\bprojectId\b\s*[:=#-]?\s*[`"\']?([0-9a-f]{32})',
        r'["\']project[_-]?id["\']\s*:\s*["\']([0-9a-f]{32})["\']',
        r'["\']projectId["\']\s*:\s*["\']([0-9a-f]{32})["\']',
    ]
    out: List[str] = []
    for pattern in patterns:
        out.extend(re.findall(pattern, text or '', flags=re.I))
    # NOTE: detect_sharded_table_refs() is intentionally NOT called here.
    return unique(out)

def detect_sharded_table_refs(text: str) -> List[Dict[str, str]]:
    refs: List[Dict[str, str]] = []
    for family, project_id in re.findall(r'\b([A-Za-z][A-Za-z0-9_]*?)_([0-9a-f]{32})\b', text or '', flags=re.I):
        refs.append({
            'table_family': family,
            'project_id': project_id,
            'table_pattern': f'{family}_<project_id>',
        })
    seen = set()
    out = []
    for ref in refs:
        key = (ref['table_family'], ref['project_id'])
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out

def detect_sharded_table_names(text: str) -> List[str]:
    return unique(re.findall(r'\b[A-Za-z][A-Za-z0-9_]*_[0-9a-f]{32}(?:_[A-Za-z0-9_]+)?\b', text or '', flags=re.I))

def detect_campaign_ids(text: str) -> List[str]:
    patterns = [
        r'\bcampaign[_\s-]*id\b\s*[:=#-]\s*[`"\']?([A-Za-z0-9_-]{3,64})',
        r'\bcampaignId\b\s*[:=#-]\s*[`"\']?([A-Za-z0-9_-]{3,64})',
        r'["\']campaign_id["\']\s*:\s*["\']([^"\']{3,64})["\']',
        r'["\']campaignId["\']\s*:\s*["\']([^"\']{3,64})["\']',
    ]
    out: List[str] = []
    for pattern in patterns:
        out.extend(re.findall(pattern, text, flags=re.I))
    noise = {'for', 'from', 'and', 'the', 'with', 'null', 'none', 'undefined', 'unknown'}
    return unique([item for item in out if item.lower() not in noise])

def detect_project_campaign_pairs(text: str) -> List[Dict[str, str]]:
    pairs: List[Dict[str, str]] = []
    patterns = [
        (
            r'\bproject[_\s-]*id\b\s*[:=#-]\s*[`"\']?([0-9a-f]{32})[`"\']?'
            r'[^\n\r]{0,1200}?\bcampaign[_\s-]*id\b\s*[:=#-]\s*[`"\']?([A-Za-z0-9_-]{3,64})'
        ),
        (
            r'\bcampaign[_\s-]*id\b\s*[:=#-]\s*[`"\']?([A-Za-z0-9_-]{3,64})[`"\']?'
            r'[^\n\r]{0,1200}?\bproject[_\s-]*id\b\s*[:=#-]\s*[`"\']?([0-9a-f]{32})'
        ),
        r'\bprojectId\b\s*[:=#-]\s*[`"\']?([0-9a-f]{32})[`"\']?[^\n\r]{0,1200}?\bcampaignId\b\s*[:=#-]\s*[`"\']?([A-Za-z0-9_-]{3,64})',
        r'\bcampaignId\b\s*[:=#-]\s*[`"\']?([A-Za-z0-9_-]{3,64})[`"\']?[^\n\r]{0,1200}?\bprojectId\b\s*[:=#-]\s*[`"\']?([0-9a-f]{32})',
        r'Project Id:\s*([0-9a-f]{32})[^\n\r]{0,1200}?Campaign Id:\s*([A-Za-z0-9_-]{3,64})',
        r'Campaign Id:\s*([A-Za-z0-9_-]{3,64})[^\n\r]{0,1200}?Project Id:\s*([0-9a-f]{32})',
        r'["\']project[_-]?id["\']\s*:\s*["\']([0-9a-f]{32})["\'][^\n\r]{0,1200}?["\']campaign[_-]?id["\']\s*:\s*["\']([A-Za-z0-9_-]{3,64})["\']',
        r'["\']campaign[_-]?id["\']\s*:\s*["\']([A-Za-z0-9_-]{3,64})["\'][^\n\r]{0,1200}?["\']project[_-]?id["\']\s*:\s*["\']([0-9a-f]{32})["\']',
    ]
    for idx, pattern in enumerate(patterns):
        for first, second in re.findall(pattern, text or '', flags=re.I | re.S):
            if idx in (0, 2, 4, 6):
                project_id, campaign_id = first, second
            else:
                campaign_id, project_id = first, second
            pairs.append({'project_id': project_id, 'campaign_id': campaign_id})
    seen = set()
    out = []
    for pair in pairs:
        key = (pair['project_id'], pair['campaign_id'])
        if key in seen:
            continue
        seen.add(key)
        out.append(pair)
    return out

def detect_user_journey_ids(text: str) -> List[str]:
    patterns = [
        r'\buser[_\s-]*journey[_\s-]*id\b\s*[:=#-]?\s*[`"\']?([A-Za-z0-9_-]{3,64})',
        r'\buserJourneyId\b\s*[:=#-]?\s*[`"\']?([A-Za-z0-9_-]{3,64})',
        r'["\']user_journey_id["\']\s*:\s*["\']([^"\']{3,64})["\']',
        r'["\']userJourneyId["\']\s*:\s*["\']([^"\']{3,64})["\']',
    ]
    out: List[str] = []
    for pattern in patterns:
        out.extend(re.findall(pattern, text, flags=re.I))
    return unique(out)

def detect_user_journey_refs(text: str) -> List[str]:
    refs = []
    for match in re.findall(r'\buser[_\s-]*journey[A-Za-z0-9_./-]*\b', text, flags=re.I):
        refs.append(match)
    for match in re.findall(r'\bjourney[_\s-]*(?:session|event|step|node)[A-Za-z0-9_./-]*\b', text, flags=re.I):
        refs.append(match)
    noise = {'user_journey_ids', 'user_journey_refs', 'user_journey_id'}
    return unique([ref for ref in refs if ref.lower() not in noise])

def detect_keywords(text: str) -> List[str]:
    low = text.lower()
    found = []
    for phrase in KNOWN_PHRASES:
        if phrase.lower() in low:
            found.append(phrase)
    return unique(found)

def detect_queue_names(text: str) -> List[str]:
    return unique(re.findall(r'\b[a-z0-9-]+(?:-queue(?:-dlq)?)\b', text))


def _nonnegative_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def parse_dlq_backlog_marker(text: str) -> Dict[str, Any]:
    """Parse one structured DLQ marker without retaining the raw log payload."""
    raw = str(text or '')
    marker_match = re.search(
        r'"eventType"\s*:\s*"('
        + '|'.join(re.escape(item) for item in sorted(DLQ_MARKER_EVENT_TYPES))
        + r')"',
        raw,
    )
    if not marker_match:
        if 'DLQ_BACKLOG_INSPECTION_FAILED' in raw:
            return {
                'marker_seen': True,
                'parse_issue': {
                    'type': 'inspection_failed',
                    'event_type': 'DLQ_BACKLOG_INSPECTION_FAILED',
                },
            }
        return {'marker_seen': False}

    event_type = marker_match.group(1)
    if len(raw.encode('utf-8')) > MAX_DLQ_MARKER_BYTES:
        return {
            'marker_seen': True,
            'parse_issue': {
                'type': 'oversized_marker',
                'event_type': event_type,
                'max_bytes': MAX_DLQ_MARKER_BYTES,
            },
        }

    object_starts = [
        match.start()
        for match in re.finditer(r'\{', raw[:marker_match.start() + 1])
    ]
    if not object_starts:
        return {
            'marker_seen': True,
            'parse_issue': {
                'type': 'missing_json_object',
                'event_type': event_type,
            },
        }

    payload = None
    decoder = json.JSONDecoder()
    for object_start in reversed(object_starts):
        try:
            candidate, consumed = decoder.raw_decode(raw[object_start:])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if (
            isinstance(candidate, dict)
            and candidate.get('eventType') == event_type
            and object_start <= marker_match.start() < object_start + consumed
        ):
            payload = candidate
            break
    if payload is None:
        return {
            'marker_seen': True,
            'parse_issue': {
                'type': 'malformed_json',
                'event_type': event_type,
            },
        }

    raw_queues = payload.get('queues')
    if event_type == 'DLQ_BACKLOG_DETECTED' and not isinstance(raw_queues, list):
        return {
            'marker_seen': True,
            'parse_issue': {
                'type': 'missing_queues',
                'event_type': event_type,
            },
        }
    if isinstance(raw_queues, list) and len(raw_queues) > MAX_DLQ_MARKER_QUEUES:
        return {
            'marker_seen': True,
            'parse_issue': {
                'type': 'too_many_queues',
                'event_type': event_type,
                'queue_count': len(raw_queues),
                'max_queues': MAX_DLQ_MARKER_QUEUES,
            },
        }

    queues: List[Dict[str, Any]] = []
    for raw_queue in raw_queues or []:
        if not isinstance(raw_queue, dict):
            continue
        queue_name = str(raw_queue.get('queueName') or '')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', queue_name):
            continue
        queue = {
            'queue_name': queue_name,
            'visible_message_count': _nonnegative_int(
                raw_queue.get('visibleMessageCount')
            ),
            'not_visible_message_count': _nonnegative_int(
                raw_queue.get('notVisibleMessageCount')
            ),
            'delayed_message_count': _nonnegative_int(
                raw_queue.get('delayedMessageCount')
            ),
            'message_count': _nonnegative_int(raw_queue.get('messageCount')),
            'message_retention_period_seconds': _nonnegative_int(
                raw_queue.get('messageRetentionPeriodSeconds')
            ),
        }
        queues.append(queue)

    if event_type == 'DLQ_BACKLOG_DETECTED' and not queues:
        return {
            'marker_seen': True,
            'parse_issue': {
                'type': 'no_valid_queues',
                'event_type': event_type,
            },
        }

    message_count = _nonnegative_int(payload.get('messageCount'))
    calculated_count = sum(
        queue.get('message_count')
        if queue.get('message_count') is not None
        else (
            (queue.get('visible_message_count') or 0)
            + (queue.get('not_visible_message_count') or 0)
            + (queue.get('delayed_message_count') or 0)
        )
        for queue in queues
    )
    return {
        'marker_seen': True,
        'event': {
            'event_type': event_type,
            'region': str(payload.get('region') or '') or None,
            'observed_at': str(payload.get('observedAt') or '') or None,
            'message_count': message_count,
            'calculated_message_count': calculated_count,
            'count_consistent': (
                message_count == calculated_count
                if message_count is not None
                else None
            ),
            'queue_count': len(queues),
            'queues': queues,
            'inspection_error': normalize_ws(
                str(payload.get('error') or payload.get('reason') or '')
            )[:360] or None,
        },
    }


def summarize_dlq_backlog_rows(
    rows: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    events: List[Dict[str, Any]] = []
    parse_issues: List[Dict[str, Any]] = []
    marker_seen = False
    for row in rows or []:
        message = row.get('@message') or row.get('message') or ''
        parsed = parse_dlq_backlog_marker(message)
        if not parsed.get('marker_seen'):
            continue
        marker_seen = True
        if parsed.get('event'):
            event = dict(parsed['event'])
            event['log_timestamp'] = (
                row.get('@timestamp') or row.get('timestamp') or None
            )
            events.append(event)
        elif parsed.get('parse_issue'):
            issue = dict(parsed['parse_issue'])
            issue['log_timestamp'] = (
                row.get('@timestamp') or row.get('timestamp') or None
            )
            parse_issues.append(issue)

    def event_sort_key(event: Dict[str, Any]) -> str:
        return str(event.get('observed_at') or event.get('log_timestamp') or '')

    events.sort(key=event_sort_key, reverse=True)
    snapshots = []
    for event in events:
        snapshots.append(tuple(
            (
                queue.get('queue_name'),
                queue.get('message_count'),
                queue.get('visible_message_count'),
                queue.get('not_visible_message_count'),
                queue.get('delayed_message_count'),
            )
            for queue in event.get('queues') or []
        ))
    latest_snapshot = snapshots[0] if snapshots else None
    return {
        'marker_seen': marker_seen,
        'event_count_in_sample': len(events),
        'latest_event': events[0] if events else None,
        'first_observed_at_in_sample': (
            events[-1].get('observed_at') or events[-1].get('log_timestamp')
            if events else None
        ),
        'last_observed_at_in_sample': (
            events[0].get('observed_at') or events[0].get('log_timestamp')
            if events else None
        ),
        'same_as_latest_count': (
            sum(1 for snapshot in snapshots if snapshot == latest_snapshot)
            if latest_snapshot is not None
            else 0
        ),
        'distinct_snapshot_count': len(set(snapshots)),
        'parse_issues': parse_issues[:3],
    }


def detect_service_names(text: str) -> List[str]:
    services = []
    patterns = [
        r'\[([A-Za-z0-9][A-Za-z0-9_.-]{2,80})\]\s+(?:4xx|5xx|error|errors|latency|timeout|slow)\b',
        r'\bservice(?:name)?\b\s*[:=#]\s*[`"\']?([A-Za-z0-9][A-Za-z0-9_.-]{2,80})',
    ]
    for pattern in patterns:
        services.extend(re.findall(pattern, text or '', flags=re.I))
    return unique(services)

def service_names_from_log_groups(log_groups: Sequence[str]) -> List[str]:
    services = []
    for group in log_groups or []:
        parts = [part for part in str(group).split('/') if part]
        if len(parts) >= 4 and parts[:2] == ['aws', 'ecs']:
            services.append(parts[-1])
        elif len(parts) >= 3 and parts[:2] == ['aws', 'lambda']:
            services.append(parts[-1])
    return unique(services)

def detect_lambda_names(text: str, log_groups: Sequence[str], alarm: Optional[Dict[str, Any]]) -> List[str]:
    names: List[str] = []
    for group in log_groups or []:
        m = re.search(r'^/aws/lambda/([A-Za-z0-9-_]+)', group)
        if m:
            names.append(m.group(1))
    if isinstance(alarm, dict):
        names.extend(alarm_dimension_value(alarm, ['FunctionName']))
    patterns = [
        r'\b([a-z0-9][a-z0-9-]{2,})\s+lambda\s+(?:error|errors|latency|timeout)\b',
        r'\blambda\s+(?:function(?:name)?|name)\b\s*[:=#]\s*[`"\']?([A-Za-z0-9-_]{3,80})',
        r'\bfunction(?:name)?\b\s*[:=#]\s*[`"\']?([A-Za-z0-9-_]{3,80})',
    ]
    for pattern in patterns:
        names.extend(re.findall(pattern, text or '', flags=re.I))
    return unique(names)

def alarm_dimension_value(alarm: Any, names: Sequence[str]) -> List[str]:
    if not isinstance(alarm, dict):
        return []
    dims = alarm.get('Dimensions') or []
    out = []
    wanted = {name.lower() for name in names}
    for dim in dims:
        if not isinstance(dim, dict):
            continue
        name = str(dim.get('Name') or '').lower()
        value = str(dim.get('Value') or '')
        if name in wanted and value:
            out.append(value)
    return unique(out)


def detect_payment_product_names(text):
    """Extract product/customer names from payment executor log lines.

    Matches patterns like:
      - "Amount of recurrent payment for HONGIN:"
      - "Executing pay-as-you-go payment for zippoom..."
      - "Failed to execute payment for choihome:"
    """
    products = []
    pattern = re.compile(
        r'\b(?:Amount|Executing|Failed to execute)(?:\s+\w+)*?\s+payment\s+for\s+([A-Za-z0-9_-]{2,40})',
        re.I,
    )
    for match in pattern.finditer(text or ''):
        products.append(match.group(1))
    return unique(products)
