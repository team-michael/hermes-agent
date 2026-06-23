from .common import *
from .text import (
    normalize_ws, truncate, sanitize_error, sanitize_log_line, log_signature,
    logs_insights_regex, logs_insights_string, metric_filter_terms, logs_result_dict,
    looks_like_low_signal_log,
)
from .detect import (
    detect_project_ids, detect_campaign_ids, detect_project_campaign_pairs,
    detect_sharded_table_refs, detect_sharded_table_names, detect_user_journey_ids,
    detect_user_journey_refs,
)
from .aws_collectors import parse_datetime, parse_log_timestamp

def describe_metric_filters(session, log_groups: Sequence[str], alarm: Optional[Dict[str, Any]], keywords: Sequence[str]) -> Optional[List[Dict[str, Any]]]:
    if session is None:
        return None
    logs = session.client('logs')
    alarm_name = (alarm or {}).get('AlarmName', '') if isinstance(alarm, dict) else ''
    metric_name = (alarm or {}).get('MetricName', '') if isinstance(alarm, dict) else ''
    metric_namespace = (alarm or {}).get('Namespace', '') if isinstance(alarm, dict) else ''
    matches: List[Dict[str, Any]] = []
    seen = set()
    tokens = [t.lower() for t in [alarm_name, metric_name, *keywords] if t]

    def add_filter(mf: Dict[str, Any], group_hint: Optional[str] = None, match_type: str = 'related') -> None:
        group = mf.get('logGroupName') or group_hint
        key = (group, mf.get('filterName'))
        if key in seen:
            return
        seen.add(key)
        matches.append({
            'log_group': group,
            'filter_name': mf.get('filterName'),
            'filter_pattern': truncate(mf.get('filterPattern') or '', 500),
            'metric_names': [mt.get('metricName') for mt in mf.get('metricTransformations') or []],
            'metric_namespaces': [mt.get('metricNamespace') for mt in mf.get('metricTransformations') or []],
            'match_type': match_type,
        })

    if metric_name and metric_namespace:
        try:
            paginator = logs.get_paginator('describe_metric_filters')
            for page in paginator.paginate(metricName=metric_name, metricNamespace=metric_namespace):
                for mf in page.get('metricFilters') or []:
                    add_filter(mf, match_type='primary_metric')
                    if len(matches) >= 20:
                        return matches
        except Exception as e:
            matches.append({'metric_name': metric_name, 'metric_namespace': metric_namespace, 'error': str(e)})

    for group in unique(log_groups):
        try:
            paginator = logs.get_paginator('describe_metric_filters')
            for page in paginator.paginate(logGroupName=group):
                for mf in page.get('metricFilters') or []:
                    hay = ' '.join([
                        mf.get('filterName', ''),
                        mf.get('filterPattern', ''),
                        ' '.join(mt.get('metricName', '') for mt in mf.get('metricTransformations') or []),
                    ]).lower()
                    if not tokens or any(tok in hay for tok in tokens):
                        add_filter(mf, group_hint=group, match_type='related_same_log_group')
        except Exception as e:
            matches.append({'log_group': group, 'error': str(e)})
    return matches[:20]

def infer_log_groups(log_groups: Sequence[str], metric_filters: Optional[Sequence[Dict[str, Any]]]) -> List[str]:
    groups = list(log_groups or [])
    for mf in metric_filters or []:
        group = mf.get('log_group') if isinstance(mf, dict) else None
        if group:
            groups.append(group)
    return unique(groups)[:MAX_LOG_QUERY_GROUPS]

def build_log_filter_terms(
    text: str,
    alarm: Optional[Dict[str, Any]],
    keywords: Sequence[str],
    metric_filters: Optional[Sequence[Dict[str, Any]]],
) -> List[str]:
    primary_terms: List[str] = []
    related_terms: List[str] = []
    for mf in metric_filters or []:
        if not isinstance(mf, dict):
            continue
        pattern = mf.get('filter_pattern') or ''
        extracted = metric_filter_terms(pattern)
        if mf.get('match_type') == 'primary_metric':
            primary_terms.extend(extracted)
        else:
            related_terms.extend(extracted)
    primary_patterns = [
        (mf.get('filter_pattern') or '') for mf in metric_filters or []
        if isinstance(mf, dict) and mf.get('match_type') == 'primary_metric'
    ]
    has_ci_markers = any(
        bool(re.search(r'\[[A-Za-z]{2,}\]', pat))
        for pat in primary_patterns
    )
    prefix = 'ci:' if has_ci_markers else 'cs:'
    if primary_terms:
        return [f'{prefix}{t}' for t in unique([t for t in primary_terms if len(normalize_ws(t)) >= 3])[:6]]

    terms: List[str] = []
    terms.extend(f'ci:{term}' for term in re.findall(r'(?i)(?:error|exception|timeout|crossslot|slow [a-z0-9 _-]{4,80}|processing took longer than expected)', text))
    if not terms:
        terms.extend(f'cs:{term}' for term in related_terms)
    if not terms and isinstance(alarm, dict):
        metric_name = str(alarm.get('MetricName') or '')
        if re.search(r'(?i)(error|exception|timeout|fail|slow)', metric_name):
            terms.append(f'ci:{metric_name}')
    return unique([t for t in terms if len(normalize_ws(t[3:] if t.startswith(("cs:", "ci:")) else t)) >= 4])[:6]

def logs_filter_clause(terms: Sequence[str]) -> str:
    clauses = []
    for term in terms:
        mode = 'ci'
        raw = term
        if term.startswith('cs:'):
            mode = 'cs'
            raw = term[3:]
        elif term.startswith('ci:'):
            raw = term[3:]
        regex = logs_insights_regex(raw)
        if not regex:
            continue
        prefix = '' if mode == 'cs' else '(?i)'
        clauses.append(f'@message like /{prefix}{regex}/')
    if not clauses:
        return '| filter @message not like /"_aws"/'
    return '| filter @message not like /"_aws"/\n| filter ' + ' or '.join(clauses)

def display_filter_terms(terms: Sequence[str]) -> List[str]:
    out = []
    for term in terms:
        if term.startswith(('cs:', 'ci:')):
            out.append(term[3:])
        else:
            out.append(term)
    return out

def _run_logs_insights_query(
    session,
    query: str,
    start: datetime,
    end: datetime,
    limit: int,
    max_wait_seconds: int,
    *,
    log_group: Optional[str] = None,
    log_groups: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    if session is None:
        return {'skipped': 'missing aws session'}
    if not log_group and not log_groups:
        return {'skipped': 'missing log group(s)'}
    logs = session.client('logs')
    kwargs: Dict[str, Any] = {
        'startTime': int(start.timestamp()),
        'endTime': int(end.timestamp()),
        'queryString': query,
        'limit': limit,
    }
    if log_group:
        kwargs['logGroupName'] = log_group
    else:
        kwargs['logGroupNames'] = list(log_groups or [])[:MAX_LOG_QUERY_GROUPS]
    try:
        resp = logs.start_query(**kwargs)
        query_id = resp['queryId']
        deadline = time.time() + max_wait_seconds
        while time.time() < deadline:
            result = logs.get_query_results(queryId=query_id)
            status = result.get('status')
            if status in ('Complete', 'Failed', 'Cancelled', 'Timeout', 'Unknown'):
                return {
                    'status': status,
                    'statistics': result.get('statistics'),
                    'rows': [logs_result_dict(row) for row in result.get('results') or []],
                }
            time.sleep(1.0)
        try:
            logs.stop_query(queryId=query_id)
        except Exception:
            pass
        return {'status': 'Timeout', 'error': f'query exceeded {max_wait_seconds}s'}
    except Exception as e:
        return {'status': 'Error', 'error': str(e), 'query': query}

def run_logs_insights_query(
    session,
    log_groups: Sequence[str],
    query: str,
    days: int,
    limit: int = 1000,
    max_wait_seconds: int = 35,
) -> Dict[str, Any]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    return _run_logs_insights_query(
        session,
        query,
        start,
        end,
        limit,
        max_wait_seconds,
        log_groups=log_groups,
    )

def run_logs_insights_query_window(
    session,
    log_group: str,
    query: str,
    start: datetime,
    end: datetime,
    limit: int = 100,
    max_wait_seconds: int = 20,
) -> Dict[str, Any]:
    return _run_logs_insights_query(
        session,
        query,
        start,
        end,
        limit,
        max_wait_seconds,
        log_group=log_group,
    )

def run_logs_insights_query_window_groups(
    session,
    log_groups: Sequence[str],
    query: str,
    start: datetime,
    end: datetime,
    limit: int = 100,
    max_wait_seconds: int = 25,
) -> Dict[str, Any]:
    return _run_logs_insights_query(
        session,
        query,
        start,
        end,
        limit,
        max_wait_seconds,
        log_groups=log_groups,
    )

def _comparison_is_breaching(value: Any, threshold: Any, operator: str) -> bool:
    try:
        value_f = float(value)
        threshold_f = float(threshold)
    except Exception:
        return value is not None
    op = str(operator or '')
    if op == 'GreaterThanOrEqualToThreshold':
        return value_f >= threshold_f
    if op == 'GreaterThanThreshold':
        return value_f > threshold_f
    if op == 'LessThanOrEqualToThreshold':
        return value_f <= threshold_f
    if op == 'LessThanThreshold':
        return value_f < threshold_f
    return True


def _state_reason_datapoint_window(alarm: Optional[Dict[str, Any]], history: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    latest = (history or {}).get('latest_alarm_transition') or {}
    reason_data = latest.get('state_reason_data')
    if not isinstance(reason_data, dict):
        return None
    try:
        period = int(reason_data.get('period') or (alarm or {}).get('Period') or 60)
    except Exception:
        period = 60
    period = max(1, period)
    threshold = reason_data.get('threshold')
    if threshold is None and isinstance(alarm, dict):
        threshold = alarm.get('Threshold')
    operator = (alarm or {}).get('ComparisonOperator') if isinstance(alarm, dict) else None
    datapoints = reason_data.get('evaluatedDatapoints') or []
    parsed: List[datetime] = []
    for datapoint in datapoints:
        if not isinstance(datapoint, dict):
            continue
        ts = parse_datetime(datapoint.get('timestamp'))
        if not ts:
            continue
        if datapoint.get('value') is None or _comparison_is_breaching(datapoint.get('value'), threshold, operator or ''):
            parsed.append(ts)
    if not parsed:
        start = parse_datetime(reason_data.get('startDate'))
        if start:
            parsed.append(start)
    if not parsed:
        return None
    start = min(parsed)
    end = max(parsed) + timedelta(seconds=period)
    return {
        'basis': 'latest_alarm_state_reason_data',
        'alarm_transition_time': latest.get('timestamp'),
        'start': start.isoformat(),
        'end': end.isoformat(),
        'datapoint_period_seconds': period,
        'evaluated_datapoints': [ts.isoformat() for ts in sorted(parsed)],
    }


def alarm_trigger_window(alarm: Optional[Dict[str, Any]], history: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    state_window = _state_reason_datapoint_window(alarm, history)
    if state_window:
        return state_window

    anchor = parse_datetime(((history or {}).get('latest_alarm_transition') or {}).get('timestamp'))
    basis = 'latest_alarm_transition'
    if anchor is None and isinstance(alarm, dict) and alarm.get('StateValue') == 'ALARM':
        anchor = parse_datetime(alarm.get('StateUpdatedTimestamp'))
        basis = 'current_alarm_state_updated'
    if anchor is None:
        return None

    period = 300
    evaluation_periods = 1
    if isinstance(alarm, dict):
        try:
            period = int(alarm.get('Period') or period)
        except Exception:
            pass
        try:
            evaluation_periods = int(alarm.get('EvaluationPeriods') or evaluation_periods)
        except Exception:
            pass
    lookback_seconds = max(15 * 60, period * max(1, evaluation_periods + 1) * 2)
    after_seconds = max(5 * 60, period)
    start = anchor - timedelta(seconds=lookback_seconds)
    end = anchor + timedelta(seconds=after_seconds)
    return {
        'basis': basis,
        'alarm_transition_time': anchor.isoformat(),
        'start': start.isoformat(),
        'end': end.isoformat(),
        'lookback_seconds': lookback_seconds,
        'after_seconds': after_seconds,
    }

def row_log_group(row: Dict[str, str], fallback_groups: Sequence[str]) -> Optional[str]:
    raw = row.get('@log') or ''
    if raw and ':' in raw:
        return raw.split(':', 1)[1]
    return fallback_groups[0] if fallback_groups else None

ERROR_OBJECT_PROPERTY_RE = re.compile(
    r"^\s*(?:length|severity|code|detail|hint|position|internalPosition|"
    r"internalQuery|where|schema|table|column|dataType|constraint|file|"
    r"line|routine):\s",
    re.I,
)
USEFUL_ERROR_OBJECT_PROPERTY_RE = re.compile(
    r"^\s*(?:code|detail|where|schema|table|constraint|file|routine):\s",
    re.I,
)
GENERIC_ERROR_PROPERTY_RE = re.compile(r"^\s*severity:\s*['\"]?ERROR['\"]?,?\s*$", re.I)
STACK_FRAME_RE = re.compile(r'^\s*at\s+.+(?:/app/|node_modules|\.js:|\.ts:)', re.I)
SENSITIVE_CONTEXT_RE = re.compile(r'(?i)^(params|values):\s')
QUERY_CONTEXT_RE = re.compile(r'(?i)^(query|sql|statement):\s')

def is_sensitive_context_line(message: str) -> bool:
    return bool(SENSITIVE_CONTEXT_RE.match(normalize_ws(message)))

def is_generic_error_property_line(message: str) -> bool:
    text = normalize_ws(message)
    return text in {'ERROR', 'Error'} or bool(GENERIC_ERROR_PROPERTY_RE.match(text))

def is_error_object_property_line(message: str) -> bool:
    return bool(ERROR_OBJECT_PROPERTY_RE.match(normalize_ws(message)))

def is_useful_error_object_property_line(message: str) -> bool:
    return bool(USEFUL_ERROR_OBJECT_PROPERTY_RE.match(normalize_ws(message)))

def is_stack_frame_line(message: str) -> bool:
    return bool(STACK_FRAME_RE.match(normalize_ws(message)))

def error_context_score(message: str) -> int:
    line = normalize_ws(message)
    if not line:
        return 1000
    if looks_like_low_signal_log(line):
        return 900
    if is_generic_error_property_line(line):
        return 800
    low = line.lower()
    if any(token in low for token in ['failed', 'duplicate key', 'violates unique constraint', 'exception']):
        return 0
    if any(token in low for token in ['error from', 'timeout', 'timed out', 'denied', 'rejected', 'deadlock']):
        return 1
    if is_useful_error_object_property_line(line):
        return 2
    if QUERY_CONTEXT_RE.match(line):
        return 3
    if any(pattern.search(line) for pattern in ERROR_CONTEXT_PATTERNS):
        return 10
    if is_stack_frame_line(line):
        return 30
    if is_error_object_property_line(line):
        return 60
    return 100

def locate_trigger_index(ordered: Sequence[Dict[str, Any]], trigger_ms: int, trigger_message: str) -> int:
    trigger_norm = normalize_ws(trigger_message)
    exact = [
        idx for idx, event in enumerate(ordered)
        if trigger_norm and normalize_ws(event.get('message') or '') == trigger_norm
    ]
    if exact:
        return min(exact, key=lambda idx: abs(int(ordered[idx].get('timestamp') or 0) - trigger_ms))
    return min(
        range(len(ordered)),
        key=lambda idx: abs(int(ordered[idx].get('timestamp') or 0) - trigger_ms),
    )

def choose_error_context_anchor_index(
    ordered: Sequence[Dict[str, Any]],
    center: int,
    radius: int,
) -> int:
    start = max(0, center - radius)
    end = min(len(ordered), center + radius + 1)
    ranked = []
    for idx in range(start, end):
        message = ordered[idx].get('message') or ''
        score = error_context_score(message)
        if score >= 900:
            continue
        ranked.append((score, abs(idx - center), idx))
    if not ranked:
        return center
    best_score, _, best_idx = min(ranked)
    center_score = error_context_score(ordered[center].get('message') or '')
    if center_score >= 700 and best_score < center_score:
        return best_idx
    return center

def fetch_log_stream_context_events(
    session,
    log_group: str,
    log_stream: str,
    trigger_ms: int,
    before_seconds: int = 5,
    after_seconds: int = 5,
    max_events: int = 1000,
) -> Dict[str, Any]:
    if session is None:
        return {'skipped': 'missing aws session', 'events': []}
    try:
        logs = session.client('logs')
        start_ms = max(0, trigger_ms - before_seconds * 1000)
        end_ms = trigger_ms + after_seconds * 1000 + 1
        events: List[Dict[str, Any]] = []
        next_token = None
        while len(events) < max_events:
            kwargs: Dict[str, Any] = {
                'logGroupName': log_group,
                'logStreamName': log_stream,
                'startTime': start_ms,
                'endTime': end_ms,
                'startFromHead': True,
                'limit': min(10000, max_events - len(events)),
            }
            if next_token:
                kwargs['nextToken'] = next_token
            resp = logs.get_log_events(**kwargs)
            for event in resp.get('events') or []:
                events.append({
                    'timestamp': int(event.get('timestamp') or 0),
                    'message': event.get('message') or '',
                })
                if len(events) >= max_events:
                    break
            token = resp.get('nextForwardToken')
            if not token or token == next_token:
                break
            next_token = token
        return {'status': 'Complete', 'events': events}
    except Exception as e:
        return {'status': 'Error', 'error': sanitize_error(e), 'events': []}

def compact_error_blocks(
    events: Sequence[Dict[str, Any]],
    trigger_ms: int,
    trigger_message: str,
    radius: int = 24,
    limit: int = 24,
) -> List[Dict[str, Any]]:
    if not events:
        return []
    ordered = sorted(events, key=lambda event: int(event.get('timestamp') or 0))
    center = locate_trigger_index(ordered, trigger_ms, trigger_message)
    anchor = choose_error_context_anchor_index(ordered, center, radius)
    window = ordered[max(0, anchor - radius):anchor + radius + 1]
    lines: List[str] = []
    omitted_low_signal = 0
    for event in window:
        message = event.get('message') or ''
        if not normalize_ws(message):
            continue
        if looks_like_low_signal_log(message):
            omitted_low_signal += 1
            continue
        if is_sensitive_context_line(message):
            continue
        score = error_context_score(message)
        is_detail = any(pattern.search(message) for pattern in ERROR_DETAIL_PATTERNS)
        is_context = any(pattern.search(message) for pattern in ERROR_CONTEXT_PATTERNS)
        if score > 60 and not is_detail and not is_context:
            continue
        line = sanitize_log_line(message, limit=420)
        if line and line not in lines:
            lines.append(line)
        if len(lines) >= limit:
            break
    if not lines or all(is_generic_error_property_line(line) for line in lines):
        return []
    return [{
        'anchor': sanitize_log_line(ordered[anchor].get('message') or '', limit=360),
        'lines': lines,
        'omitted_low_signal_lines': omitted_low_signal,
    }]

def centered_log_context_lines(
    events: Sequence[Dict[str, Any]],
    trigger_ms: int,
    trigger_message: str,
    radius: int = 20,
    limit: int = 32,
) -> Dict[str, Any]:
    if not events:
        return {'lines': [], 'omitted_low_signal_lines': 0}

    ordered = sorted(events, key=lambda event: int(event.get('timestamp') or 0))
    trigger_norm = normalize_ws(trigger_message)
    original_center = locate_trigger_index(ordered, trigger_ms, trigger_message)
    center = choose_error_context_anchor_index(ordered, original_center, radius)

    window = ordered[max(0, center - radius):center + radius + 1]
    lines = []
    omitted_low_signal = 0
    for event in window:
        message = event.get('message') or ''
        if not normalize_ws(message):
            continue
        is_trigger = trigger_norm and normalize_ws(message) == trigger_norm
        if is_sensitive_context_line(message):
            continue
        if looks_like_low_signal_log(message) and not is_trigger:
            omitted_low_signal += 1
            continue
        lines.append(sanitize_log_line(message, limit=360 if is_trigger else 260))
        if len(lines) >= limit:
            break

    if not lines and trigger_message:
        lines.append(sanitize_log_line(trigger_message, limit=360))
    return {
        'lines': lines,
        'omitted_low_signal_lines': omitted_low_signal,
        'anchor_line': sanitize_log_line(ordered[center].get('message') or '', limit=360),
        'anchor_shifted': center != original_center,
    }

def collect_surrounding_log_contexts(
    session,
    groups: Sequence[str],
    sample_rows: Sequence[Dict[str, str]],
    max_contexts: int = 3,
) -> List[Dict[str, Any]]:
    if session is None:
        return []
    contexts = []
    seen = set()
    for row in sample_rows:
        if len(contexts) >= max_contexts:
            break
        stream = row.get('@logStream')
        ts = parse_log_timestamp(row.get('@timestamp'))
        group = row_log_group(row, groups)
        if not stream or not ts or not group:
            continue
        key = (group, stream, int(ts.timestamp()))
        if key in seen:
            continue
        seen.add(key)
        try:
            trigger_ms = int(ts.timestamp() * 1000)
            trigger_message = row.get('@message') or row.get('message') or ''
            stream_context = fetch_log_stream_context_events(session, group, stream, trigger_ms)
            events = stream_context.get('events') or []
            context_status = stream_context.get('status') or stream_context.get('skipped')
            if not events:
                context_query = f"""
fields @timestamp, @message
| filter @logStream = {logs_insights_string(stream)}
| filter @message not like /"_aws"/
| sort @timestamp asc
| limit 80
""".strip()
                context = run_logs_insights_query_window(
                    session,
                    group,
                    context_query,
                    start=ts - timedelta(seconds=60),
                    end=ts + timedelta(seconds=60),
                    limit=80,
                )
                context_status = context.get('status') or context.get('skipped')
                for ctx_row in context.get('rows') or []:
                    ctx_ts = parse_log_timestamp(ctx_row.get('@timestamp'))
                    if not ctx_ts:
                        continue
                    events.append({
                        'timestamp': int(ctx_ts.timestamp() * 1000),
                        'message': ctx_row.get('@message') or ctx_row.get('message') or '',
                    })
            centered = centered_log_context_lines(events, trigger_ms, trigger_message)
            error_blocks = compact_error_blocks(events, trigger_ms, trigger_message)
            # SCOPE FIX: Only analyze the trigger message for project_ids, not entire log stream.
            # Log streams mix multiple invocations; other invocations' project_ids should not
            # be attributed to the current trigger unless they explicitly appear in the trigger
            # line itself or in explicit project_campaign_pairs.
            raw_scope_source = trigger_message
            contexts.append({
                'timestamp': ts.isoformat(),
                'log_group': group,
                'log_stream': stream,
                'trigger': sanitize_log_line(trigger_message),
                'surrounding_lines': centered['lines'],
                'error_blocks': error_blocks,
                'context_anchor': centered.get('anchor_line'),
                'context_anchor_shifted': centered.get('anchor_shifted'),
                'project_ids': detect_project_ids(raw_scope_source)[:10],
                'project_campaign_pairs': detect_project_campaign_pairs(raw_scope_source)[:10],
                'table_refs': detect_sharded_table_refs(raw_scope_source)[:10],
                'omitted_low_signal_lines': centered['omitted_low_signal_lines'],
                'context_query_status': context_status,
            })
        except Exception as e:
            contexts.append({
                'timestamp': ts.isoformat(),
                'log_group': group,
                'log_stream': stream,
                'error': sanitize_error(e),
            })
    return contexts

def current_error_details_from_contexts(
    contexts: Sequence[Dict[str, Any]],
    max_details: int = 3,
) -> List[Dict[str, Any]]:
    """Extract compact, actionable error context from trigger-centered logs."""
    def stable_detail_line(line: str) -> str:
        table_names = detect_sharded_table_names(line)
        if line.lower().startswith('query:') and table_names:
            return 'Query references table(s): ' + ', '.join(table_names)
        return line

    def error_priority(line: str) -> int:
        low = line.lower()
        if any(token in low for token in ['failed', 'duplicate key', 'violates unique', 'exception', 'typeerror', 'referenceerror']):
            return 0
        if any(token in low for token in ['timeout', 'denied', 'rejected', 'error from', 'statuscode', 'errorcode', 'resultcode']):
            return 1
        if 'constraint' in low:
            return 2
        if low.startswith('query:') or low.startswith('query references table'):
            return 3
        return 4

    details: List[Dict[str, Any]] = []
    low_signal = {
        "severity: 'ERROR',",
        'ERROR',
        'Error',
    }
    for ctx in contexts or []:
        if len(details) >= max_details:
            break
        signal_lines: List[str] = []
        context_lines: List[str] = []
        detail_source_lines: List[str] = []
        raw_detail_source_lines: List[str] = []
        seen = set()
        block_lines = [
            line
            for block in ctx.get('error_blocks') or []
            if isinstance(block, dict)
            for line in block.get('lines') or []
        ]
        for raw in [*block_lines, ctx.get('trigger'), *(ctx.get('surrounding_lines') or [])]:
            raw_line = str(raw or '')
            if raw_line:
                raw_detail_source_lines.append(raw_line)
            line = sanitize_log_line(raw_line, limit=360)
            if not line or line in low_signal or line in seen:
                continue
            if re.match(r'(?i)^(params|values):\s', line):
                continue
            is_signal = (
                any(pattern.search(line) for pattern in ERROR_DETAIL_PATTERNS)
                or is_useful_error_object_property_line(line)
            )
            is_context = any(pattern.search(line) for pattern in ERROR_CONTEXT_PATTERNS)
            line = stable_detail_line(line)
            if '...' in line:
                continue
            if line in seen:
                continue
            seen.add(line)
            detail_source_lines.append(line)
            if is_signal:
                signal_lines.append(line)
            elif is_context:
                context_lines.append(line)
        trigger_line = sanitize_log_line(str(ctx.get('trigger') or ''), limit=360)
        concrete_trigger = bool(trigger_line) and error_context_score(trigger_line) < 700
        if concrete_trigger and not signal_lines:
            trigger_pairs = merge_project_campaign_pairs([
                *detect_project_campaign_pairs(trigger_line),
                *(ctx.get('project_campaign_pairs') or []),
            ])
            trigger_table_refs = [
                *detect_sharded_table_refs(trigger_line),
                *[
                    ref for ref in (ctx.get('table_refs') or [])
                    if isinstance(ref, dict)
                ],
            ]
            details.append({
                'timestamp': ctx.get('timestamp'),
                'log_group': ctx.get('log_group'),
                'log_stream': ctx.get('log_stream'),
                'trigger': ctx.get('trigger'),
                'likely_error': trigger_line,
                'project_ids': unique([
                    *detect_project_ids(trigger_line),
                    *(ctx.get('project_ids') or []),
                    *[pair['project_id'] for pair in trigger_pairs],
                ]),
                'project_campaign_pairs': trigger_pairs,
                'table_names': detect_sharded_table_names(trigger_line),
                'table_refs': trigger_table_refs,
                'context_lines': [],
                'error_lines': [],
                'root_cause_hint': trigger_line,
            })
            continue
        if not signal_lines and not context_lines:
            continue
        ranked_signal_lines = sorted(signal_lines, key=error_priority)
        likely_error = ranked_signal_lines[0] if ranked_signal_lines else context_lines[0]
        hint_parts = []
        if context_lines:
            hint_parts.append(context_lines[0])
        if ranked_signal_lines:
            hint_parts.append(ranked_signal_lines[0])
        detail_source = '\n'.join(detail_source_lines)
        raw_detail_source = '\n'.join(raw_detail_source_lines)
        project_campaign_pairs = merge_project_campaign_pairs([
            *detect_project_campaign_pairs(raw_detail_source),
            *(ctx.get('project_campaign_pairs') or []),
        ])
        explicit_project_ids = unique([
            *detect_project_ids(raw_detail_source),
            *(ctx.get('project_ids') or []),
        ])
        table_refs = detect_sharded_table_refs(raw_detail_source)
        table_refs = [
            *table_refs,
            *[
                ref for ref in (ctx.get('table_refs') or [])
                if isinstance(ref, dict)
            ],
        ]
        details.append({
            'timestamp': ctx.get('timestamp'),
            'log_group': ctx.get('log_group'),
            'log_stream': ctx.get('log_stream'),
            'trigger': ctx.get('trigger'),
            'likely_error': likely_error,
            'project_ids': unique([
                *explicit_project_ids,
                *[pair['project_id'] for pair in project_campaign_pairs],
            ]),
            'project_campaign_pairs': project_campaign_pairs,
            'table_names': detect_sharded_table_names(raw_detail_source),
            'table_refs': table_refs,
            'context_lines': context_lines[:4],
            'error_lines': ranked_signal_lines[:5],
            'root_cause_hint': truncate(' | '.join(hint_parts), 420),
        })
    return details

def parse_count_rows(rows: Sequence[Dict[str, str]]) -> int:
    total = 0
    for row in rows:
        for key in ('count', 'c', 'count()'):
            value = row.get(key)
            if value is not None:
                try:
                    total += int(float(value))
                except Exception:
                    pass
                break
    return total

def top_log_signatures(rows: Sequence[Dict[str, str]], limit: int = 5) -> List[Dict[str, Any]]:
    signature_counts: Counter[str] = Counter()
    signature_samples: Dict[str, List[str]] = {}
    for row in rows or []:
        message = row.get('@message') or row.get('message') or ''
        sig = log_signature(message)
        if not sig:
            continue
        signature_counts[sig] += 1
        signature_samples.setdefault(sig, [])
        if len(signature_samples[sig]) < MAX_LOG_SAMPLES_PER_SIGNATURE:
            signature_samples[sig].append(sanitize_log_line(message))
    return [
        {
            'signature': sig,
            'count_in_sample': count,
            'sample_lines': signature_samples.get(sig, [])[:MAX_LOG_SAMPLES_PER_SIGNATURE],
        }
        for sig, count in signature_counts.most_common(limit)
    ]

def project_campaign_pair_counts(rows: Sequence[Dict[str, str]], limit: int = 20) -> List[Dict[str, Any]]:
    counts: Counter[tuple[str, str]] = Counter()
    for row in rows or []:
        message = row.get('@message') or row.get('message') or ''
        for pair in detect_project_campaign_pairs(message):
            counts[(pair['project_id'], pair['campaign_id'])] += 1
    return [
        {'project_id': project_id, 'campaign_id': campaign_id, 'count': count}
        for (project_id, campaign_id), count in counts.most_common(limit)
    ]

def merge_project_campaign_pairs(pairs: Sequence[Dict[str, Any]], limit: int = 20) -> List[Dict[str, Any]]:
    merged: Dict[tuple[str, str], Dict[str, Any]] = {}
    for pair in pairs or []:
        if not isinstance(pair, dict):
            continue
        project_id = pair.get('project_id')
        campaign_id = pair.get('campaign_id')
        if not project_id or not campaign_id:
            continue
        key = (str(project_id), str(campaign_id))
        item = merged.setdefault(key, {'project_id': key[0], 'campaign_id': key[1], 'count': 0})
        item['count'] += int(pair.get('count') or 1)
    return sorted(merged.values(), key=lambda item: item.get('count', 0), reverse=True)[:limit]

def collect_logs_insights_summary(
    session,
    log_groups: Sequence[str],
    text: str,
    alarm: Optional[Dict[str, Any]],
    keywords: Sequence[str],
    metric_filters: Optional[Sequence[Dict[str, Any]]],
    history: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    groups = infer_log_groups(log_groups, metric_filters)
    if session is None or not groups:
        return None
    terms = build_log_filter_terms(text, alarm, keywords, metric_filters)
    if not terms:
        return {
            'log_groups': groups,
            'skipped': 'no stable filter terms inferred; refusing broad 30d log scan',
        }
    filter_clause = logs_filter_clause(terms)
    # Vetted query templates only. Do not build ad-hoc Logs Insights syntax in the LLM loop.
    count_query = f"""
fields @timestamp, @message
{filter_clause}
| stats count() as count
""".strip()
    daily_query = f"""
fields @timestamp, @message
{filter_clause}
| stats count() as count by bin(1d)
""".strip()
    sample_query = f"""
fields @timestamp, @message, @logStream, @log
{filter_clause}
| sort @timestamp desc
| limit {MAX_LOG_EVENTS}
""".strip()

    count_7d = run_logs_insights_query(session, groups, count_query, days=7, limit=1)
    count_30d = run_logs_insights_query(session, groups, count_query, days=30, limit=1)
    daily_30d = run_logs_insights_query(session, groups, daily_query, days=30, limit=40)
    samples = run_logs_insights_query(session, groups, sample_query, days=7, limit=MAX_LOG_EVENTS)
    recent_rows = samples.get('rows') or []
    recent_trigger_contexts = collect_surrounding_log_contexts(session, groups, recent_rows)

    current_alarm_window = alarm_trigger_window(alarm, history)
    current_samples: Dict[str, Any] = {}
    current_rows: List[Dict[str, str]] = []
    current_trigger_contexts: List[Dict[str, Any]] = []
    if current_alarm_window:
        window_start = parse_datetime(current_alarm_window.get('start'))
        window_end = parse_datetime(current_alarm_window.get('end'))
        if window_start and window_end:
            current_sample_query = f"""
fields @timestamp, @message, @logStream, @log
{filter_clause}
| sort @timestamp desc
| limit {MAX_LOG_EVENTS}
""".strip()
            current_samples = run_logs_insights_query_window_groups(
                session,
                groups,
                current_sample_query,
                start=window_start,
                end=window_end,
                limit=MAX_LOG_EVENTS,
            )
            current_rows = current_samples.get('rows') or []
            current_trigger_contexts = collect_surrounding_log_contexts(session, groups, current_rows)

    detected_project_ids: List[str] = []
    detected_campaign_ids: List[str] = []
    detected_user_journey_ids: List[str] = []
    detected_user_journey_refs: List[str] = []
    for row in current_rows:
        message = row.get('@message') or row.get('message') or ''
        detected_project_ids.extend(detect_project_ids(message))
        detected_campaign_ids.extend(detect_campaign_ids(message))
        detected_user_journey_ids.extend(detect_user_journey_ids(message))
        detected_user_journey_refs.extend(detect_user_journey_refs(message))

    top_signatures = top_log_signatures(recent_rows)
    for item in top_signatures:
        item['count_in_recent_sample'] = item.pop('count_in_sample')
    current_top_signatures = top_log_signatures(current_rows)
    for item in current_top_signatures:
        item['count_in_current_alarm_window'] = item.pop('count_in_sample')
    current_error_details = current_error_details_from_contexts(current_trigger_contexts)
    current_detail_project_campaign_pairs = [
        pair
        for detail in current_error_details
        if isinstance(detail, dict)
        for pair in detail.get('project_campaign_pairs') or []
    ]
    current_row_project_campaign_pairs = project_campaign_pair_counts(current_rows)
    current_project_campaign_pairs = (
        current_row_project_campaign_pairs
        or merge_project_campaign_pairs(current_detail_project_campaign_pairs)
    )
    recent_project_campaign_pairs = project_campaign_pair_counts(recent_rows)
    daily_rows = daily_30d.get('rows') or []
    compact_daily = []
    for row in daily_rows[:35]:
        day = row.get('bin(1d)') or row.get('@timestamp') or row.get('timestamp') or row.get('date')
        count = row.get('count') or row.get('c') or row.get('count()')
        compact_daily.append({'day': day, 'count': count})

    return {
        'log_groups': groups,
        'filter_terms': display_filter_terms(terms),
        'count_7d': parse_count_rows(count_7d.get('rows') or []),
        'count_30d': parse_count_rows(count_30d.get('rows') or []),
        'daily_counts_30d': compact_daily,
        'current_alarm_window': current_alarm_window,
        'current_top_signatures': current_top_signatures,
        'current_trigger_contexts': current_trigger_contexts,
        'current_error_details': current_error_details,
        'current_project_campaign_pairs': current_project_campaign_pairs,
        'project_campaign_pairs': recent_project_campaign_pairs,
        'top_signatures': top_signatures,
        'trigger_contexts': current_trigger_contexts,
        'recent_trigger_contexts': recent_trigger_contexts,
        'detected_scope_ids': {
            'project_ids': unique(detected_project_ids)[:10],
            'campaign_ids': unique(detected_campaign_ids)[:10],
            'current_project_campaign_pairs': current_project_campaign_pairs[:10],
            'project_campaign_pairs': recent_project_campaign_pairs[:10],
            'user_journey_ids': unique(detected_user_journey_ids)[:10],
            'user_journey_refs': unique(detected_user_journey_refs)[:10],
        },
        'query_status': {
            'count_7d': count_7d.get('status'),
            'count_30d': count_30d.get('status'),
            'daily_30d': daily_30d.get('status'),
            'samples': samples.get('status'),
            'current_samples': current_samples.get('status') if current_samples else None,
        },
        'errors': unique([sanitize_error(x.get('error')) for x in (count_7d, count_30d, daily_30d, samples, current_samples) if x.get('error')]),
    }
