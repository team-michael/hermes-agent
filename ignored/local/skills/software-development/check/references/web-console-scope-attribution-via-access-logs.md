# web-console Scope Attribution via Access Logs

When a `web-console` console error alarm fires and the triggering ERROR log does not contain `project_id` or `campaign_id`, the scope may still be recoverable from the access log.

## Referer header extraction

The `web-console` access log format includes the HTTP `Referer` header. For UI-driven requests, the Referer path contains the product slug:

```
POST /api/liquid/template ... "https://console.notifly.tech/ko/console/products/qmarket/utils/liquid-playground"
```

Extract `<productId>` from `/console/products/<productId>/...`.

## Path-parameter extraction (API route handlers)

For API endpoints that take `projectId` as a URL path parameter, the access log line shows the concrete value even when the error log line does not:

```
POST /api/projects/5578956dbb9459a9858dbb91e67a0c8a/test_send/kakao_brand_message HTTP/1.1
```

The error log for the same request may only show the generic route frame (`/api/projects/[projectId]/test_send/kakao_brand_message.js`) without the resolved value. Always inspect access logs in the alarm window when the error log stack trace shows a parameterized route.

## Multi-stream pitfall (Fargate)

The `web-console` service runs multiple Fargate tasks behind a load balancer. The access log and the error log for the **same request** can end up on **different log streams** because each task writes to its own stream. When `get-log-events` or `filter-log-events` on the stream containing the ERROR line yields no matching access log, repeat the search across **all active streams** in the alarm window:

```bash
aws logs describe-log-streams \
  --region ap-northeast-2 \
  --log-group-name '/aws/ecs/notifly-services-prod/web-console' \
  --order-by LastEventTime --descending --limit 10
```

Then run `get-log-events` on each stream that has events overlapping the alarm window. Do not assume a single stream carries both log types.

## DynamoDB mapping

Query via DynamoDB `project` table GSI `product_id-project_id-index`:

```python
table.query(
    IndexName='product_id-project_id-index',
    KeyConditionExpression=Key('product_id').eq('<productId>'),
    ProjectionExpression='id, product_id, #n',
    ExpressionAttributeNames={'#n': 'name'},
)
```

## Duplicate product_id pitfall

The same `product_id` may map to **multiple** `project.id` values.
Example: `qmarket` maps to two distinct projects
(`c39ea97b82285ed5a445c75c5819e340` and `f2e198e2448959908fe4f8e540f4057f`).
Do not assume 1:1 mapping. Report all matches when duplicates exist.

## Endpoints known to not log project_id

- `POST /api/liquid/template` — Liquid Playground preview endpoint; renders user-supplied Liquid template with context JSON. Does not include `projectId` in request body.
- Any UI playground or preview endpoint that delegates rendering to a generic API.
