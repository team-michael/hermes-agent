from .common import *
from .text import normalize_ws, sanitize_error, sanitize_sql_statement
from .detect import alarm_dimension_value, detect_sharded_table_refs

def build_aws_session(region: str):
    if boto3 is None:
        return None
    if not os.environ.get('AWS_ACCESS_KEY_ID') or not os.environ.get('AWS_SECRET_ACCESS_KEY'):
        return None
    return boto3.Session(
        aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
        region_name=region,
    )

def call_sts(session) -> Optional[Dict[str, Any]]:
    if session is None:
        return None
    try:
        ident = session.client('sts').get_caller_identity()
        return {'account': ident.get('Account'), 'arn': ident.get('Arn')}
    except Exception as e:
        return {'error': str(e)}

def describe_alarm(session, alarm_name: Optional[str]) -> Optional[Dict[str, Any]]:
    if session is None or not alarm_name:
        return None
    cw = session.client('cloudwatch')
    try:
        resp = cw.describe_alarms(AlarmNames=[alarm_name])
        for bucket in ('MetricAlarms', 'CompositeAlarms'):
            items = resp.get(bucket) or []
            if items:
                item = items[0]
                item['_alarm_type'] = bucket[:-1]
                return item
        # fallback: prefix search
        resp = cw.describe_alarms(AlarmNamePrefix=alarm_name[:255])
        for bucket in ('MetricAlarms', 'CompositeAlarms'):
            items = resp.get(bucket) or []
            if items:
                item = items[0]
                item['_alarm_type'] = bucket[:-1]
                return item
        return None
    except Exception as e:
        return {'error': str(e)}

def collect_alarm_history(session, alarm_name: Optional[str], days: int) -> Optional[Dict[str, Any]]:
    if session is None or not alarm_name:
        return None
    cw = session.client('cloudwatch')
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    seven_day_start = now - timedelta(days=7)
    one_day_start = now - timedelta(days=1)
    summaries: List[str] = []
    by_type_lookback: Counter[str] = Counter()
    by_type_7d: Counter[str] = Counter()
    alarm_transitions_lookback: Counter[str] = Counter()
    alarm_transitions_7d: Counter[str] = Counter()
    alarm_transitions_1d: Counter[str] = Counter()
    alarm_daily_lookback: Counter[str] = Counter()
    items_out: List[Dict[str, Any]] = []
    latest_alarm_transition: Optional[Dict[str, Any]] = None
    latest_alarm_ts: Optional[datetime] = None
    alarm_transition_times: List[datetime] = []
    next_token = None
    try:
        while True:
            kwargs: Dict[str, Any] = {
                'AlarmName': alarm_name,
                'StartDate': start,
                'MaxRecords': 100,
            }
            if next_token:
                kwargs['NextToken'] = next_token
            resp = cw.describe_alarm_history(**kwargs)
            items = resp.get('AlarmHistoryItems') or []
            for item in items:
                hist_type = item.get('HistoryItemType') or 'Unknown'
                by_type_lookback[hist_type] += 1
                ts = item.get('Timestamp')
                if isinstance(ts, datetime) and ts >= seven_day_start:
                    by_type_7d[hist_type] += 1
                summary = normalize_ws(item.get('HistorySummary', ''))
                if summary:
                    summaries.append(summary)
                new_state = None
                try:
                    data = json.loads(item.get('HistoryData') or '{}')
                    new_state = (
                        data.get('newState', {}).get('stateValue')
                        or data.get('stateUpdate', {}).get('stateValue')
                    )
                except Exception:
                    new_state = None
                if not new_state and 'to ALARM' in summary:
                    new_state = 'ALARM'
                if new_state:
                    alarm_transitions_lookback[new_state] += 1
                    if isinstance(ts, datetime):
                        alarm_daily_lookback[ts.date().isoformat()] += 1 if new_state == 'ALARM' else 0
                        if ts >= seven_day_start:
                            alarm_transitions_7d[new_state] += 1
                        if ts >= one_day_start:
                            alarm_transitions_1d[new_state] += 1
                if len(items_out) < 12:
                    items_out.append({
                        'timestamp': str(item.get('Timestamp')),
                        'type': hist_type,
                        'new_state': new_state,
                        'summary': summary,
                    })
                if new_state == 'ALARM' and isinstance(ts, datetime):
                    alarm_transition_times.append(ts)
                    if latest_alarm_ts is None or ts > latest_alarm_ts:
                        latest_alarm_ts = ts
                        latest_alarm_transition = {
                            'timestamp': ts.isoformat(),
                            'type': hist_type,
                            'summary': summary,
                        }
            next_token = resp.get('NextToken')
            if not next_token or len(items_out) >= 12 and sum(by_type_lookback.values()) >= 300:
                break
        alarm_transition_times = sorted(alarm_transition_times, reverse=True)
        rapid_recurrence: Dict[str, Any] = {'status': 'not_applicable'}
        if latest_alarm_ts:
            previous_alarms = [ts for ts in alarm_transition_times if ts < latest_alarm_ts]
            previous_ts = previous_alarms[0] if previous_alarms else None
            recurrence_tolerance_seconds = 1.0
            previous_delta_seconds = (
                (latest_alarm_ts - previous_ts).total_seconds()
                if previous_ts else None
            )
            minutes_since_previous = (
                round(previous_delta_seconds / 60, 2)
                if previous_delta_seconds is not None else None
            )

            def count_alarms_within(minutes: int) -> int:
                limit_seconds = minutes * 60 + recurrence_tolerance_seconds
                return sum(
                    1
                    for ts in alarm_transition_times
                    if 0 <= (latest_alarm_ts - ts).total_seconds() <= limit_seconds
                )

            rapid_recurrence = {
                'status': 'rapid' if previous_delta_seconds is not None and previous_delta_seconds <= 10 * 60 + recurrence_tolerance_seconds else 'normal',
                'latest_alarm_time': latest_alarm_ts.isoformat(),
                'previous_alarm_time': previous_ts.isoformat() if previous_ts else None,
                'minutes_since_previous_alarm': minutes_since_previous,
                'alarm_count_within_10m': count_alarms_within(10),
                'alarm_count_within_30m': count_alarms_within(30),
                'recent_alarm_times': [ts.isoformat() for ts in alarm_transition_times[:8]],
            }
        return {
            'lookback_days': days,
            'counts_by_type_7d': dict(by_type_7d),
            'counts_by_type_lookback': dict(by_type_lookback),
            'state_transitions_7d': dict(alarm_transitions_7d),
            'state_transitions_1d': dict(alarm_transitions_1d),
            'state_transitions_lookback': dict(alarm_transitions_lookback),
            'alarm_count_7d': int(alarm_transitions_7d.get('ALARM', 0)),
            'alarm_count_1d': int(alarm_transitions_1d.get('ALARM', 0)),
            'alarm_count_10m': rapid_recurrence.get('alarm_count_within_10m'),
            'alarm_count_lookback': int(alarm_transitions_lookback.get('ALARM', 0)),
            'alarm_daily_counts': dict(sorted((k, v) for k, v in alarm_daily_lookback.items() if v)),
            'top_summaries': Counter(summaries).most_common(8),
            'sample_items': items_out[:12],
            'latest_alarm_transition': latest_alarm_transition,
            'rapid_recurrence': rapid_recurrence,
        }
    except Exception as e:
        return {'error': str(e)}

def summarize_alarm(alarm: Dict[str, Any]) -> Dict[str, Any]:
    if 'error' in alarm:
        return alarm
    keys = [
        'AlarmName', 'StateValue', 'StateReason', 'StateUpdatedTimestamp', 'Namespace',
        'MetricName', 'Threshold', 'ComparisonOperator', 'EvaluationPeriods',
        'DatapointsToAlarm', 'Period', 'Statistic', 'TreatMissingData', 'Dimensions'
    ]
    out = {k: alarm.get(k) for k in keys if k in alarm}
    out['_alarm_type'] = alarm.get('_alarm_type')
    return out

def metric_statistics_summary(
    session,
    namespace: str,
    metric_name: str,
    dimensions: Sequence[Dict[str, Any]],
    stat: str,
    days: int = 7,
    period_hint: int = 300,
    threshold: Any = None,
    comparison_operator: Any = None,
) -> Optional[Dict[str, Any]]:
    if session is None or not namespace or not metric_name:
        return None
    stat = stat or 'Average'
    alarm_period = int(period_hint or 300)
    window_seconds = max(1, days) * 24 * 60 * 60
    min_period = max(60, (window_seconds + 1439) // 1440)
    if min_period % 60:
        min_period = ((min_period // 60) + 1) * 60
    period = max(alarm_period, min_period)
    now = datetime.now(timezone.utc)
    kwargs: Dict[str, Any] = {
        'Namespace': namespace,
        'MetricName': metric_name,
        'Dimensions': list(dimensions or []),
        'StartTime': now - timedelta(days=days),
        'EndTime': now,
        'Period': period,
    }
    if str(stat).startswith('p'):
        kwargs['ExtendedStatistics'] = [stat]
    else:
        kwargs['Statistics'] = [stat]
    try:
        resp = session.client('cloudwatch').get_metric_statistics(**kwargs)
        datapoints = sorted(resp.get('Datapoints') or [], key=lambda d: d.get('Timestamp'))
        def point_value(dp: Dict[str, Any]) -> Optional[float]:
            if str(stat).startswith('p'):
                value = (dp.get('ExtendedStatistics') or {}).get(stat)
            else:
                value = dp.get(stat)
            return value if isinstance(value, (int, float)) else None

        values = [v for v in (point_value(dp) for dp in datapoints) if v is not None]
        recent_points = [
            {
                'timestamp': str(dp.get('Timestamp')),
                'value': point_value(dp),
            }
            for dp in datapoints[-12:]
        ]
        summary: Dict[str, Any] = {
            'days': days,
            'statistic': stat,
            'period': period,
            'datapoint_count': len(datapoints),
            'threshold': threshold,
            'comparison_operator': comparison_operator,
            'recent_points': recent_points,
        }
        if values:
            summary.update({
                'min': min(values),
                'max': max(values),
                'avg': sum(values) / len(values),
                'latest': values[-1],
            })
        return summary
    except Exception as e:
        return {'error': str(e)}

def collect_metric_datapoints(session, alarm: Optional[Dict[str, Any]], days: int = 7) -> Optional[Dict[str, Any]]:
    if session is None or not alarm or 'error' in alarm:
        return None
    if alarm.get('_alarm_type') != 'MetricAlarm':
        return None
    if alarm.get('Metrics'):
        return {'note': 'metric math alarm; inspect Alarm summary Metrics manually'}
    namespace = alarm.get('Namespace')
    metric_name = alarm.get('MetricName')
    if not namespace or not metric_name:
        return None
    stat = alarm.get('Statistic') or alarm.get('ExtendedStatistic') or 'Average'
    return metric_statistics_summary(
        session,
        namespace,
        metric_name,
        alarm.get('Dimensions') or [],
        stat,
        days=days,
        period_hint=int(alarm.get('Period') or 300),
        threshold=alarm.get('Threshold'),
        comparison_operator=alarm.get('ComparisonOperator'),
    )

def collect_5xx_metrics(session, alarm: Optional[Dict[str, Any]], days: int = 7) -> Optional[Dict[str, Any]]:
    if session is None or not alarm or 'error' in alarm:
        return None
    namespace = alarm.get('Namespace')
    dimensions = alarm.get('Dimensions') or []
    dim_names = {str(d.get('Name') or '').lower() for d in dimensions if isinstance(d, dict)}
    dim_values = {str(d.get('Value') or '').lower() for d in dimensions if isinstance(d, dict)}
    candidates: List[tuple[str, str, Sequence[Dict[str, Any]]]] = []
    if namespace == 'AWS/ApplicationELB':
        candidates.extend([
            ('HTTPCode_Target_5XX_Count', 'Sum', dimensions),
            ('HTTPCode_ELB_5XX_Count', 'Sum', dimensions),
        ])
    elif namespace == 'AWS/ApiGateway':
        candidates.append(('5XXError', 'Sum', dimensions))
    elif namespace == 'AWS/CloudFront':
        candidates.append(('5xxErrorRate', 'Average', dimensions))
    elif '5xx' in str(alarm.get('MetricName', '')).lower():
        candidates.append((str(alarm.get('MetricName')), alarm.get('Statistic') or 'Sum', dimensions))
    elif (
        namespace
        and {'statuscode', 'status_code', 'status', 'httpstatus', 'http_status'} & dim_names
        and any(re.search(r'(^5|5xx|50\d)', value) for value in dim_values)
    ):
        candidates.append((str(alarm.get('MetricName') or 'RequestCount'), alarm.get('Statistic') or 'Sum', dimensions))

    if not candidates:
        return {'status': 'not_applicable', 'reason': 'no 5xx metric family inferred from alarm namespace/dimensions'}

    out = []
    for metric_name, stat, dims in candidates[:4]:
        summary = metric_statistics_summary(
            session,
            namespace,
            metric_name,
            dims,
            stat,
            days=days,
            period_hint=int(alarm.get('Period') or 300),
        )
        out.append({'namespace': namespace, 'metric_name': metric_name, 'summary': summary})
    return {'days': days, 'metrics': out}

def collect_http_context(session, alarm: Optional[Dict[str, Any]], text: str, days: int = 7) -> Optional[Dict[str, Any]]:
    if session is None or not alarm or 'error' in alarm:
        return None
    namespace = alarm.get('Namespace')
    dimensions = alarm.get('Dimensions') or []
    alarm_name = str(alarm.get('AlarmName') or '')
    metric_name = str(alarm.get('MetricName') or '')
    dim_names = {str(d.get('Name') or '').lower() for d in dimensions if isinstance(d, dict)}
    http_dim_names = {
        'statuscode', 'status_code', 'status', 'httpstatus', 'http_status',
        'path', 'route', 'resource', 'normalizedpath', 'method',
        'targetgroup', 'loadbalancer', 'api', 'stage',
    }
    low = f'{alarm_name} {metric_name} {text}'.lower()
    if not (
        any(token in low for token in ['4xx', '4x', '5xx', '5x', 'httpcode', 'error response'])
        or bool(http_dim_names & dim_names)
        or namespace in {'AWS/ApplicationELB', 'AWS/ApiGateway', 'AWS/CloudFront'}
    ):
        return {'status': 'not_applicable', 'reason': 'no HTTP 4xx/5xx signal inferred from alarm text/metric'}

    candidates: List[tuple[str, str, Sequence[Dict[str, Any]]]] = []
    if namespace == 'AWS/ApplicationELB':
        candidates.extend([
            ('HTTPCode_Target_4XX_Count', 'Sum', dimensions),
            ('HTTPCode_ELB_4XX_Count', 'Sum', dimensions),
            ('HTTPCode_Target_5XX_Count', 'Sum', dimensions),
            ('HTTPCode_ELB_5XX_Count', 'Sum', dimensions),
            ('RequestCount', 'Sum', dimensions),
        ])
    elif namespace == 'AWS/ApiGateway':
        candidates.extend([
            ('4XXError', 'Sum', dimensions),
            ('5XXError', 'Sum', dimensions),
            ('Count', 'Sum', dimensions),
            ('Latency', 'Average', dimensions),
        ])
    elif namespace == 'AWS/CloudFront':
        candidates.extend([
            ('4xxErrorRate', 'Average', dimensions),
            ('5xxErrorRate', 'Average', dimensions),
            ('Requests', 'Sum', dimensions),
        ])
    if re.search(r'(?i)(4xx|5xx|4x|5x|http)', metric_name):
        candidates.insert(0, (metric_name, alarm.get('Statistic') or 'Sum', dimensions))
    if http_dim_names & dim_names:
        candidates.extend([
            (metric_name or 'RequestCount', alarm.get('Statistic') or 'Sum', dimensions),
            ('RequestCount', 'Sum', dimensions),
            ('RequestDuration', 'Average', dimensions),
            ('Latency', 'Average', dimensions),
        ])

    out = []
    seen = set()
    for candidate_metric, stat, dims in candidates[:8]:
        key = (namespace, candidate_metric, stat)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            'namespace': namespace,
            'metric_name': candidate_metric,
            'statistic': stat,
            'summary': metric_statistics_summary(
                session,
                namespace,
                candidate_metric,
                dims,
                stat,
                days=days,
                period_hint=int(alarm.get('Period') or 300),
                threshold=alarm.get('Threshold') if candidate_metric == metric_name else None,
                comparison_operator=alarm.get('ComparisonOperator') if candidate_metric == metric_name else None,
            ),
        })
    return {
        'days': days,
        'status': 'collected' if out else 'no_metric_candidates',
        'metrics': out,
        'note': 'For route/status-code root cause, pair this with Logs Insights or access-log/Athena aggregates when available.',
    }

def collect_queue_metric(session, queue_name: str, metric_name: str, stat: str, days: int = 7) -> Dict[str, Any]:
    return {
        'metric_name': metric_name,
        'statistic': stat,
        'summary': metric_statistics_summary(
            session,
            'AWS/SQS',
            metric_name,
            [{'Name': 'QueueName', 'Value': queue_name}],
            stat,
            days=days,
            period_hint=300,
        ),
    }

def queue_main_guesses(queue_name: str) -> List[str]:
    guesses = []
    if queue_name.endswith('-dlq'):
        guesses.append(queue_name[:-4])
    if queue_name.endswith('-queue-dlq'):
        guesses.append(queue_name[:-4])
    return unique(guesses)

def sqs_queue_summary(sqs, queue_name: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {'queue_name': queue_name}
    try:
        url = sqs.get_queue_url(QueueName=queue_name).get('QueueUrl')
        out['queue_url_tail'] = url.rsplit('/', 1)[-1] if url else None
        attrs = sqs.get_queue_attributes(
            QueueUrl=url,
            AttributeNames=[
                'ApproximateNumberOfMessages',
                'ApproximateNumberOfMessagesNotVisible',
                'ApproximateNumberOfMessagesDelayed',
                'RedrivePolicy',
                'VisibilityTimeout',
                'MessageRetentionPeriod',
                'CreatedTimestamp',
                'LastModifiedTimestamp',
            ],
        ).get('Attributes') or {}
        if attrs.get('RedrivePolicy'):
            try:
                attrs['RedrivePolicy'] = json.loads(attrs['RedrivePolicy'])
            except Exception:
                pass
        out['attributes'] = attrs
        try:
            sources = sqs.list_dead_letter_source_queues(QueueUrl=url, MaxResults=10).get('queueUrls') or []
            out['dead_letter_source_queues'] = [src.rsplit('/', 1)[-1] for src in sources]
        except Exception as e:
            out['dead_letter_source_queues_error'] = sanitize_error(e)
    except Exception as e:
        out['error'] = sanitize_error(e)
    return out

def collect_sqs_context(session, alarm: Optional[Dict[str, Any]], queue_names: Sequence[str], days: int = 7) -> Optional[Dict[str, Any]]:
    if session is None:
        return None
    names = list(queue_names or [])
    if isinstance(alarm, dict):
        names.extend(alarm_dimension_value(alarm, ['QueueName']))
    names = unique(names)[:MAX_CONTEXT_ITEMS]
    if not names:
        return None
    sqs = session.client('sqs')
    queues = []
    for name in names:
        related = unique([name, *queue_main_guesses(name)])[:3]
        queue_rows = []
        for queue_name in related:
            row = sqs_queue_summary(sqs, queue_name)
            row['metrics'] = [
                collect_queue_metric(session, queue_name, 'ApproximateNumberOfMessagesVisible', 'Maximum', days),
                collect_queue_metric(session, queue_name, 'ApproximateAgeOfOldestMessage', 'Maximum', days),
                collect_queue_metric(session, queue_name, 'ApproximateNumberOfMessagesNotVisible', 'Maximum', days),
                collect_queue_metric(session, queue_name, 'NumberOfMessagesSent', 'Sum', days),
                collect_queue_metric(session, queue_name, 'NumberOfMessagesDeleted', 'Sum', days),
            ]
            queue_rows.append(row)
        queues.append({'detected_queue': name, 'related_queues': queue_rows})
    return {
        'days': days,
        'queues': queues,
        'note': 'DLQ payload sampling is intentionally not performed here because receive_message changes message visibility.',
    }

def collect_lambda_context(session, alarm: Optional[Dict[str, Any]], lambda_names: Sequence[str], days: int = 7) -> Optional[Dict[str, Any]]:
    if session is None or not lambda_names:
        return None
    lambda_client = session.client('lambda')
    rows = []
    for name in unique(lambda_names)[:MAX_CONTEXT_ITEMS]:
        row: Dict[str, Any] = {'function_name': name}
        try:
            cfg = lambda_client.get_function_configuration(FunctionName=name)
            row['configuration'] = {
                'function_name': cfg.get('FunctionName'),
                'runtime': cfg.get('Runtime'),
                'handler': cfg.get('Handler'),
                'memory_size': cfg.get('MemorySize'),
                'timeout': cfg.get('Timeout'),
                'last_modified': cfg.get('LastModified'),
                'state': cfg.get('State'),
                'package_type': cfg.get('PackageType'),
                'architectures': cfg.get('Architectures'),
                'layers': [layer.get('Arn') for layer in cfg.get('Layers') or []],
            }
        except Exception as e:
            row['configuration_error'] = sanitize_error(e)
        try:
            mappings = lambda_client.list_event_source_mappings(FunctionName=name, MaxItems=10).get('EventSourceMappings') or []
            row['event_source_mappings'] = [
                {
                    'uuid': m.get('UUID'),
                    'event_source_arn': m.get('EventSourceArn'),
                    'state': m.get('State'),
                    'batch_size': m.get('BatchSize'),
                    'maximum_batching_window': m.get('MaximumBatchingWindowInSeconds'),
                    'last_modified': str(m.get('LastModified')),
                }
                for m in mappings[:10]
            ]
        except Exception as e:
            row['event_source_mappings_error'] = sanitize_error(e)
        try:
            invoke_cfg = lambda_client.get_function_event_invoke_config(FunctionName=name)
            row['async_invoke_config'] = {
                'maximum_retry_attempts': invoke_cfg.get('MaximumRetryAttempts'),
                'maximum_event_age': invoke_cfg.get('MaximumEventAgeInSeconds'),
                'destination_config': invoke_cfg.get('DestinationConfig'),
            }
        except Exception as e:
            row['async_invoke_config_error'] = sanitize_error(e)
        dims = [{'Name': 'FunctionName', 'Value': name}]
        period_hint = int(alarm.get('Period') or 300) if isinstance(alarm, dict) else 300
        row['metrics'] = [
            {
                'metric_name': 'Errors',
                'statistic': 'Sum',
                'summary': metric_statistics_summary(session, 'AWS/Lambda', 'Errors', dims, 'Sum', days, period_hint),
            },
            {
                'metric_name': 'Throttles',
                'statistic': 'Sum',
                'summary': metric_statistics_summary(session, 'AWS/Lambda', 'Throttles', dims, 'Sum', days, period_hint),
            },
            {
                'metric_name': 'Duration',
                'statistic': 'p99',
                'summary': metric_statistics_summary(session, 'AWS/Lambda', 'Duration', dims, 'p99', days, period_hint),
            },
        ]
        rows.append(row)
    return {'days': days, 'functions': rows}

def describe_rds_context(session, alarm: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if session is None or not alarm or 'error' in alarm:
        return None
    dims = {d.get('Name'): d.get('Value') for d in (alarm.get('Dimensions') or [])}
    if alarm.get('Namespace') != 'AWS/RDS' and not ({'DBClusterIdentifier', 'DBInstanceIdentifier'} & set(dims)):
        return None
    rds = session.client('rds')
    out: Dict[str, Any] = {'dimensions': dims}
    try:
        cluster_id = dims.get('DBClusterIdentifier')
        inst_id = dims.get('DBInstanceIdentifier')
        if cluster_id:
            clusters = rds.describe_db_clusters(DBClusterIdentifier=cluster_id).get('DBClusters') or []
            if clusters:
                cluster = clusters[0]
                out['cluster'] = {
                    'id': cluster.get('DBClusterIdentifier'),
                    'engine': cluster.get('Engine'),
                    'status': cluster.get('Status'),
                    'members': cluster.get('DBClusterMembers'),
                }
                instance_ids = [m.get('DBInstanceIdentifier') for m in cluster.get('DBClusterMembers') or [] if m.get('DBInstanceIdentifier')]
                if instance_ids:
                    insts = rds.describe_db_instances().get('DBInstances') or []
                    rows = []
                    for inst in insts:
                        if inst.get('DBInstanceIdentifier') in instance_ids:
                            rows.append({
                                'id': inst.get('DBInstanceIdentifier'),
                                'class': inst.get('DBInstanceClass'),
                                'role_hint': 'writer' if any(m.get('DBInstanceIdentifier') == inst.get('DBInstanceIdentifier') and m.get('IsClusterWriter') for m in cluster.get('DBClusterMembers') or []) else 'reader',
                                'pi_enabled': inst.get('PerformanceInsightsEnabled'),
                                'dbi_resource_id': inst.get('DbiResourceId'),
                            })
                    out['instances'] = rows
        elif inst_id:
            insts = rds.describe_db_instances(DBInstanceIdentifier=inst_id).get('DBInstances') or []
            if insts:
                inst = insts[0]
                out['instance'] = {
                    'id': inst.get('DBInstanceIdentifier'),
                    'class': inst.get('DBInstanceClass'),
                    'engine': inst.get('Engine'),
                    'status': inst.get('DBInstanceStatus'),
                    'pi_enabled': inst.get('PerformanceInsightsEnabled'),
                    'dbi_resource_id': inst.get('DbiResourceId'),
                }
    except Exception as e:
        return {'error': str(e)}
    return out

def parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    text = str(value).strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

def parse_log_timestamp(value: Any) -> Optional[datetime]:
    parsed = parse_datetime(value)
    if parsed:
        return parsed
    text = str(value or '').strip()
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None

def rds_pi_window(history: Optional[Dict[str, Any]]) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    anchor = now
    latest_alarm = ((history or {}).get('latest_alarm_transition') or {}).get('timestamp')
    parsed_latest = parse_datetime(latest_alarm)
    if parsed_latest:
        anchor = min(parsed_latest, now)
        return anchor - timedelta(hours=2), anchor + timedelta(minutes=15)
    for item in (history or {}).get('sample_items') or []:
        if not isinstance(item, dict) or item.get('new_state') != 'ALARM':
            continue
        parsed = parse_datetime(item.get('timestamp'))
        if parsed:
            anchor = min(parsed, now)
            break
    start = max(anchor - timedelta(minutes=45), now - timedelta(days=7))
    end = min(max(anchor + timedelta(minutes=45), start + timedelta(minutes=10)), now)
    if end <= start:
        start = now - timedelta(hours=2)
        end = now
    return start, end

def rds_pi_focus_window(history: Optional[Dict[str, Any]]) -> tuple[datetime, datetime]:
    """Narrow window for attributing the current RDS alarm, not historical background load."""
    now = datetime.now(timezone.utc)
    latest_alarm = ((history or {}).get('latest_alarm_transition') or {}).get('timestamp')
    anchor = parse_datetime(latest_alarm) or now
    anchor = min(anchor, now)
    start = anchor - timedelta(minutes=10)
    end = min(anchor + timedelta(minutes=5), now)
    if end <= start:
        start = now - timedelta(minutes=15)
        end = now
    return start, end

def rds_instances_for_pi(rds_context: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(rds_context, dict) or rds_context.get('error'):
        return []
    out: List[Dict[str, Any]] = []
    if isinstance(rds_context.get('instance'), dict):
        item = dict(rds_context['instance'])
        item.setdefault('role_hint', 'instance')
        out.append(item)
    for item in rds_context.get('instances') or []:
        if isinstance(item, dict):
            out.append(dict(item))
    return [i for i in out if i.get('pi_enabled') and i.get('dbi_resource_id')][:MAX_RDS_PI_INSTANCES]

def collect_rds_performance_insights(
    session,
    rds_context: Optional[Dict[str, Any]],
    history: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    instances = rds_instances_for_pi(rds_context)
    if session is None or not instances:
        return None
    start, end = rds_pi_window(history)
    focus_start, focus_end = rds_pi_focus_window(history)
    pi = session.client('pi')
    rows = []
    detected_project_ids: List[str] = []
    table_refs_by_project: Dict[str, List[str]] = {}
    load_by_project: Dict[str, float] = {}
    max_load_by_project: Dict[str, float] = {}
    current_load_by_project: Dict[str, float] = {}
    current_max_load_by_project: Dict[str, float] = {}
    current_points_by_project: Dict[str, int] = {}
    current_unattributed_sql: List[Dict[str, Any]] = []
    for inst in instances:
        try:
            resp = pi.get_resource_metrics(
                ServiceType='RDS',
                Identifier=inst['dbi_resource_id'],
                StartTime=start,
                EndTime=end,
                PeriodInSeconds=60,
                MetricQueries=[{
                    'Metric': 'db.load.avg',
                    'GroupBy': {
                        'Group': 'db.sql',
                        'Dimensions': ['db.sql.id', 'db.sql.statement'],
                        'Limit': MAX_RDS_PI_SQL,
                    },
                }],
            )
            top_sql = []
            for metric in resp.get('MetricList') or []:
                key = metric.get('Key') or {}
                dims = key.get('Dimensions') or {}
                datapoints = metric.get('DataPoints') or []
                values = [dp.get('Value') for dp in datapoints if isinstance(dp.get('Value'), (int, float))]
                focus_values = []
                for dp in datapoints:
                    value = dp.get('Value')
                    ts = parse_datetime(dp.get('Timestamp'))
                    if isinstance(value, (int, float)) and ts and focus_start <= ts <= focus_end:
                        focus_values.append(value)
                raw_statement = str(dims.get('db.sql.statement') or dims.get('db.sql.name') or dims.get('db.sql.id') or '')
                table_refs = detect_sharded_table_refs(raw_statement)
                for ref in table_refs:
                    detected_project_ids.append(ref['project_id'])
                    table_refs_by_project.setdefault(ref['project_id'], [])
                    table_refs_by_project[ref['project_id']].append(ref['table_pattern'])
                statement = sanitize_sql_statement(raw_statement)
                sql_id = dims.get('db.sql.id')
                if not values or not (statement or sql_id):
                    continue
                avg_load = round(sum(values) / len(values), 4)
                max_load = round(max(values), 4)
                focus_avg_load = round(sum(focus_values) / len(focus_values), 4) if focus_values else 0.0
                focus_max_load = round(max(focus_values), 4) if focus_values else 0.0
                sql_project_ids = unique([ref['project_id'] for ref in table_refs])
                for project_id in sql_project_ids:
                    load_by_project[project_id] = load_by_project.get(project_id, 0.0) + avg_load
                    max_load_by_project[project_id] = max(max_load_by_project.get(project_id, 0.0), max_load)
                    if focus_values:
                        current_load_by_project[project_id] = current_load_by_project.get(project_id, 0.0) + focus_avg_load
                        current_max_load_by_project[project_id] = max(current_max_load_by_project.get(project_id, 0.0), focus_max_load)
                        current_points_by_project[project_id] = current_points_by_project.get(project_id, 0) + len(focus_values)
                if focus_values and not sql_project_ids:
                    current_unattributed_sql.append({
                        'instance_id': inst.get('id'),
                        'role_hint': inst.get('role_hint'),
                        'sql_id': sql_id,
                        'statement': statement,
                        'focus_avg_load': focus_avg_load,
                        'focus_max_load': focus_max_load,
                        'focus_points': len(focus_values),
                    })
                top_sql.append({
                    'sql_id': sql_id,
                    'statement': statement,
                    'table_refs': table_refs,
                    'avg_load': avg_load,
                    'max_load': max_load,
                    'focus_avg_load': focus_avg_load,
                    'focus_max_load': focus_max_load,
                    'focus_points': len(focus_values),
                    'points': len(values),
                })
            rows.append({
                'instance_id': inst.get('id'),
                'role_hint': inst.get('role_hint'),
                'dbi_resource_id': inst.get('dbi_resource_id'),
                'top_sql': sorted(top_sql, key=lambda x: x.get('avg_load') or 0, reverse=True)[:MAX_RDS_PI_SQL],
            })
        except Exception as e:
            rows.append({
                'instance_id': inst.get('id'),
                'role_hint': inst.get('role_hint'),
                'dbi_resource_id': inst.get('dbi_resource_id'),
                'error': sanitize_error(e),
            })
    return {
        'window_start': start.isoformat(),
        'window_end': end.isoformat(),
        'focus_window_start': focus_start.isoformat(),
        'focus_window_end': focus_end.isoformat(),
        'source': 'AWS Performance Insights db.load.avg grouped by db.sql',
        'instances': rows,
        'detected_scope_ids': {
            'project_ids': unique(detected_project_ids)[:10],
            'current_top_projects_by_load': [
                {
                    'project_id': pid,
                    'focus_avg_load_sum': round(current_load_by_project.get(pid, 0.0), 4),
                    'focus_max_load': round(current_max_load_by_project.get(pid, 0.0), 4),
                    'focus_points': current_points_by_project.get(pid, 0),
                    'table_families': unique(table_refs_by_project.get(pid, []))[:10],
                }
                for pid in sorted(current_load_by_project, key=lambda p: current_load_by_project.get(p, 0.0), reverse=True)[:10]
            ],
            'current_unattributed_top_sql': sorted(
                current_unattributed_sql,
                key=lambda item: item.get('focus_avg_load') or 0,
                reverse=True,
            )[:5],
            'top_projects_by_load': [
                {
                    'project_id': pid,
                    'avg_load_sum': round(load_by_project.get(pid, 0.0), 4),
                    'max_load': round(max_load_by_project.get(pid, 0.0), 4),
                    'table_families': unique(table_refs_by_project.get(pid, []))[:10],
                }
                for pid in sorted(load_by_project, key=lambda p: load_by_project.get(p, 0.0), reverse=True)[:10]
            ],
            'table_refs_by_project': {
                pid: unique(families)[:10]
                for pid, families in table_refs_by_project.items()
            },
        },
        'note': 'Use this to name the concrete DB instance and SQL family in DB alert final responses.',
    }

def map_projects_via_dynamodb(session, project_ids: Sequence[str]) -> Optional[List[Dict[str, Any]]]:
    if session is None or not project_ids:
        return None
    ddb = session.client('dynamodb')
    out = []
    for pid in project_ids[:10]:
        try:
            resp = ddb.get_item(
                TableName=PROJECT_TABLE_NAME,
                Key={'id': {'S': pid}},
                ProjectionExpression='id, product_id, #n',
                ExpressionAttributeNames={'#n': 'name'},
            )
            item = resp.get('Item') or {}
            if not item:
                out.append({
                    'project_id': pid,
                    'product_id': None,
                    'name': None,
                    'mapping_status': 'not_found',
                    'mapping_failure_reason': f'DynamoDB {PROJECT_TABLE_NAME} table item not found',
                })
            else:
                out.append({
                    'project_id': item.get('id', {}).get('S', pid),
                    'product_id': item.get('product_id', {}).get('S'),
                    'name': item.get('name', {}).get('S'),
                    'mapping_status': 'found',
                    'mapping_failure_reason': None,
                })
        except Exception as e:
            out.append({
                'project_id': pid,
                'mapping_status': 'error',
                'mapping_failure_reason': sanitize_error(e),
                'error': sanitize_error(e),
            })
    return out
