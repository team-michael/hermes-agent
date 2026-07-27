# Notifly EMF dimension cost and usage patterns

Use when designing or reviewing CloudWatch EMF metrics for Notifly services, especially MCP/tool-call telemetry.

## Mechanism

EMF is a structured CloudWatch Logs event that CloudWatch also extracts into custom metrics via the `_aws.CloudWatchMetrics` block. Cost is therefore two-part:

1. CloudWatch Logs ingestion/storage for the JSON log event.
2. CloudWatch custom metric cost for every extracted `MetricName + DimensionSet` time series.

For most low/medium-volume app telemetry, the expensive part is not log bytes; it is the number of custom metric series created by dimension combinations.

## Seoul region reference prices observed from AWS pricing offer

- Custom metric: first 10,000 metrics at about `$0.30 / metric-month`; next 240,000 at about `$0.10 / metric-month`; next 750,000 at `$0.05`; over 1M at `$0.02`.
- Custom CloudWatch Logs ingestion: about `$0.76 / GB`.
- CloudWatch Logs storage: about `$0.0314 / GB-month`.
- Logs Insights scan: about `$0.0076 / GB`.
- Standard alarm: about `$0.10 / alarm-month`.
- Metrics Insights alarm: about `$0.10 / metric analyzed / month`.

Always re-check AWS pricing for current values before making financial commitments.

## Cardinality calculation

Custom metric series count is roughly:

```text
metric_names × dim1_cardinality × dim2_cardinality × ...
```

Example MCP telemetry:

```text
ProjectId × ToolName × Status × MetricName
```

If there are 100 projects, 25 tools, 3 statuses, and 3 metrics:

```text
100 × 25 × 3 × 3 = 22,500 custom metric series
```

At Seoul first/second tier pricing this is roughly `$4,250/month` for metrics alone. By comparison, 1M EMF events/month at 2KB/event is only about 1.9GB of log ingestion, roughly `$1.45/month` plus small storage.

## Existing Notifly patterns

### `api-service` HTTP metrics

Path: `services/server/api-service/lib/middlewares/http-metrics.js`

Current pattern:

- Metrics: `RequestCount`, `RequestDuration`
- Dimensions: `StatusCode`, `NormalizedPath`
- Properties only: `ProjectId`, `Method`, `RawPath`

Interpretation: for broad HTTP traffic, `ProjectId` is deliberately kept out of dimensions to avoid `path × status × project` metric explosion. It remains searchable in Logs Insights as a property.

### `kakao-delivery-result-poller`

Path: `services/lambda/kakao-delivery-result-poller/index.ts`

Uses `project_id` as a real dimension for bounded workflow telemetry:

- `TerminalState` dimensions include `project_id`, `channel`, `status`.
- `PollingDuration` dimensions include `project_id`, `channel`, `final_status`.
- `PollAttempt` dimensions include `project_id`, `channel`, `outcome`.

Dashboards query these dimensions with Metrics Insights / SEARCH, e.g. `GROUP BY project_id`, project-level p99 polling duration, and terminal state by project.

Interpretation: Notifly already treats bounded tenant/project dimensions as acceptable when project-level operational views are explicitly useful.

### `delivery-result-webhook-receiver`

Path: `services/lambda/delivery-result-webhook-receiver/lib/delivery_result.ts`

Current pattern:

- `RowOutcome` dimensions: `outcome`, `channel`
- `project_id` property only
- `DbWriteError` dimensions include `channel`, `error_code`; project remains property

Interpretation: for row-level/high-volume processing, project-level detail is kept searchable but not metric-dimensional.

## Recommendation for public MCP/tool-call telemetry

`ProjectId` can be a dimension if external MCP project cardinality is truly bounded (for example <=10 expected, <=100 max) and project-level dashboards/alerts are a product/ops requirement. The risk is not `ProjectId` alone; it is the cross product with `ToolName`, `Status`, `MetricName`, and any future dimensions.

Safer split:

1. Global tool metrics
   - Dimensions: `Environment`, `ToolName`, `Status`
   - Metrics: count, duration, error count
   - Purpose: overall tool stability and latency

2. Project impact metrics
   - Dimensions: `Environment`, `ProjectId`, `Status`
   - Optionally `ToolCategory`, not raw `ToolName`, if tool count grows
   - Purpose: project/customer-level usage and failure impact

3. Structured logs / S3 JSONL / Athena
   - Properties: `ProjectId`, `ToolName`, `RequestId`, `ToolCallId`, `ErrorCode`, safe arg keys/hash
   - Purpose: detailed investigation without custom metric series explosion

Avoid dimensions for `RequestId`, `ToolCallId`, raw user/customer identifiers, `CampaignId`, `OAuthClientId`, raw `ErrorMessage`, or anything unbounded.

## Practical review question

Before approving a new EMF dimension, ask:

> What is the expected and worst-case number of resulting `MetricName + DimensionSet` series this month?

If no one can answer, keep the field as a log property first and promote it to a dimension only after usage is measured.
