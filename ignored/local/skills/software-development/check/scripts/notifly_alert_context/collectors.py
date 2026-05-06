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
)
from .logs import describe_metric_filters, collect_logs_insights_summary
from .scope import collect_campaign_scope_hints


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


def _collect_logs_insights(ctx: CollectorContext) -> Any:
    return collect_logs_insights_summary(
        ctx.session,
        ctx.log_groups,
        ctx.text,
        ctx.alarm,
        ctx.keywords,
        ctx.results.get('metric_filters'),
        ctx.history,
    )


def _collect_rds_performance_insights(ctx: CollectorContext) -> Any:
    return collect_rds_performance_insights(
        ctx.session,
        ctx.results.get('rds_context'),
        ctx.history,
    )


def _collect_campaign_scope_hints(ctx: CollectorContext) -> Any:
    return collect_campaign_scope_hints(
        ctx.results.get('logs_insights'),
        ctx.results.get('rds_performance_insights'),
    )


COLLECTOR_REGISTRY = (
    CollectorSpec('metric_datapoints', lambda ctx: collect_metric_datapoints(ctx.session, ctx.alarm, days=ctx.days)),
    CollectorSpec('rds_context', lambda ctx: describe_rds_context(ctx.session, ctx.alarm)),
    CollectorSpec('metric_filters', _collect_metric_filters),
    CollectorSpec('logs_insights', _collect_logs_insights),
    CollectorSpec('http_context', lambda ctx: collect_http_context(ctx.session, ctx.alarm, ctx.text, days=ctx.days)),
    CollectorSpec('five_xx_metrics', lambda ctx: collect_5xx_metrics(ctx.session, ctx.alarm, days=ctx.days)),
    CollectorSpec('sqs_context', lambda ctx: collect_sqs_context(ctx.session, ctx.alarm, ctx.queue_names, days=ctx.days)),
    CollectorSpec('lambda_context', lambda ctx: collect_lambda_context(ctx.session, ctx.alarm, ctx.lambda_names, days=ctx.days)),
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
