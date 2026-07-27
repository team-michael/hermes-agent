# Sentry Email Alert Pipeline Analysis

Alarm family: `/aws/ecs/notifly-services-prod/web-console/sentry alert` (metric namespace `ConsoleErrors`).

**STOP — mandatory step before writing `no_action` for this alarm family**: Ctrl-F this file's "Common Sentry payload patterns" catalog for the current issue's exact `title` + `transaction`/route BEFORE composing the final answer, every time, even when the helper says `can_answer_root_cause: true` and even when the individual project's own 7d/30d count looks low/isolated. `can_answer_root_cause: true` only means the current-window log evidence was found — it says nothing about whether this exact bug already hit a *different* Notifly production project on an earlier date. Skipping this check is the single most common way this alarm family gets misclassified `no_action` when the correct answer is `needs_fix` (confirmed miss: 2026-07-06, `qmarket`/`DTBLUX` `replaceAll` TypeError — the catalog already documented the identical `tourlive`/`Zq3Jac` occurrence from 2026-06-18 and said the next hit should be `needs_fix`, but the live session classified it `no_action` anyway because the catalog was never opened before answering). If a match is found on another production project, classify `needs_fix` regardless of this project's own low count, and append the new occurrence to the existing bullet.

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

**Generalized signal — synthetic/automated-probe hostnames**: the same "not-bare-`console.notifly.tech`" rule also catches non-preview synthetic hostnames used by internal test/automation tooling, e.g. `https://codex-type-non-product-route-queries-console.notifly.tech/...` (a Codex/agent-style generated test hostname, seen 2026-07-09 hitting `GET /cafe24/initialize` with `Error: Required query param is missing.`). These are not git-branch preview deploys, but the same identification rule applies: any hostname other than the bare production `console.notifly.tech` (or a known customer custom domain) is internal/synthetic traffic, not real customer usage. Root cause for this specific error: `createParam(...).required()` in `services/server/web-console/src/utils/query-params.ts:71` throws `Error: Required query param is missing.` whenever a page's required query-param helper receives no value — this is the generic defensive-validation guard used across web-console pages, not a `/cafe24/initialize`-specific bug. Classify `no_action` when the calling host is a synthetic/test hostname and no other ERROR patterns co-occur; only escalate if the same guard starts firing from the bare production console domain with real customer traffic.

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

## Helper `table_refs` as scope source when Sentry payload is truncated

The helper's `current_trigger_contexts[].trigger` and `current_error_details[].likely_error` fields truncate the Sentry JSON at ~200 characters with `...`. When `request.url` falls outside the truncated window, the normal scope recovery path (extract `productId` or `project_id` from the URL) is not available from the helper output alone. However, the helper's `table_refs` array in the same context object extracts sharded table references from the full (untruncated) log line and carries the `project_id` directly:

```json
"table_refs": [
  {
    "table_family": "delivery_result",
    "project_id": "91a042a79e4c5c4fa3af7c3d3b5aaf53",
    "table_pattern": "delivery_result_<project_id>"
  }
]
```

Use `table_refs[0].project_id` to query DynamoDB `project` table by `id` (not GSI) when the Sentry payload URL is truncated. This avoids needing a separate `get_log_events` call just to read the full `request.url`.

## Logs Insights direct JSON field access (preferred over `parse`)

CloudWatch Logs Insights auto-extracts nested JSON fields using dot notation. For the Sentry pipeline log group, fields like `sentryAlert.issue.id`, `sentryAlert.issue.title`, `sentryAlert.issue.transaction`, and `sentryAlert.status` are directly available in queries without any `parse` clause. This is simpler and more reliable than glob `parse` or regex `parse` for nested fields.

**7-day issue distribution query** (preferred for frequency analysis):

```sql
fields @timestamp, sentryAlert.issue.id, sentryAlert.issue.title, sentryAlert.issue.transaction, sentryAlert.status
| filter @message like "Received Sentry email alert"
| stats count() by sentryAlert.issue.id, sentryAlert.issue.title, sentryAlert.issue.transaction
| sort count desc
| limit 20
```

This returns one row per distinct Sentry issue with its occurrence count in the window. Use it to quickly assess whether the current trigger is a recurring issue or a new one, and whether multiple distinct issues are firing on the same day.

**30-day daily count query** (for baseline establishment):

```sql
fields @timestamp
| filter @message like "Received Sentry email alert"
| stats count() by bin(1d)
| sort @timestamp asc
| limit 31
```

Use the daily counts to compute the 30-day average and compare the current day count against the baseline. This is a Logs Insights alternative to `get_metric_statistics` with `Period=86400` and works directly on log events rather than metric datapoints.

The earlier `parse`-based queries (glob and regex) below remain valid but are no longer the preferred approach. Prefer direct dot-notation field access when the log payload is structured JSON.

## Logs Insights regex `parse` for nested JSON field aggregation (legacy)

The earlier Logs Insights template uses `"*"` glob parse syntax (`parse @message '"title":"*"' as issue_title`), which works for top-level JSON keys that Logs Insights auto-extracts. For nested fields like `sentryAlert.issue.id` (inside `issue: {...}`), glob parse may not reliably extract values. Use regex-delimited `parse` with named captures instead:

```sql
fields @timestamp, @message
| filter @message like /"title":"([^"]+)"/
| parse @message /"id":"(?<issue_id>[^"]+)","title":"(?<issue_title>[^"]+)"/
| stats count() as cnt by issue_id, issue_title
| sort cnt desc
| limit 50
```

This successfully aggregates all distinct Sentry issues by ID and title across a 7-day window for the `빈도` field frequency distribution.

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
  - **Recurrence (2026-07-06)**: Same title+transaction pair fired again — different Sentry issue id `7520113669`, different project `qmarket` (product_id=`qmarket`, dev=false), different user journey `DTBLUX`, minified frame `10647-981be35bfc0b938c.js`. `sentryAlert.status` was `"Ongoing issue"` (Sentry itself has already seen this exact issue id before, i.e. not brand-new from Sentry's perspective), which makes it easy to read as "just another isolated occurrence" and default to `no_action`. **That read is wrong for this alarm-response purpose**: the escalation rule below cares about the *title+transaction pair* recurring across distinct production projects, not about whether Sentry's own dedup considers the specific issue id new. tourlive (6/18) and qmarket (7/6) are two different production projects hitting the identical unguarded `.replaceAll()` call on the identical user-journey detail page route. Per the "When to escalate" rule (same title/transaction pair increasing across multiple production projects), this pair has now crossed that threshold and should be classified `needs_fix`, not `no_action`, on its second production-project occurrence — even though each individual project's own count is still low (1 hit). Fix target unchanged: the user-journey detail page component's `.replaceAll()` call needs an undefined guard; this is now confirmed as a repeat production-impacting client bug, not a one-off. **CONFIRMED MISS**: a live Slack-alert-response session on 2026-07-06 classified this exact occurrence `no_action` because it did not open/search this reference file before answering — it reasoned only from this session's own 30d/7d/1d/10m frequency count (4 hits, sporadic) and never cross-checked the catalog for the same signature on another project. Corrected status for any future recurrence of this pair: `needs_fix`.
- `SyntaxError` (`Unexpected token '<', "<!DOCTYPE "... is not valid JSON`) — Client-side JSON parse failure when an API returns HTML (502/504 gateway error page) instead of JSON. Often hits `/user-journey/[userJourneyId]/stats`. See multiple projects (munice, safedoc, class101).
- `Error` (`Failed to get user journey`) — Invalid `userJourneyId=undefined` in URL (class101).
- `Error` (`Failed to get user journey node statistics`) — Backend failure on user-journey stats (fint).
- `Error` (`문자 메시지 발신자 정보를 불러오는 중 오류가 발생했습니다.`) — SMS/Kakao sender info load failure during campaign creation or edit. Seen on weatherstone and zippoom (issue `7572207308`, 2026-07-02, `handled: yes`, transaction `/console/products/[productId]/campaign/create`, campaign edit mode `?id=<campaignId>&mode=edit`). Each occurrence so far has been a distinct new Sentry issue tied to a different project, low volume (1-2 hits/30d per project) — classify as `no_action` per-occurrence. If this exact error title recurs across 3+ distinct production projects within a 30-day window, treat it as a systemic sender-info-fetch API flakiness (not per-project bad data) and escalate to `needs_fix`: the shared code path is the campaign create/edit page's sender-info fetch call, not a project-specific config issue.
- `TypeError` (`Cannot read properties of undefined (reading 'h')`) — React/Next.js hydration error, usually on test/staging projects (`michael`).
- `TypeError` (`Failed to fetch (api-sr.amplitude.com)`) — Amplitude analytics API network error (break).
- `Error` (`Failed to parse stream string. No separator found.`) — Usually from `campaign/list`, occurs on localhost or stage (`michael`).
- `Error` (`AI agent stream client response closed before completion`) — Web-console AI Agent proxy/stream disconnect. Tag `handled: yes` indicates it is a caught Sentry event, not an unhandled crash. Tag `feature: ai-agent`. Customer impact depends on whether the disconnect is transient (single user session) or recurring across many sessions. Daily volume is typically low (0–3).
- `Error` (`Unacceptable characters in title and body.`) at `POST /api/projects/[projectId]/test_send/kakao_brand_message` — Kakao BizMessage API rejects the test-send payload because the title or body contains invalid characters (e.g., unsupported Unicode or special symbols). Tag `handled: yes`. This is a client-side content validation error from the external Kakao SDK/API, not a service bug. Scope recovery: extract `project_id` from the API route path in `request.url` (e.g., `/api/projects/b2b4a8f879a75673b755bff42fc1deb6/test_send/kakao_brand_message`). Classify as `no_action` when isolated.
- `Error` (`Unacceptable characters in title and body.`) at `PUT /api/projects/[projectId]/campaigns` — same validator, different call site: campaign **save/upsert** (not test-send). Stack frame `chunks/71260.js`, `CampaignService.upsertCampaign → MessageTransformer.transform`. Scope recovery is the same technique (extract `project_id` from `tags.api.route`/`request.url` path segment, e.g. `/api/projects/b2b4a8f879a75673b755bff42fc1deb6/campaigns`), and in this case the same Sentry issue id (`7545407593`) has been re-firing on the same project (`class101`) since at least 2026-06-12 — treat repeat firings of the *same issue id* on the *same project* as a known recurring case, not escalating severity; do not conflate this with the cross-project escalation rule below, which is about the same title+transaction hitting *different* projects. See `references/web-console-campaign-validation-errors.md` for the full validator-family writeup (this pattern is #3 alongside the Kakao-link and SMS-length validators sharing the same `CampaignService.upsertCampaign → MessageTransformer.transform` pipeline). Classify as `no_action` — single-datapoint alarm (`Threshold: 1.0`, `EvaluationPeriods: 1`) recovers to `INSUFFICIENT_DATA` immediately after, handled validation rejection, no data loss, no message sent.
- `SyntaxError` (`"[object Object]" is not valid JSON`) — **confirmed root cause (2026-07-08): a `JSON.parse(req.body)` / `JSON.parse(params)` anti-pattern shared across web-console Next.js API routes, not an api-service issue.** Next.js's default body parser already deserializes a `Content-Type: application/json` request body into an object before the handler runs. Any route that then calls `JSON.parse(req.body)` again coerces the object to the literal string `"[object Object]"` and throws this exact `SyntaxError` on the second parse. Do **not** point at `services/api-service/` for this signature — trace the exact web-console route from `sentryAlert.issue.transaction` / `request.url` instead.
  - **First occurrence**: `PUT /api/projects/[projectId]/campaigns` (2026-06-18), seen mostly on `michael` (internal test/demo project, product_id=`michael`, project_id=`b80c3f0e2fbd5eb986df4f1d32ea2871`). Originally classified `no_action` when confined to `michael`.
  - **Recurrence #2**: `POST /api/kakao/alimtalk/template` (2026-07-03, web-console).
  - **Recurrence #3**: `POST /api/kakao/alimtalk/templates` (2026-07-08, web-console) — traced to `services/server/web-console/src/pages/api/kakao/alimtalk/templates.ts:8` (`const { platform, platform_params } = JSON.parse(params)` where `params = req.body`).
  - **Code-pattern audit**: the identical `JSON.parse(req.body)` / `JSON.parse(params)` pattern is present in at least 7 files under `services/server/web-console/src/pages/api/kakao/alimtalk/`: `templates.ts`, `template.ts`, `create_template.ts`, `delete_template.ts`, `sender_profiles.ts`, `upload_template_img.ts`, `platforms/notifly/senders/[senderKey]/templates/[templateId]/comments_with_files.ts`. Any of these can throw the same signature depending on caller `Content-Type`/body shape.
  - **Escalation rule for this signature**: this is the same "mandatory catalog cross-check" logic as the `replaceAll` TypeError entry above — do not classify a new hit as `no_action` just because it is a "new issue" on a different route. Three hits across three distinct routes in three weeks (6/18, 7/3, 7/8) is a worsening, recurring structural bug class → classify `needs_fix` on the third and any subsequent occurrence, with the action item being a repo-wide sweep of the `kakao/alimtalk/*` routes to remove the redundant `JSON.parse()` call (use `req.body` directly). Reserve `no_action` only for the very first isolated hit before the pattern was known to recur.
  - Unrelated: this is a different code path from the `[object Object]` serialization bug in the `scheduled-batch-delivery` Lambda; see `references/scheduled-batch-delivery-dbinsert-json-serialization-bug.md` for that one.
- `Slow DB Query` (Sentry `level: info`) — Sentry's performance monitoring sends slow DB query alerts as `info`-level events. The raw JSON payload still embeds `"error"` substrings in other field values (e.g., field names, interface type, or log message fragments), so the `%[Ee][Rr][Rr][Oo][Rr]%` metric filter matches and increments `ConsoleErrors`. This is a **false positive for error classification** — the payload signals a slow query, not an error. The transaction is typically a slow `SELECT ... user_journey_id ...` on a `user_journeys_<project_id>` or related stats table. Scope via `request.url` (e.g., `/api/projects/<project_id>/user_journeys/statistics`). Classify as `no_action`. When writing the aggregation Python recipe, skip `level == 'info'` or `title == 'Slow DB Query'` entries (see recipe above with `if level == 'info': continue`).
- `AxiosError` (`Network Error`) at `/auth/login` — Client network connectivity failure during login redirect. Common on mobile devices (iPhone/iOS) with unstable connections. Tag `handled: no`. Extract productId and campaign/user-journey ID from `request.query` redirect parameter (see "Scope recovery: campaign ID from redirect parameter" section). Classify as `no_action` for isolated mobile network errors; monitor if volume is rising across many users.
- `AxiosError` (`Network Error`) at `/console/admin/dashboard` — Client network connectivity failure while accessing the Notifly admin dashboard (`console.notifly.tech/console/admin/dashboard`). Typically surfaces as `status: "Ongoing issue"` (recurring). This is an internal-only admin page; no customer-facing impact. Scope: no productId in path → no DynamoDB mapping needed; campaign/user journey 특정 불가. Classify as `no_action`.
- `AxiosError` (`Network Error`) at `/console/products/[productId]/campaign/list` — Client network connectivity failure on the campaign list page. Scope: extract `productId` from `tags.url` or `request.url` (e.g., `https://console.notifly.tech/console/products/mom-sitter/campaign/list`) → map via DynamoDB GSI `product_id-project_id-index` (prefer `dev=false`). Typically iOS mobile device with unstable connection (`device: iPhone`, `os: iOS`, `mechanism: auto.browser.global_handlers.onunhandledrejection`). Tag `handled: no` — unhandled rejection but failure is client-side network, not a service bug. No `campaign_id` recoverable because the list API call itself failed. Classify as `no_action` for isolated occurrences; escalate to `needs_fix` only if volume rises sharply across multiple production projects.
- `NotFoundError` (`Failed to execute 'removeChild' on 'Node': The node to be removed is not a child of this node.`) at `/console/products/[productId]/campaign/create` — Browser-side React/Next.js virtual DOM mismatch during campaign creation page teardown or re-render. Sentry issue `7561927008` (first seen 2026-06-19, New issue). **Scope recovery**: Standard `request.url` scope recovery is unreliable for this issue type — the `request` object may be absent. However, the raw stream JSON (retrieved via `get_log_events`) often embeds `products/<productId>/campaign/create` inside `surrounding_lines`; use `re.findall(r'products/([a-zA-Z0-9_-]+)', full_stream_json)` on the raw event and map via DynamoDB GSI `product_id-project_id-index` (prefer `dev=False`). Confirmed example: HONGIN 프로덕션 프로젝트 (`product_id=HONGIN → id=ab53e7305afe560fb1183bc9b4f95d9b, dev=False`, 2026-06-19). Tag `handled: no`. Customer-facing: some users on campaign create page may see UI freeze or white screen on page transition. No server-side data loss. Classify as `no_action` when isolated (pipeline healthy, Sentry separately tracks in greybox org); `needs_fix` if frequency rises. Long-term fix: add null guard or explicit DOM cleanup in the campaign create page component before `removeChild` call.
- `Error` (`Cannot find module 'google-spreadsheet' Require stack: - /app/services/server/web-console/.next/server/...`) at `GET /api/projects/[projectId]/campaigns/[campaignId]/iplusn-cost-savings` — Server-side Next.js API route fails because `google-spreadsheet` is not bundled in the `.next` build. Sentry issue `7561945552` (first seen 2026-06-11 after PR #3741, confirmed 2026-06-19). **Root cause (confirmed)**: `iplusn-cost-savings.ts` imports `@notifly/pricing` → `PriceTagRepository` → `google-spreadsheet`. The `google-spreadsheet` package is declared in `packages/pricing/package.json` `dependencies`, but as a transitive dep of a local workspace package it is not automatically bundled by Next.js. The module is absent from the production `.next/server/` bundle. This is **not** a `devDependencies` misconfiguration — it is a pnpm monorepo transitive dep bundling gap. See `references/web-console-iplusn-cost-savings-module-not-found.md` for the full dependency chain, fix direction, and alarm history. **Scope recovery**: Payload does not contain a literal projectId; scope is all callers of the I+N cost-savings feature. **Customer impact**: The cost-savings card API returns 500 for all I+N campaigns — feature completely unavailable. **Action**: Add `@notifly/pricing` to `next.config.js` `transpilePackages`, or lazy-import only the pricing sub-path that does not require `google-spreadsheet`. Classify as `needs_fix`.
- `Error` — **`pg` `Query read timeout` family under Sentry issue `7359055823`** (Ongoing issue). **Pitfall — same Sentry issue id can carry different `transaction`/`message` text over time**: this issue id has been observed with at least two different transaction/SQL pairs: (a) `GET /api/projects/[projectId]/campaigns/[campaignId]/stats` with SQL starting `select "campaign_id", event_name AS metric_name, TO_CHAR(DATE_TRUNC('hour', created_at), 'YYYY-MM...` (doctornow, 2026-06-23), and (b) `GET /api/projects/[projectId]/delivery-results` with SQL starting `select "delivery_result".*, "user_table"."external_user_id" from (select ... from "delivery_result_<project_id>" ... left join "users_<project_id>" ...) - Query read timeout` (11 hits on doctornow between 2026-06-08 and 2026-07-08, then first hit on **regather** `b57754a9497a545ab9b0e4aadd6f53b6` on 2026-07-10). Sentry groups by stack trace/fingerprint (the `pg` client's `Query read timeout` throw site in `node_modules/pg/lib/client.js:536`), not by literal query text, so don't be surprised when the exact SQL differs between occurrences of the same issue id — treat this issue id as a **query-timeout root cause class** on `delivery_result_<project_id>` / `message_events_<project_id>` / `campaign_statistics_<project_id>`-family sharded tables, not a single fixed query.
  - **Scope recovery**: `request.url` contains the API path `https://console.notifly.tech/api/projects/<project_id>/...` — extract `project_id` directly from the path and query DynamoDB `project` table by `id` (not GSI). Confirmed mappings: `91a042a79e4c5c4fa3af7c3d3b5aaf53` → doctornow (dev=false, prod), `b57754a9497a545ab9b0e4aadd6f53b6` → regather (dev=false, prod). Sharded table refs (`delivery_result_<project_id>`, `message_events_<project_id>`, `users_<project_id>`) in the same payload cross-validate scope. No `campaignId` value is recoverable from the payload (bound as a query parameter, not embedded in the SQL text log).
  - **Frequency**: 17 hits across 30 days as of 2026-07-10 (Logs Insights `stats count() by sentryAlert.issue.id`), heavily concentrated on doctornow (11/12 most recent hits) with the 2026-07-10 hit being the *first* on a second production project (regather).
  - **Classification — escalated to `needs_fix` on 2026-07-10**: this crossed from "isolated single-project recurring issue" (previously `no_action`) to "same root-cause query-timeout class now hitting a second production project" — apply the same cross-project escalation logic as the `replaceAll` TypeError entry below even though the exact SQL/transaction text differs, because the underlying fingerprint (issue id `7359055823`, `pg` `Query read timeout`) is identical. Action item: `EXPLAIN ANALYZE` the delivery-results subquery (`delivery_result_<project_id>` filtered by `created_at`/`event_name` with an `EXISTS` subquery against `message_events_<project_id>` on `event_params->>'notifly_message_id'` / `event_params->>'user_journey_id'`) to check for a missing index on `message_events_<project_id>.event_params` (GIN/expression index candidate) before the next occurrence. If a third distinct production project hits this issue id, treat it as confirmed systemic and prioritize the index fix over further per-occurrence triage.
- `TypeError` (`Cannot read properties of undefined (reading '<product_id_slug>.kr')`) at `/console/products/[productId]/settings` — Client-side crash where the exception message's "property name" is literally the custom-domain-shaped string `<productSlug>.kr` (e.g., `tripstore.kr`), not a generic field name like `'key'` or `'replaceAll'`. This is a strong signal the settings page code indexes a lookup object/map (likely a per-project custom-domain or sender-domain config) using a domain-string key, and that object/map is `undefined` for this project. Sentry issue `7520438852` (web-console, `handled: yes`, 2026-07-02). `request.url` was `https://console.notifly.tech/console/products/<productId>/settings` — extract `productId` directly from the path segment (here `tripstore`) rather than `request.query`; map via DynamoDB GSI `product_id-project_id-index` (prefer `dev=false`). Volume was low (3 hits/30d, first seen 3 days before triage) and isolated to one project — treat as `needs_fix` (non-urgent tracked bug) rather than `no_action` when it is a **new** signature (first seen within the trailing few days) even at low volume, since `handled: yes` + low volume alone don't prove it's benign business logic like the other settings-page entries above — it looks like a real undefined-guard bug on the settings page rather than an external-provider rejection. Exact TS source line could not be pinned from the repo because the stack trace only references the minified production bundle (`settings-<hash>.js`); no source maps are checked into `notifly-event`. Next step if this recurs: pull the exact stack trace/source map from the Sentry issue UI (`greybox` org, issue id) rather than trying to grep the minified bundle reference out of the repo.

- `NotFoundError` (`The object can not be found here.`) at `/console/products/[productId]/analytics/events` — Client-side DOM exception (`DOMException code 8`, i.e. `NotFoundError` on `Node.removeChild`-family DOM APIs) while viewing the analytics/events page. Sentry issue `7589777645` (New issue, `handled: yes`, 2026-07-02), seen on `browser: Chrome Mobile iOS`, `device: iPhone`. Scope recovery: `request.url` directly contains `https://console.notifly.tech/console/products/<productId>/analytics/events` — extract `productId` (here `regather`) and map via DynamoDB GSI `product_id-project_id-index` (prefer `dev=false`). This is the same virtual-DOM-mismatch-on-render family as the `removeChild` issue documented above, just a different page (`analytics/events` instead of `campaign/create`) and a different DOM exception subtype. `handled: yes` + isolated single occurrence → classify as `no_action`.

- `TransformError` (`Inserted content deeper than insertion position`) at `/console/products/[productId]/in-app-message/new` — Client-side rich-text editor exception (Slate.js-family `TransformError`) while creating a new in-app-message. Sentry issue `7591052690` (New issue, `handled: no`, 2026-07-03), `request.url = https://console.notifly.tech/console/products/<productId>/in-app-message/new`. Scope recovery: extract `productId` directly from `request.url` path segment (here `fint`) and map via DynamoDB GSI `product_id-project_id-index` (prefer `dev=false`). `handled: no` + single new occurrence, no other ERROR patterns co-occurring → classify as `no_action` (pipeline healthy, Sentry tracks the issue separately). If this same title/transaction recurs across the same or multiple projects, treat it as an editor content-insertion bug in the in-app-message rich-text component and escalate to `needs_fix`.

- `Error` (`No error message`) at `/console/products/[productId]/kakao-brand-message-template/[templateId]/edit` — Client-side minified React Query cache-accessor failure (`n.getById` in `app:///_next/static/chunks/99498-af70dfce7cb41a66.js`, called from a `queryFn` in `3959-*.js`) while opening the Kakao brand-message template edit page. `issue.message` is literally the string `"No error message"` — the thrown `Error` object carries no message, so this alone gives no server-traceable detail; the stack only references minified production bundle chunks, no source maps checked into `notifly-event`. Sentry issue `7602988153` (New issue, `handled: yes`, 2026-07-10). Scope recovery: `request.url` contains `/console/products/<productId>/kakao-brand-message-template/<templateId>/edit` — extract `productId` (here `lifezip`) and map via DynamoDB GSI `product_id-project_id-index` (prefer `dev=false`). Single new occurrence, `handled: yes`, no other ERROR patterns co-occurring → classify `no_action`. If this same title+transaction recurs (same or different project), treat it as a real `getById` cache-miss/undefined-response bug in the template edit page's data-fetch hook and escalate to `needs_fix`; next step would be pulling the exact stack trace/source map from the Sentry issue UI since the repo has no source maps for this chunk.

- `Error` (`Required query param is missing.`) at `GET /cafe24/initialize` (and potentially other web-console pages using the same required-query-param helper) — Generic defensive validation error thrown by `createParam(...).required()` in `services/server/web-console/src/utils/query-params.ts:71` whenever a page's required query parameter is absent from the request. Sentry issue `7601311839` (New issue, `handled: no`, 2026-07-09), `request.url = https://codex-type-non-product-route-queries-console.notifly.tech/cafe24/initialize` — the calling host is a synthetic/automation test hostname (Codex/agent-style generated subdomain), not a real customer session. Scope: no real Notifly project/campaign/user-journey involved; the request itself is a probe missing the expected Cafe24 init query param. Classify as `no_action` — this is expected defensive-code behavior against a malformed/incomplete synthetic request, not a service bug. Escalate to `needs_fix` only if the same error starts firing from the bare production `console.notifly.tech` domain with real customer traffic (would indicate a genuine broken link/redirect generating requests without the required param).

- `TypeError` (`Failed to fetch (www.google.com)`) at `/console/products/[productId]/users` — Client-side unhandled `fetch` rejection to `www.google.com` (likely a Google resource such as reCAPTCHA/analytics beacon blocked by ad-blocker or network extension). Sentry issue `7621493640` (New Alert, `handled: no`, `mechanism: auto.browser.global_handlers.onunhandledrejection`, 2026-07-20). `request.url = https://console.notifly.tech/console/products/<productId>/users` — extract `productId` (here `break`) and map via DynamoDB GSI `product_id-project_id-index` (prefer `dev=false`). Single isolated occurrence on one production project, no server-side data loss → classify `no_action`. Escalate to `needs_fix` only if this exact title+transaction recurs sharply across multiple production projects (same logic as other external-domain-fetch client network errors above).

## Retrieving the full untruncated Sentry payload when `current_error_details` truncates before scope-bearing fields

The helper's `logs.current_error_details[].trigger`/`likely_error` fields truncate the raw JSON at roughly 200 characters with `...`. For DB-shaped Sentry issues, the truncation point is usually late enough that `table_refs`/`project_ids` still populate. But for **client-side** Sentry issues (browser exceptions, DOM errors, network errors with no DB table reference), the truncation frequently cuts off before `request.url`/`tags.url`/`project.id` appear, and `table_refs`/`project_ids`/`campaign_ids` are all empty — the SKILL.md-recommended structured-field fallback has nothing to fall back to.

**Fix**: `current_error_details[]` always carries `log_group`, `log_stream`, and `timestamp` even when `trigger`/`likely_error` are truncated. Use those three fields to pull the exact untruncated event directly:

```bash
aws logs get-log-events --region ap-northeast-2 \
  --log-group-name '<log_group from current_error_details>' \
  --log-stream-name '<log_stream from current_error_details>' \
  --start-time <timestamp_ms - 1000> \
  --end-time <timestamp_ms + 90000> \
  --output json
```

Since each Sentry-pipeline log stream contains exactly one alert email, this reliably returns the full JSON payload (`sentryAlert.issue`, `sentryAlert.request.url`, `sentryAlert.tags`) in one read-only call — no Logs Insights query needed, no risk of the `filter-log-events` term-matching false-negative described below. Parse `request.url` for the `productId` path segment as usual.

## When to escalate vs stay as `no_action`

- Default status for this alarm family is `no_action` because the pipeline itself is healthy and individual Sentry issues are tracked in the Sentry (`greybox`) organization.
- Check the `handled` tag in the Sentry payload (`"handled":"yes"` vs `"handled":"no"`). `handled: yes` means the error was caught and reported intentionally (e.g., an expected AI agent disconnect); `handled: no` or absent means an unhandled crash and should be reviewed more carefully.
- Escalate to `needs_fix` only when:
  - A specific error title/transaction pair is **sharply increasing** across multiple production projects (not just test projects).
  - The Sentry issue volume itself indicates a real customer-facing regression (e.g., `SyntaxError` on stats page hitting many projects repeatedly).
- Never use `urgent` solely because this metric-filter alarm fired; the alarm fires on every Sentry alert arrival.

**Mandatory cross-check before finalizing as `no_action`**: This reference file is a running catalog of past `title`+`transaction` pairs with project/date. Before classifying a new Sentry issue as `no_action` on the reasoning "this issue id is new/isolated," search this catalog (Ctrl-F the error title or route) for the same `title`+`transaction` on a *different* project. Sentry's own `sentryAlert.status` field (`"New issue"` vs `"Ongoing issue"`) reflects Sentry's dedup within one org/project — it does NOT tell you whether the same bug already hit a different Notifly production project before. If a match exists on a different production project, the pair has already crossed the "recurring across multiple production projects" threshold in the rule above — classify as `needs_fix`, not `no_action`, even though this individual project's own count is still 1. Always append the new occurrence (project, date, issue id) to the existing bullet rather than creating a duplicate entry, so the next session's search finds full history in one place. (Concrete miss: the `replaceAll` TypeError on the user-journey page was logged for `tourlive` on 2026-06-18 and, without cross-checking this file, was initially misclassified `no_action` again for `qmarket` on 2026-07-06 instead of `needs_fix`.)

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

### Single-datapoint alarm (`Threshold: 1.0`, `EvaluationPeriods: 1`) — go straight to `filter_log_events` on the exact minute, skip Logs Insights entirely

When `describe-alarms` shows `Threshold: 1.0` and `EvaluationPeriods: 1` for this alarm, exactly one Sentry email produced the breach. The helper's `logs.current_error_details`/`current_trigger_contexts` are commonly empty for these single-event alarms because Logs Insights ingestion lags the metric-filter evaluation by tens of seconds to a few minutes — do not wait for the helper's Logs Insights query to populate. Instead, jump directly to a bounded `filter_log_events` call anchored on the alarm's `stateReasonData` breach minute (from `describe-alarms` → `StateReason`, e.g. `"1.0 (09/07/26 10:13:00)"` converted to epoch ms), with a ±60s buffer:

```python
resp = logs.filter_log_events(
    logGroupName='/aws/ecs/notifly-services-prod/web-console/sentry',
    startTime=breach_epoch_ms - 60000,
    endTime=breach_epoch_ms + 120000,
    limit=50,
)
```

For a single-datapoint alarm this reliably returns exactly one event containing the full untruncated Sentry JSON — no need for `get_log_events`/stream lookup, no need for a Logs Insights query at all. Cross-check that the alarm has already returned to `INSUFFICIENT_DATA` (confirms it was a one-off single-minute spike, not sustained) before finalizing as `no_action`.
