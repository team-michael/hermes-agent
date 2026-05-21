# web-console Scope Attribution via Access Logs

When a `web-console` console error alarm fires and the triggering ERROR log does not contain `project_id` or `campaign_id`, the scope may still be recoverable from the access log.

## Referer header extraction

The `web-console` access log format includes the HTTP `Referer` header. For UI-driven requests, the Referer path contains the product slug:

```
POST /api/liquid/template ... "https://console.notifly.tech/ko/console/products/qmarket/utils/liquid-playground"
```

Extract `<productId>` from `/console/products/<productId>/...`.

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
