# Sentry Email Alert Pipeline Analysis

Alarm family: `/aws/ecs/notifly-services-prod/web-console/sentry alert` (metric namespace `ConsoleErrors`).

**User intent correction**: This alarm is **intentional error logging**, not a Lambda crash, not a metric-filter false positive, and not a reason to investigate Lambda health. The `ops-email-receiver` Lambda receives Sentry alert emails via SES and writes parsed payloads to CloudWatch Logs. A broad `%ERROR%` metric filter matches literal strings inside the JSON payload (e.g., `"title":"SyntaxError"`, `"level":"error"`), so the alarm fires whenever any Sentry issue arrives. Do **not** treat the alarm itself as noise. The goal is to parse the actual Sentry payload and report:
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
- **API-endpoint shortcut**: For `POST /api/projects/{projectId}/...` or similar API route URLs in `request.url`, the path segment is the literal Notifly `project_id` (e.g., `api/projects/b2b4a8f879a75673b755bff42fc1deb6/test_send/kakao_brand_message`). Query DynamoDB `project` table directly by `id` when this pattern is detected, instead of searching for a `productId` slug. Mapping via `id` is more reliable and avoids GSI query misses when the URL does not contain a product slug.
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

## Scope recovery: campaign ID from `request.query` redirect parameter

When the Sentry issue originates at `/auth/login` (user was mid-flow and redirected to login), the `sentryAlert.request.query` field contains a URL-encoded `redirect=...` path that often embeds a campaign or user-journey ID:

- Example: `redirect=%2Fconsole%2Fproducts%2Fclass101%2Fcampaign%2Fcreate%3Fenvironment%3D1%26id%3DiViRLM%26mod…`
  → URL-decode → `/console/products/class101/campaign/create?environment=1&id=iViRLM`
  → productId=`class101`, campaignId=`iViRLM`

Parse logic:

```python
import re, urllib.parse
query_str = sa.get('request', {}).get('query', '') or ''
decoded = urllib.parse.unquote(query_str)
m = re.search(r'/products/([^/]+)/(?:campaign|user-journey)/[^/]+\?.*?id=([A-Za-z0-9]+)', decoded)
if m:
    product_id_from_redirect = m.group(1)
    campaign_or_uj_id = m.group(2)
```

Use this when `request.url` is `/auth/login` and does not contain a productId directly. The redirect path is the true scope evidence.

## Scope recovery: project_id from API route in `request.url`

When `sentryAlert.request.url` contains an API path like `https://console.notifly.tech/api/projects/<project_id>/test_send/...`, the path segment is the literal Notifly `project_id`. Query DynamoDB `project` table directly by `id` (more reliable than GSI lookup for these routes):

```python
resp = ddb.get_item(
    TableName='project',
    Key={'id': {'S': project_id}},
    ProjectionExpression='id, #n, product_id',
    ExpressionAttributeNames={'#n': 'name'}
)
```

## Preview/staging subdomain pattern

Sentry alerts from preview deploy URLs like `https://<branch-name>-console.notifly.tech/...` indicate staging/PR preview environment access, not production. Identify by the domain being anything **other than** bare `console.notifly.tech`. Treat as `no_action` by default unless the same error also appears on production.

## Scope recovery: user-journey from `req_url` field

When the triggering Sentry issue URL is `/console/products/<productId>/user-journey/<userJourneyId>`:

1. Extract `productId` from `req_url` (the `request.url` field in the Sentry payload, not the issue URL).
2. Map `productId` via DynamoDB GSI `product_id-project_id-index` → get `project_id` and `name`. Use `dev=false` item when both dev/prod exist.
3. Look up the `userJourneyId` in `user_journeys_<project_id>` (Postgres): `SELECT id, name, status, created_at FROM user_journeys_<project_id> WHERE id = '<id>' LIMIT 1`. `status=1` means active/enabled.
4. Include both the project name and the user-journey name + status in `범위:`.

**Example (2026-06-18):**
- `req_url = https://console.notifly.tech/console/products/tourlive/user-journey/Zq3Jac`
- productId=`tourlive` → project_id=`c73ff97bb627533785f06fa56345690d` (dev=false)
- `user_journeys_c73ff97bb627533785f06fa56345690d` → id=`Zq3Jac`, name=`테스트 여정`, status=1

## `get_log_events` on stream as fallback for empty `filter-log-events`

When `filter-log-events` returns empty results for the alarm window (even without a filter pattern), retrieve the stream name from `describe_log_streams` ordered by `lastIngestionTime` desc, then use `get_log_events` on that stream directly:

```python
logs.get_log_events(
    logGroupName='/aws/ecs/notifly-services-prod/web-console/sentry',
    logStreamName='sentry/YYYY/MM/DD/<stream-id>',
    limit=10,
    startFromHead=True
)
```

This bypasses CloudWatch's term-matching index. Each stream contains exactly one Sentry alert. The helper's `trigger_contexts` may also expose this data via `get_log_events` internally when the stream name is known.

## Common Sentry payload patterns seen through this pipeline

- `TypeError` (`Cannot read properties of undefined (reading 'replaceAll')`) — web-console user-journey 상세 페이지 (`/console/products/[productId]/user-journey/[userJourneyId]`) 렌더링 중 undefined 값에 `.replaceAll()` 호출. **New issue → `needs_fix`** 분류. Scope: tourlive / Zq3Jac "테스트 여정" (2026-06-18). 수정 위치: `apps/web-console` user-journey 상세 페이지 컴포넌트에서 `.replaceAll()` 호출 전 undefined guard 추가.
- `SyntaxError` (`Unexpected token '<', "<!DOCTYPE "... is not valid JSON`) — Client-side JSON parse failure when an API returns HTML (502/504 gateway error page) instead of JSON. Often hits `/user-journey/[userJourneyId]/stats`. See multiple projects (munice, safedoc, class101).
- `Error` (`Failed to get user journey`) — Invalid `userJourneyId=undefined` in URL (class101).
- `Error` (`Failed to get user journey node statistics`) — Backend failure on user-journey stats (fint).
- `Error` (`문자 메시지 발신자 정보를 불러오는 중 오류가 발생했습니다.`) — SMS sender info load failure during campaign creation (weatherstone).
- `TypeError` (`Cannot read properties of undefined (reading 'h')`) — React/Next.js hydration error, usually on test/staging projects (`michael`).
- `TypeError` (`Failed to fetch (api-sr.amplitude.com)`) — Amplitude analytics API network error (break).
- `Error` (`Failed to parse stream string. No separator found.`) — Usually from `campaign/list`, occurs on localhost or stage (`michael`).
- `Error` (`AI agent stream client response closed before completion`) — Web-console AI Agent proxy/stream disconnect. Tag `handled: yes` indicates it is a caught Sentry event, not an unhandled crash. Tag `feature: ai-agent`. Customer impact depends on whether the disconnect is transient (single user session) or recurring across many sessions. Daily volume is typically low (0–3).
- `Error` (`Unacceptable characters in title and body.`) at `POST /api/projects/[projectId]/test_send/kakao_brand_message` — Kakao BizMessage API rejects the test-send payload because the title or body contains invalid characters (e.g., unsupported Unicode or special symbols). Tag `handled: yes`. This is a client-side content validation error from the external Kakao SDK/API, not a service bug. Scope recovery: extract `project_id` from the API route path in `request.url` (e.g., `/api/projects/b2b4a8f879a75673b755bff42fc1deb6/test_send/kakao_brand_message`). Classify as `no_action` when isolated.
- `SyntaxError` (`"[object Object]" is not valid JSON`) at `PUT /api/projects/[projectId]/campaigns` — The campaign save API receives a raw JavaScript object instead of a JSON string. Tag `handled: yes`. Most commonly seen from `michael` (internal test/demo project, product_id=`michael`, project_id=`b80c3f0e2fbd5eb986df4f1d32ea2871`). Classify as `no_action` when confined to `michael`. If it appears for production projects, it may indicate a real serialization bug in campaign creation — look at `services/api-service/` campaign update path (note: this is a different code path from the `[object Object]` in `scheduled-batch-delivery` Lambda; see `references/scheduled-batch-delivery-dbinsert-json-serialization-bug.md`).
- `Slow DB Query` (Sentry `level: info`) — Sentry's performance monitoring sends slow DB query alerts as `info`-level events. The raw JSON payload still embeds `"error"` substrings in other field values (e.g., field names, interface type, or log message fragments), so the `%[Ee][Rr][Rr][Oo][Rr]%` metric filter matches and increments `ConsoleErrors`. This is a **false positive for error classification** — the payload signals a slow query, not an error. The transaction is typically a slow `SELECT ... user_journey_id ...` on a `user_journeys_<project_id>` or related stats table. Scope via `request.url` (e.g., `/api/projects/<project_id>/user_journeys/statistics`). Classify as `no_action`. When writing the aggregation Python recipe, skip `level == 'info'` or `title == 'Slow DB Query'` entries (see recipe above with `if level == 'info': continue`).
- `AxiosError` (`Network Error`) at `/auth/login` — Client network connectivity failure during login redirect. Common on mobile devices (iPhone/iOS) with unstable connections. Tag `handled: no`. Extract productId and campaign/user-journey ID from `request.query` redirect parameter (see "Scope recovery: campaign ID from redirect parameter" section). Classify as `no_action` for isolated mobile network errors; monitor if volume is rising across many users.
- `AxiosError` (`Network Error`) at `/console/admin/dashboard` — Client network connectivity failure while accessing the Notifly admin dashboard (`console.notifly.tech/console/admin/dashboard`). Typically surfaces as `status: "Ongoing issue"` (recurring). This is an internal-only admin page; no customer-facing impact. Scope: no productId in path → no DynamoDB mapping needed; campaign/user journey 특정 불가. Classify as `no_action`.
- `AxiosError` (`Network Error`) at `/console/products/[productId]/campaign/list` — Client network connectivity failure on the campaign list page. Scope: extract `productId` from `tags.url` or `request.url` (e.g., `https://console.notifly.tech/console/products/mom-sitter/campaign/list`) → map via DynamoDB GSI `product_id-project_id-index` (prefer `dev=false`). Typically iOS mobile device with unstable connection (`device: iPhone`, `os: iOS`, `mechanism: auto.browser.global_handlers.onunhandledrejection`). Tag `handled: no` — unhandled rejection but failure is client-side network, not a service bug. No `campaign_id` recoverable because the list API call itself failed. Classify as `no_action` for isolated occurrences; escalate to `needs_fix` only if volume rises sharply across multiple production projects.
- `NotFoundError` (`Failed to execute 'removeChild' on 'Node': The node to be removed is not a child of this node.`) at `/console/products/[productId]/campaign/create` — Browser-side React/Next.js virtual DOM mismatch during campaign creation page teardown or re-render. Sentry issue `7561927008` (first seen 2026-06-19, New issue). **Scope recovery**: Standard `request.url` scope recovery is unreliable for this issue type — the `request` object may be absent. However, the raw stream JSON (retrieved via `get_log_events`) often embeds `products/<productId>/campaign/create` inside `surrounding_lines`; use `re.findall(r'products/([a-zA-Z0-9_-]+)', full_stream_json)` on the raw event and map via DynamoDB GSI `product_id-project_id-index` (prefer `dev=False`). Confirmed example: HONGIN 프로덕션 프로젝트 (`product_id=HONGIN → id=ab53e7305afe560fb1183bc9b4f95d9b, dev=False`, 2026-06-19). Tag `handled: no`. Customer-facing: some users on campaign create page may see UI freeze or white screen on page transition. No server-side data loss. Classify as `no_action` when isolated (pipeline healthy, Sentry separately tracks in greybox org); `needs_fix` if frequency rises. Long-term fix: add null guard or explicit DOM cleanup in the campaign create page component before `removeChild` call.
- `Error` (`Cannot find module 'google-spreadsheet' Require stack: - /app/services/server/web-console/.next/server/...`) at `GET /api/projects/[projectId]/campaigns/[campaignId]/iplusn-cost-savings` — Server-side Next.js API route fails because `google-spreadsheet` is not bundled in the `.next` build. Sentry issue `7561945552` (first seen 2026-06-11 after PR #3741, confirmed 2026-06-19). **Root cause (confirmed)**: `iplusn-cost-savings.ts` imports `@notifly/pricing` → `PriceTagRepository` → `google-spreadsheet`. The `google-spreadsheet` package is declared in `packages/pricing/package.json` `dependencies`, but as a transitive dep of a local workspace package it is not automatically bundled by Next.js. The module is absent from the production `.next/server/` bundle. This is **not** a `devDependencies` misconfiguration — it is a pnpm monorepo transitive dep bundling gap. See `references/web-console-iplusn-cost-savings-module-not-found.md` for the full dependency chain, fix direction, and alarm history. **Scope recovery**: Payload does not contain a literal projectId; scope is all callers of the I+N cost-savings feature. **Customer impact**: The cost-savings card API returns 500 for all I+N campaigns — feature completely unavailable. **Action**: Add `@notifly/pricing` to `next.config.js` `transpilePackages`, or lazy-import only the pricing sub-path that does not require `google-spreadsheet`. Classify as `needs_fix`.
- `Error` (`select "campaign_id", event_name AS metric_name, TO_CHAR(DATE_TRUNC('hour', created_at), 'YYYY-MM...`) at `GET /api/projects/[projectId]/campaigns/[campaignId]/stats` — Backend SQL error on campaign stats API endpoint. Sentry issue `7359055823` (Ongoing issue, doctornow prod, 2026-06-23). The `issue.message` field contains the raw SQL query fragment that failed. **Scope recovery**: `request.url` contains the API path `https://console.notifly.tech/api/projects/<project_id>/...` — extract `project_id` directly from the path and query DynamoDB `project` table by `id` (not GSI). Confirmed: `91a042a79e4c5c4fa3af7c3d3b5aaf53` → doctornow (dev=false). The `delivery_result_<project_id>` table reference in the same payload cross-validates the scope. No `campaignId` value is recoverable from the payload (only the route parameter name). Classify as `no_action` for the CloudWatch alarm (Sentry pipeline proxy); track the SQL error in Sentry greybox org.

## When to escalate vs stay as `no_action`

- Default status for this alarm family is `no_action` because the pipeline itself is healthy and individual Sentry issues are tracked in the Sentry (`greybox`) organization.
- Check the `handled` tag in the Sentry payload (`"handled":"yes"` vs `"handled":"no"`). `handled: yes` means the error was caught and reported intentionally (e.g., an expected AI agent disconnect); `handled: no` or absent means an unhandled crash and should be reviewed more carefully.
- Escalate to `needs_fix` only when:
  - A specific error title/transaction pair is **sharply increasing** across multiple production projects (not just test projects).
  - The Sentry issue volume itself indicates a real customer-facing regression (e.g., `SyntaxError` on stats page hitting many projects repeatedly).
- Never use `urgent` solely because this metric-filter alarm fired; the alarm fires on every Sentry alert arrival.

## Pitfalls learned from live sessions

### `filter-log-events --filter-pattern 'ERROR'` can return 0 while the metric filter still matched

CloudWatch Logs `filter-log-events` uses **term matching** for bare keywords like `ERROR`. The metric filter `%[Ee][Rr][Rr][Oo][Rr]%` uses substring (case-insensitive) matching. JSON payload strings such as `"title":"Error"` may tokenize in ways that prevent a standalone `ERROR` term match, so `filterPattern='ERROR'` produces zero results even though the metric filter counted the line.  
**Remediation**: when the alarm `StateReasonData` confirms a datapoint but `filter-log-events --filter-pattern 'ERROR'` returns empty, fall back to an **unfiltered** `filter-log-events` bounded to the exact alarm window and parse the raw messages manually, or use Logs Insights with `filter @message like 'Error'`.

### `organizationSlug` is a Sentry organization name, not a Notifly `product_id`

The Sentry payload contains `organizationSlug` (e.g., `greybox`). This is the **Sentry** organization, not a Notifly product slug. Querying DynamoDB `project` table with `product_id = greybox` returns zero items. The correct Notifly product ID must be extracted from `request.url` or `tags.url` (e.g., `/console/products/<productId>/...`). Do not confuse the two identifiers.

### `describe_alarm_history` OK→ALARM may be zero even though the alarm is currently in ALARM

`describe_alarm_history` only counts explicit `StateUpdate` history items. If the alarm transitioned from `INSUFFICIENT_DATA → ALARM` (never reaching `OK`) or if the helper's default lookback is too short, `alarm_count_7d: 0` is normal.

**This alarm family always follows `INSUFFICIENT_DATA → ALARM → INSUFFICIENT_DATA` cycles**, not `OK → ALARM → OK`. Because the metric filter emits a value of `1` only on match (default_value=0) and the evaluation window is 1 minute with no sustained traffic, the alarm never reaches `OK` — it returns to `INSUFFICIENT_DATA` between Sentry alert arrivals. Counting `OK→ALARM` transitions from alarm history will return 0 and is misleading; use INSUFFICIENT_DATA→ALARM transitions or the metric daily Sum instead.

**Helper note (2026-06-23)**: The helper now correctly counts `INSUFFICIENT_DATA → ALARM` transitions via `HistoryData` parsing (per the SKILL.md `StateValue: null` pitfall workaround). For this alarm family, the helper returns non-zero counts (e.g., `alarm_count_30d: 62`, `alarm_count_7d: 23`, `alarm_count_1d: 8`, `alarm_count_10m: 2`) and correctly flags `rapid_recurrence.status: "rapid"`. These counts are reliable for the `빈도` field. The previous recommendation to "prefer the metric daily Sum over alarm-history transition counts" is no longer strictly necessary when the helper returns non-zero values, but the metric daily Sum remains a valid cross-check.

```python
client.get_metric_statistics(
    Namespace='ConsoleErrors',
    MetricName='/aws/ecs/notifly-services-prod/web-console/sentry alert',
    StartTime=now - timedelta(days=N),
    EndTime=now,
    Period=86400,
    Statistics=['Sum']
)
```

Use the resulting daily `Sum` values for the `빈도` field.

### Logs Insights `%pattern%` syntax vs `filter-log-events` syntax mismatch

CloudWatch Logs API uses two **incompatible** pattern syntaxes:

- **Logs Insights**: uses `%pattern%` for substring matching (case-insensitive). Example: `%[Ee][Rr][Rr][Oo][Rr]%` matches any case variation of "error". This syntax is used in the Logs Insights query language and in metric filter definitions.
- **`filter-log-events` API**: does NOT accept `%pattern%` syntax. It uses either a bare term (e.g., `filterPattern='ERROR'`) or term-list syntax (e.g., `filterPattern='[ERROR or WARN]'`). Passing `%[Ee][Rr][Rr][Oo][Rr]%` to `filter-log-events` raises `InvalidParameterException: Invalid filter pattern`.

**Pitfall**: The metric filter on this log group is `%[Ee][Rr][Rr][Oo][Rr]%` (Logs Insights substring syntax). When investigating the alarm, do NOT copy this pattern directly to `filter-log-events`. Instead:
1. Use **Logs Insights queries** directly (recommended for aggregate counts and structured JSON parsing).
2. Or use an **unfiltered** `filter-log-events` call (omit `filterPattern`) and parse all messages in the window manually.
3. Or use a simplified `filterPattern` like `'ERROR'` (bare term), but understand it may match fewer events than the metric filter because term matching is stricter than substring matching.

**Remediation**: for Sentry payload analysis, always prefer Logs Insights over `filter-log-events`. Logs Insights supports the same substring syntax and integrates seamlessly with JSON parsing (`parse`, `fields`, and `stats`).
