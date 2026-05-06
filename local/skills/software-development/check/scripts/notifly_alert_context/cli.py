from .common import *
from .detect import (
    detect_alarm_name, detect_region, detect_log_groups, detect_project_ids,
    detect_campaign_ids, detect_user_journey_ids, detect_user_journey_refs,
    detect_keywords, detect_queue_names, detect_service_names, service_names_from_log_groups,
    detect_lambda_names, alarm_dimension_value,
)
from .aws_collectors import (
    build_aws_session, call_sts, describe_alarm, collect_alarm_history, summarize_alarm,
    map_projects_via_dynamodb,
)
from .collectors import CollectorContext, run_collectors
from .scope import (
    merge_scope_detections, build_scope_attribution,
)
from .repo import repo_search
from .assessment import print_section, assess_helper_context, compact_output

def main() -> None:
    parser = argparse.ArgumentParser(description='Collect first-pass live alert context for Notifly incidents using Hermes profile/global .env-backed data sources.')
    parser.add_argument('--text', help='Pasted alert or thread text')
    parser.add_argument('--text-file', help='Path to file containing pasted alert or thread text')
    parser.add_argument('--stdin', action='store_true', help='Read pasted alert or thread text from stdin')
    parser.add_argument('--alarm-name', help='Explicit CloudWatch alarm name override')
    parser.add_argument('--region', help='AWS region override')
    parser.add_argument('--repo', default=str(DEFAULT_REPO), help='Local repo path for source search (default: /home/ubuntu/notifly-event)')
    parser.add_argument('--lookback-days', type=int, default=30, help='Alarm history lookback window in days')
    parser.add_argument('--format', choices=('compact-json', 'sections'), default='compact-json', help='Output format')
    args = parser.parse_args()

    load_env_files()
    text = read_text_arg(args)
    alarm_name = detect_alarm_name(text, args.alarm_name)
    region = detect_region(text, args.region)
    log_groups = detect_log_groups(text)
    project_ids = detect_project_ids(text)
    campaign_ids = detect_campaign_ids(text)
    user_journey_ids = detect_user_journey_ids(text)
    user_journey_refs = detect_user_journey_refs(text)
    keywords = detect_keywords(text)
    queue_names = detect_queue_names(text)
    service_names = unique([*detect_service_names(text), *service_names_from_log_groups(log_groups)])

    session = build_aws_session(region)
    sts = call_sts(session)
    alarm = describe_alarm(session, alarm_name)
    service_names = unique([*service_names, *alarm_dimension_value(alarm, ['ServiceName', 'ClusterName'])])
    queue_names = unique([*queue_names, *alarm_dimension_value(alarm, ['QueueName'])])
    lambda_names = detect_lambda_names(text, log_groups, alarm)
    history = collect_alarm_history(session, alarm_name, args.lookback_days)
    collector_results = run_collectors(CollectorContext(
        session=session,
        text=text,
        alarm=alarm,
        log_groups=log_groups,
        keywords=keywords,
        queue_names=queue_names,
        lambda_names=lambda_names,
        history=history,
        days=7,
    ))
    metric_datapoints = collector_results.get('metric_datapoints')
    rds_context = collector_results.get('rds_context')
    rds_performance_insights = collector_results.get('rds_performance_insights')
    metric_filters = collector_results.get('metric_filters')
    logs_insights = collector_results.get('logs_insights')
    http_context = collector_results.get('http_context')
    five_xx_metrics = collector_results.get('five_xx_metrics')
    sqs_context = collector_results.get('sqs_context')
    lambda_context = collector_results.get('lambda_context')
    campaign_scope_hints = collector_results.get('campaign_scope_hints')
    scope_detections = merge_scope_detections(
        text,
        logs_insights,
        rds_performance_insights,
        project_ids,
        campaign_ids,
        user_journey_ids,
        user_journey_refs,
    )
    project_ids = scope_detections['project_ids']
    campaign_ids = scope_detections['campaign_ids']
    project_campaign_pairs = scope_detections['project_campaign_pairs']
    user_journey_ids = scope_detections['user_journey_ids']
    user_journey_refs = scope_detections['user_journey_refs']
    project_mappings = map_projects_via_dynamodb(session, project_ids)

    repo_tokens = [alarm_name or '', *keywords, *service_names]
    repo_tokens.extend([*queue_names, *lambda_names])
    if isinstance(alarm, dict):
        repo_tokens.extend([str(alarm.get('MetricName') or ''), str(alarm.get('AlarmDescription') or '')])
    for mf in metric_filters or []:
        if isinstance(mf, dict):
            repo_tokens.extend([str(mf.get('filter_name') or ''), str(mf.get('filter_pattern') or '')])
    code_hits = repo_search(Path(args.repo), repo_tokens)

    detected = {
        'alarm_name': alarm_name,
        'region': region,
        'log_groups': log_groups,
        'project_ids': project_ids,
        'campaign_ids': campaign_ids,
        'project_campaign_pairs': project_campaign_pairs,
        'user_journey_ids': user_journey_ids,
        'user_journey_refs': user_journey_refs,
        'queue_names': queue_names,
        'lambda_names': lambda_names,
        'service_names': service_names,
        'keywords': keywords,
    }

    data = {
        'detected': detected,
        'aws_caller_identity': sts,
        'alarm_summary': summarize_alarm(alarm) if isinstance(alarm, dict) else alarm,
        'alarm_history': history,
        'metric_datapoints': metric_datapoints,
        'rds_context': rds_context,
        'rds_performance_insights': rds_performance_insights,
        'metric_filters': metric_filters,
        'logs_insights': logs_insights,
        'http_context': http_context,
        'five_xx_metrics': five_xx_metrics,
        'sqs_context': sqs_context,
        'lambda_context': lambda_context,
        'campaign_scope_hints': campaign_scope_hints,
        'project_mappings': project_mappings,
        'scope_attribution': build_scope_attribution(detected, alarm, project_mappings, rds_performance_insights),
        'repo_code_hits': code_hits,
    }
    data['helper_assessment'] = assess_helper_context(data)

    if args.format == 'sections':
        print_section('Detected artifacts', detected)
        print_section('AWS caller identity', sts)
        print_section('Helper assessment', data['helper_assessment'])
        print_section('Alarm summary', data['alarm_summary'])
        print_section('Alarm history', history)
        print_section('Metric datapoints', metric_datapoints)
        print_section('Metric filters', metric_filters)
        print_section('Logs Insights compact summary', logs_insights)
        print_section('HTTP context', http_context)
        print_section('5xx metrics', five_xx_metrics)
        print_section('SQS context', sqs_context)
        print_section('Lambda context', lambda_context)
        print_section('RDS context', rds_context)
        print_section('RDS Performance Insights', rds_performance_insights)
        print_section('Campaign scope hints', campaign_scope_hints)
        print_section('Project mappings', project_mappings)
        print_section('Repo code hits', code_hits)
    else:
        print(json.dumps(compact_output(data), ensure_ascii=False, indent=2, default=str))
