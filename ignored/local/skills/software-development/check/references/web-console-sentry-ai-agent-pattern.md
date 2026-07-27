# web-console Sentry AI agent error pattern

## Trigger

Sentry email alert proxy (`/aws/ecs/notifly-services-prod/web-console/sentry`) sometimes carries greybox issues with varying messages grouped under the same browser-side issue:

- `Google Generative AI API key is missing. Pass it using the 'apiKey' parameter...`
- `Unsupported AI_MODEL "<name>" for AI_PROVIDER=google. Available models: ...`
- `no healthy upstream`

Shared attributes:
- `transaction`: `/console/products/[productId]/campaign/list`
- `handled`: `yes` (browser exception, not service crash)
- `request.url` / `tags.url`: `https://console-stage.notifly.tech/console/products/<productId>/campaign/list`
- `feature`: `ai-agent`
- `level`: `error` (trips the `%ERROR%` metric filter)

## Extraction

```bash
aws logs filter-log-events --region ap-northeast-2 \
  --log-group-name '/aws/ecs/notifly-services-prod/web-console/sentry' \
  --start-time <epoch_ms> --end-time <epoch_ms> \
  --filter-pattern 'Google Generative AI API key' \
  --limit 5 --output json | jq -r '.events[].message' | python3 -c "
import sys, json
for line in sys.stdin:
    d = json.loads(line)
    sa = d.get('sentryAlert', {})
    issue = sa.get('issue', {})
    tags = sa.get('tags', {})
    print(json.dumps({
        'transaction': issue.get('transaction'),
        'message': issue.get('message'),
        'url': sa.get('request', {}).get('url', tags.get('url')),
        'handled': tags.get('handled'),
        'feature': tags.get('feature'),
    }, ensure_ascii=False))
"
```

## Scope

Extract `<productId>` from `request.url` or `tags.url` and map via DynamoDB `project` table GSI `product_id-project_id-index`. Projects with slug `michael` or `notifly-*` are internal/stage test projects.

## Classification

- `no_action` when isolated/internal project and `handled: yes`.
- `needs_fix` only if the same `transaction`+`message` pair spikes sharply across multiple production projects.