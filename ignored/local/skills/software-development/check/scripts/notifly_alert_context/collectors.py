from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Sequence

from .common import *
from .aws_collectors import (
    collect_metric_datapoints,
    collect_5xx_metrics,
    collect_http_context,
    collect_sqs_context,
    collect_lambda_context,
    describe_rds_context,
    collect_rds_performance_insights,
    collect_lambda_top_offenders,
)
from .alarm_shape import classify_alarm_shape
from .logs import (
    collect_lambda_alarm_signatures,
    describe_metric_filters,
    collect_logs_insights_summary,
)
from .scope import collect_campaign_scope_hints
from .hermes_observability import collect_hermes_observability_context


@dataclass
class CollectorContext:
    session: Any
    text: str
    alarm: Optional[Dict[str, Any]]
    log_groups: Sequence[str]
    keywords: Sequence[str]
    queue_names: Sequence[str]
    lambda_names: Sequence[str]
    history: Optional[Dict[str, Any]]
    days: int = 7
    results: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CollectorSpec:
    output_key: str
    collect: Callable[[CollectorContext], Any]


def _collect_metric_filters(ctx: CollectorContext) -> Any:
    return describe_metric_filters(ctx.session, ctx.log_groups, ctx.alarm, ctx.keywords)


def effective_lambda_names(ctx: CollectorContext) -> List[str]:
    discovery = ctx.results.get('lambda_discovery') or {}
    return unique([
        *(ctx.lambda_names or []),
        *(discovery.get('derived_lambda_names') or []),
    ])


def effective_log_groups(ctx: CollectorContext) -> List[str]:
    discovery = ctx.results.get('lambda_discovery') or {}
    return unique([
        *(ctx.log_groups or []),
        *(discovery.get('derived_log_groups') or []),
    ])[:MAX_LOG_QUERY_GROUPS]


def _collect_metric_datapoints(ctx: CollectorContext) -> Any:
    return collect_metric_datapoints(ctx.session, ctx.alarm, days=ctx.days)


def _collect_alarm_shape(ctx: CollectorContext) -> Any:
    return classify_alarm_shape(ctx.alarm, text=ctx.text)


def _collect_lambda_discovery(ctx: CollectorContext) -> Any:
    return collect_lambda_top_offenders(
        ctx.session,
        ctx.alarm,
        ctx.history,
        ctx.results.get('alarm_shape'),
    )


def _collect_hermes_observability(ctx: CollectorContext) -> Any:
    return collect_hermes_observability_context(
        ctx.session,
        ctx.alarm,
        ctx.history,
        alarm_shape=ctx.results.get('alarm_shape'),
    )


def _collect_logs_insights(ctx: CollectorContext) -> Any:
    payment_mode = bool(
        any(
            'payment-executor' in name or name == 'payment-executor'
            for name in effective_lambda_names(ctx)
        )
    )
    return collect_logs_insights_summary(
        ctx.session,
        ctx.log_groups,
        ctx.text,
        ctx.alarm,
        ctx.keywords,
        ctx.results.get('metric_filters'),
        ctx.history,
        payment_mode=payment_mode,
    )


def _collect_lambda_log_signatures(ctx: CollectorContext) -> Any:
    return collect_lambda_alarm_signatures(
        ctx.session,
        effective_log_groups(ctx),
        ctx.alarm,
        ctx.history,
    )


def _collect_rds_context(ctx: CollectorContext) -> Any:
    return describe_rds_context(
        ctx.session,
        ctx.alarm,
        alarm_shape=ctx.results.get('alarm_shape'),
        logs_insights=ctx.results.get('logs_insights'),
        lambda_log_signatures=ctx.results.get('lambda_log_signatures'),
    )


def _collect_rds_performance_insights(ctx: CollectorContext) -> Any:
    return collect_rds_performance_insights(
        ctx.session,
        ctx.results.get('rds_context'),
        ctx.history,
    )


def _collect_http_context(ctx: CollectorContext) -> Any:
    return collect_http_context(ctx.session, ctx.alarm, ctx.text, days=ctx.days)


def _collect_five_xx_metrics(ctx: CollectorContext) -> Any:
    return collect_5xx_metrics(ctx.session, ctx.alarm, days=ctx.days)


def _collect_lambda_context(ctx: CollectorContext) -> Any:
    return collect_lambda_context(
        ctx.session,
        ctx.alarm,
        effective_lambda_names(ctx),
        days=ctx.days,
    )


def queue_names_from_dlq_backlog(logs_insights: Any) -> List[str]:
    if not isinstance(logs_insights, dict):
        return []
    current = (logs_insights.get('dlq_backlog') or {}).get('current') or {}
    latest = current.get('latest_event') or {}
    return unique([
        str(queue.get('queue_name') or '')
        for queue in latest.get('queues') or []
        if isinstance(queue, dict) and queue.get('queue_name')
    ])


def _collect_sqs_context(ctx: CollectorContext) -> Any:
    queue_names = unique([
        *(ctx.queue_names or []),
        *queue_names_from_dlq_backlog(ctx.results.get('logs_insights')),
    ])
    return collect_sqs_context(
        ctx.session,
        ctx.alarm,
        queue_names,
        days=ctx.days,
    )


def _collect_campaign_scope_hints(ctx: CollectorContext) -> Any:
    return collect_campaign_scope_hints(
        ctx.results.get('logs_insights'),
        ctx.results.get('rds_performance_insights'),
    )


COLLECTOR_REGISTRY = (
    CollectorSpec('metric_datapoints', _collect_metric_datapoints),
    CollectorSpec('alarm_shape', _collect_alarm_shape),
    CollectorSpec('lambda_discovery', _collect_lambda_discovery),
    CollectorSpec('hermes_observability', _collect_hermes_observability),
    CollectorSpec('metric_filters', _collect_metric_filters),
    CollectorSpec('logs_insights', _collect_logs_insights),
    CollectorSpec('lambda_log_signatures', _collect_lambda_log_signatures),
    CollectorSpec('rds_context', _collect_rds_context),
    CollectorSpec('http_context', _collect_http_context),
    CollectorSpec('five_xx_metrics', _collect_five_xx_metrics),
    CollectorSpec('sqs_context', _collect_sqs_context),
    CollectorSpec('lambda_context', _collect_lambda_context),
    CollectorSpec('rds_performance_insights', _collect_rds_performance_insights),
    CollectorSpec('campaign_scope_hints', _collect_campaign_scope_hints),
)


def collector_keys(specs: Sequence[CollectorSpec] = COLLECTOR_REGISTRY) -> List[str]:
    return [spec.output_key for spec in specs]


def run_collectors(
    ctx: CollectorContext,
    specs: Sequence[CollectorSpec] = COLLECTOR_REGISTRY,
) -> Dict[str, Any]:
    for spec in specs:
        ctx.results[spec.output_key] = spec.collect(ctx)
    return ctx.results
