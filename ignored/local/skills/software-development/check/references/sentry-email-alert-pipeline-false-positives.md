# Sentry Email Alert Pipeline Analysis

Alarm family: `/aws/ecs/notifly-services-prod/web-console/sentry alert` (metric namespace `ConsoleErrors`).

**User intent correction**: This alarm is **intentional error logging**, not a Lambda crash or generic false positive. The `ops-email-receiver` Lambda receives Sentry alert emails via SES and writes parsed payloads to CloudWatch Logs. A broad `%ERROR%` metric filter matches literal strings inside the JSON payload (e.g., `"title":"SyntaxError"`, `"level":"error"`), so the alarm fires whenever any Sentry issue arrives.

When this alarm fires, the investigation goal is **not** to prove the Lambda is healthy. The goal is to parse the actual Sentry payload and report:
- which page / feature is failing,
- what the concrete error message and title are,
- which Notifly project / product is affected,
- how often it occurs,
- and whether it is a user-facing incident.

## Alarm name auto-detection pitfall

The alarm name is literally the CloudWatch log group path suffixed with ` alert`. When Slack delivers only this path as the alert text, the helper text parser returns `detected.alarm_name: null` because there is no `CloudWatch Alarm | <name>` marker. Pass `--alarm-name '/aws/ecs/notifly-services-prod/web-console/sentry alert'` explicitly. This is a Terraform-generated metric-filter alarm where the alarm name equals the log group name.

## Why the alarm fires

- `ops-email-receiver` Lambda writes structured JSON to `/aws/ecs/notifly-services-prod/web-console/sentry`.
- The payload contains fields such as `"level":"error"`, `"issue":{"title":"Error"}`, `"title":"SyntaxError"`, etc.
- The metric filter `%[Ee][Rr][Rr][Oo][Rr]%` matches inside the JSON text, producing a `ConsoleErrors` datapoint for every Sentry alert.
- Lambda runtime `Errors` metric is typically zero because the Lambda itself succeeds.

## Analysis workflow (prioritized)

1. **Confirm Lambda health** (one-liner): cross-check `AWS/Lambda Errors` for `ops-email-receiver`. If zero, the pipeline is operating correctly.
2. **Parse Sentry payloads** from the alarm window:
   - Use `filter-log-events` or Logs Insights on `/aws/ecs/notifly-services-prod/web-console/sentry`.
   - Extract `sentryAlert.issue.title`, `sentryAlert.issue.transaction`, `sentryAlert.issue.message`, `sentryAlert.request.url`.
3. **Scope each issue**:
   - Extract the Notifly `productId` from `request.url` (e.g., `/console/products/<productId>/...`).
   - Map `<productId>` via DynamoDB `project` table GSI `product_id-project_id-index`. Use `dev = false` when duplicate items exist.
4. **Aggregate by title + transaction + project**:
   - Count occurrences, earliest/latest timestamps, and distinct URLs.
5. **Report in Korean** using this structure (not the generic 5-field alarm format):
   - `[Issue Title]` — how many times, which issue ID, which page/transaction.
   - **Project**: mapped project name and product slug.
   - **Error detail**: concrete `message` and `title`.
   - **Recurrence**: first seen and latest timestamps (KST).
   - **Customer impact**: whether the error is in a production project (dev=false) vs internal test (`michael`, stage, localhost).
   - **Action**: whether any specific pattern is worsening or requires follow-up.

## Parsing recipe (Python / boto3)

Use a bounded `filter-log-events` query anchored to the alarm datapoint window, then aggregate:

```python
import boto3, json, re
from datetime import datetime, timezone, timedelta

logs = boto3.client('logs', region_name='ap-northeast-2')
dynamodb = boto3.client('dynamodb', region_name='ap-northeast-2')

def get_project(product_id):
    if not product_id:
        return None
    resp = dynamodb.query(
        TableName='project',
        IndexName='product_id-project_id-index',
        KeyConditionExpression='product_id = :v',
        ExpressionAttributeValues={':v': {'S': product_id}},
        ProjectionExpression='id, #n',
        ExpressionAttributeNames={'#n': 'name'}
    )
    for item in resp.get('Items', []):
        # Prefer production (id starts with '0' -> prod hash heuristic)
        if item.get('id', {}).get('S', '').startswith('0'):
            return item
    return resp['Items'][0] if resp.get('Items') else None

start_ms = int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp() * 1000)
end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

events = []
next_token = None
for _ in range(10):
    kwargs = {
        'logGroupName': '/aws/ecs/notifly-services-prod/web-console/sentry',
        'startTime': start_ms,
        'endTime': end_ms,
        'limit': 100
    }
    if next_token:
        kwargs['nextToken'] = next_token
    resp = logs.filter_log_events(**kwargs)
    events.extend(resp.get('events', []))
    next_token = resp.get('nextToken')
    if not next_token:
        break

grouped = {}
for evt in events:
    try:
        msg = json.loads(evt['message'])
    except Exception:
        continue
    sa = msg.get('sentryAlert', {})
    issue = sa.get('issue', {})
    req = sa.get('request', {}) or {}
    if not isinstance(req, dict):
        req = {}
    url = req.get('url', '')
    title = issue.get('title', 'Unknown')
    txn = issue.get('transaction', 'Unknown')
    err_msg = issue.get('message', '')
    level = sa.get('level', '')
    issue_id = issue.get('id', '')

    # Skip info-level alerts unless asked to include them
    if level == 'info' or title == 'Slow DB Query':
        continue

    m = re.search(r'/products/([^/]+)', url)
    product_id = m.group(1) if m else ''

    key = issue_id or f'{title}|{txn}|{product_id}'
    if key not in grouped:
        proj = get_project(product_id)
        proj_name = proj.get('name', {}).get('S', product_id) if proj and isinstance(proj, dict) else product_id
        grouped[key] = {
            'title': title, 'txn': txn, 'msg': err_msg,
            'urls': set(), 'product_id': product_id,
            'project_name': proj_name, 'count': 0,
            'timestamps': [], 'issue_id': issue_id,
            'levels': set()
        }
    g = grouped[key]
    g['count'] += 1
    g['timestamps'].append(evt['timestamp'])
    if url:
        g['urls'].add(url)
    if level:
        g['levels'].add(level)

# Print summary sorted by most recent
for key, info in sorted(grouped.items(), key=lambda x: max(x[1]['timestamps']), reverse=True):
    latest = datetime.fromtimestamp(max(info['timestamps'])/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    earliest = datetime.fromtimestamp(min(info['timestamps'])/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    print(f"[{info['title']}] {info['count']}회 | Issue {info['issue_id']}")
    print(f"  Page: {info['txn']}")
    print(f"  Project: {info['project_name']} ({info['product_id']})")
    print(f"  Message: {info['msg'][:120]}")
    print(f"  First: {earliest} | Latest: {latest}")
    for u in list(info['urls'])[:2]:
        print(f"  URL: {u}")
```

## Logs Insights alternative (quick aggregate)

```sql
fields @timestamp, @message
| filter @message like 'sentryAlert'
| parse @message '"title":"*"' as issue_title
| parse @message '"transaction":"*"' as transaction
| parse @message '"message":"*"' as error_message
| parse @message '"url":"*"' as url
| parse @message '"level":"*"' as level
| stats count(*) as cnt by issue_title, transaction, error_message, level
| sort cnt desc
| limit 30
```

Note: `parse` is redundant for top-level JSON keys that Logs Insights auto-extracts; if a field already exists, rename the alias (e.g., `as parsed_level`) to avoid `Ephemeral field is already defined` errors.

## Scoping technique

- Extract `productId` from `request.url` or `tags.url`.
- **Critical pitfall**: `sentryAlert.project.id` (e.g., `4506086856196096`) is the **Sentry** project ID, not the Notifly project ID. Do not map it via DynamoDB.
- Map via DynamoDB GSI:

```bash
aws dynamodb query \
  --table-name project \
  --index-name product_id-project_id-index \
  --key-condition-expression "product_id = :v" \
  --expression-attribute-values '{":v":{"S":"hybiome"}}' \
  --projection-expression "id, #n, product_id, dev" \
  --expression-attribute-names '{"#n":"name"}' \
  --region ap-northeast-2
```

- **Duplicate-item pitfall**: the same `product_id` can appear twice (`dev: true` and `dev: false`). Use `dev = false` for production scope.

## Common Sentry payload patterns seen through this pipeline

- `SyntaxError` (`Unexpected token '<', "<!DOCTYPE "... is not valid JSON`) — Client-side JSON parse failure when an API returns HTML (502/504 gateway error page) instead of JSON. Often hits `/user-journey/[userJourneyId]/stats`. See multiple projects (munice, safedoc, class101).
- `Error` (`Failed to get user journey`) — Invalid `userJourneyId=undefined` in URL (class101).
- `Error` (`Failed to get user journey node statistics`) — Backend failure on user-journey stats (fint).
- `Error` (`문자 메시지 발신자 정보를 불러오는 중 오류가 발생했습니다.`) — SMS sender info load failure during campaign creation (weatherstone).
- `TypeError` (`Cannot read properties of undefined (reading 'h')`) — React/Next.js hydration error, usually on test/staging projects (`michael`).
- `TypeError` (`Failed to fetch (api-sr.amplitude.com)`) — Amplitude analytics API network error (break).
- `Error` (`Failed to parse stream string. No separator found.`) — Usually from `campaign/list`, occurs on localhost or stage (`michael`).
- `ReferenceError` (`$ is not defined`) — `/auth/login` or `/auth/signout` page script error.

## When to escalate vs stay as `no_action`

- Default status for this alarm family is `no_action` because the pipeline itself is healthy and individual Sentry issues are tracked in the Sentry (`greybox`) organization.
- Escalate to `needs_fix` only when:
  - A specific error title/transaction pair is **sharply increasing** across multiple production projects (not just test projects).
  - The Sentry issue volume itself indicates a real customer-facing regression (e.g., `SyntaxError` on stats page hitting many projects repeatedly).
- Never use `urgent` solely because this metric-filter alarm fired; the alarm fires on every Sentry alert arrival.
