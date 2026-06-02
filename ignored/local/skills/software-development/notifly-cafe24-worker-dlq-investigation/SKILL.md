---
name: notifly-cafe24-worker-dlq-investigation
description: Investigate Notifly cafe24-worker SQS retry/DLQ behavior using live AWS data, aggregate DLQ payloads by mall and command, map malls to project/product, and correlate prolonged Cafe24 429s with queue bursts.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [notifly, cafe24, sqs, dlq, cloudwatch, boto3, debugging]
    related_skills: [aws-cloudwatch-debugging-via-boto3, systematic-debugging]
---

# Notifly cafe24-worker DLQ Investigation

Use when the user asks things like:
- "cafe24-worker retry 제대로 안 되고 DLQ 쌓이나?"
- "cafe24-worker-queue-dlq 상태/원인 봐줘"
- "DLQ를 mall_id / command 기준으로 집계해줘"
- "왜 특정 mall에서 429가 오래 가는지 파봐"

This is a live-ops investigation workflow for `team-michael/notifly-event`.

## What this workflow is for

The goal is to separate three possibilities:
1. retry logic is broken
2. retry logic works, but repeated Cafe24 429s exhaust SQS receive budget and move messages to DLQ
3. DLQ is old residue and not actively growing now

The reusable pattern:
- inspect live SQS state
- sample and aggregate actual DLQ payloads
- map `mall_id -> project_id -> product_id/name`
- correlate with CloudWatch logs and SQS metrics
- distinguish current growth vs historical backlog

## Important repository/system facts

- `cafe24-worker` consumes from `cafe24-worker-queue`
- DLQ is `cafe24-worker-queue-dlq`
- `cafe24_integration` DynamoDB table maps `mall_id -> project_id`
- `project` table maps `id -> product_id, name`
- `products` table can be queried for product metadata if needed
- Worker logs are in `/aws/lambda/cafe24-worker`
- **User table naming**: `@notifly/userdb` rewrites `user_${projectId}` → `users_${projectId}` (encrypted dual-write), but raw queries via `@notifly/common`'s `executeQuery` do not. See `cafe24-worker` code in `lib/db.js` (especially `deleteCafe24Users`).

## Related alarm: `cafe24-worker lambda error` (ConsoleErrors, not DLQ)

The same Lambda also has a ConsoleErrors alarm driven by metric filter `%ERROR|Status: timeout%`. One known false-positive signature is:

```
ERROR  Failed to delete <mallId> from notifly, error: error: relation "user_<project_id>" does not exist
```

### Why this is a false positive
- Lambda `Errors = 0`, `Throttles = 0`.
- The error is caught in `lib/jobs/delete.js` `deleteMall()` inside a `try...catch` and logged with `console.error`.
- The metric filter catches the literal string `ERROR`, not a runtime failure.

### Root cause
`lib/db.js` `deleteCafe24Users` sends two DELETE queries. The first uses `@notifly/userdb` `executeWriteQueryToUserTable`, which rewrites the legacy `user_${projectId}` table name to `users_${projectId}`. The second query (device deletion with a subquery) calls `db.executeQuery` directly, bypassing the dual-write layer and sending the raw `user_${projectId}` name to Postgres. Projects created after the encryption migration only have `users_${projectId}`, so the subquery fails with `relation does not exist`.

### Scope extraction
Same as DLQ: extract `project_id` from the table suffix in the log line, map via DynamoDB `project`.

### Classification
- `no_action` when sporadic (handled rejection, Errors=0).
- `needs_fix` when recurrent, because the device-cleanup query should reference `users_${projectId}` or route through `@notifly/userdb`.

## Step 1 — Verify live queue state

Use boto3 from `terminal`, not `execute_code`, because AWS creds are available in shell env.

```bash
python - <<'PY'
import boto3, os
session=boto3.Session(
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    aws_session_token=os.environ.get('AWS_SESSION_TOKEN'),
    region_name=os.environ.get('AWS_DEFAULT_REGION','ap-northeast-2'),
)
sqs=session.client('sqs')
for name,url in [
  ('main','https://sqs.ap-northeast-2.amazonaws.com/702197142747/cafe24-worker-queue'),
  ('dlq','https://sqs.ap-northeast-2.amazonaws.com/702197142747/cafe24-worker-queue-dlq'),
]:
    attrs=sqs.get_queue_attributes(
        QueueUrl=url,
        AttributeNames=['ApproximateNumberOfMessages','ApproximateNumberOfMessagesNotVisible','ApproximateNumberOfMessagesDelayed']
    )['Attributes']
    print(name, attrs)
PY
```

Interpretation:
- main=0, dlq>0 → old residue / historical failures possible
- main>0 and DLQ also growing → active issue
- DLQ visible stable over hours + oldest age increasing → residue not being redriven

## Step 2 — Sample and aggregate DLQ payloads

To inspect actual messages without deleting them, use `receive_message` with a short `VisibilityTimeout`.

### Single-message sample

```bash
python - <<'PY'
import boto3, os, json
session=boto3.Session(
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    aws_session_token=os.environ.get('AWS_SESSION_TOKEN'),
    region_name=os.environ.get('AWS_DEFAULT_REGION','ap-northeast-2'),
)
sqs=session.client('sqs')
resp=sqs.receive_message(
    QueueUrl='https://sqs.ap-northeast-2.amazonaws.com/702197142747/cafe24-worker-queue-dlq',
    MaxNumberOfMessages=1,
    VisibilityTimeout=5,
    WaitTimeSeconds=2,
    AttributeNames=['All'],
)
print(json.dumps(resp, ensure_ascii=False, indent=2, default=str))
PY
```

### Full aggregation pattern

Fetch up to the known visible count in batches and aggregate by `mall_id`, `command`, sent minute, and payload shape.

```bash
python - <<'PY'
import boto3, os, json, datetime, collections
session=boto3.Session(
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    aws_session_token=os.environ.get('AWS_SESSION_TOKEN'),
    region_name=os.environ.get('AWS_DEFAULT_REGION','ap-northeast-2'),
)
sqs=session.client('sqs')
url='https://sqs.ap-northeast-2.amazonaws.com/702197142747/cafe24-worker-queue-dlq'
seen={}
for _ in range(15):
    resp=sqs.receive_message(
        QueueUrl=url,
        MaxNumberOfMessages=10,
        VisibilityTimeout=60,
        WaitTimeSeconds=2,
        AttributeNames=['All'],
    )
    msgs=resp.get('Messages',[])
    if not msgs:
        break
    for m in msgs:
        seen[m['MessageId']]=m

by_mall=collections.Counter()
by_command=collections.Counter()
by_pair=collections.Counter()
for m in seen.values():
    body=json.loads(m['Body'])
    mall=body.get('mall_id')
    command=body.get('command')
    by_mall[mall]+=1
    by_command[command]+=1
    by_pair[(mall,command)]+=1
print('by_mall', by_mall.most_common())
print('by_command', by_command.most_common())
print('by_pair', by_pair.most_common())
PY
```

### Useful extra aggregations

- `ApproximateReceiveCount` from message attributes → confirms these are DLQ-bound after retry exhaustion
- `SentTimestamp` minute bucket → identifies a burst window
- `params.case_text` for `points_updated` → reveals event subtype
- payload key shape → good for spotting one command family dominating the DLQ

## Step 3 — Map malls to project/product

DLQ payloads may not contain `project_id`. For cafe24-worker, resolve through DynamoDB.

```bash
python - <<'PY'
import boto3, os, json
session=boto3.Session(
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    aws_session_token=os.environ.get('AWS_SESSION_TOKEN'),
    region_name=os.environ.get('AWS_DEFAULT_REGION','ap-northeast-2'),
)
ddb=session.resource('dynamodb')
integration=ddb.Table('cafe24_integration')
project_table=ddb.Table('project')
products=ddb.Table('products')
for mall in ['drlabnosh','chosunhnb']:
    item=integration.get_item(
        Key={'mall_id': mall},
        ProjectionExpression='mall_id, project_id, #st',
        ExpressionAttributeNames={'#st':'status'}
    ).get('Item')
    out={'mall_id': mall, 'integration': item}
    pid=item.get('project_id') if item else None
    if pid:
        p=project_table.get_item(
            Key={'id': pid},
            ProjectionExpression='id, product_id, #nm',
            ExpressionAttributeNames={'#nm':'name'}
        ).get('Item')
        out['project']=p
        if p and p.get('product_id'):
            out['product']=products.get_item(
                Key={'product_id': p['product_id']},
                ProjectionExpression='product_id, #nm',
                ExpressionAttributeNames={'#nm':'name'}
            ).get('Item')
    print(json.dumps(out, ensure_ascii=False, indent=2))
PY
```

Report discovered `project_id` together with product info, per user preference.

## Step 4 — Correlate with CloudWatch Logs

### Before blaming a new DLQ alarm, check whether the alarm itself is new

A very reusable failure mode is:
- the DLQ backlog already existed
- a CloudWatch alarm for that DLQ was only created later
- the freshly created alarm immediately enters `ALARM` on the pre-existing backlog

So if the user says "DLQ just appeared" because Slack only alerted now, check CloudWatch alarm configuration history first.

Use `describe_alarm_history(..., HistoryItemType='ConfigurationUpdate')` on the DLQ alarm and compare:
- alarm creation timestamp
- first `INSUFFICIENT_DATA/OK -> ALARM` timestamp
- current DLQ visible count

If the alarm creation is recent while the DLQ count is already non-zero, interpret the notification as:
- **new alerting on old residue**, not necessarily a fresh incident.

### Best tool: `filter_log_events`

For this case, `filter_log_events` is often simpler and more reliable than Logs Insights, especially when query syntax gets finicky around `bin(...)`.

Patterns to search:
- `"will retry via SQS"`
- `"[Cafe24 Quota]"`
- `"backed off via Redis"`
- `"rate limited. Waiting"`

Example: pull retry events in a suspect window and aggregate mall counts locally in Python.

```bash
python - <<'PY'
import boto3, os, json, datetime, re, collections
session=boto3.Session(
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    aws_session_token=os.environ.get('AWS_SESSION_TOKEN'),
    region_name=os.environ.get('AWS_DEFAULT_REGION','ap-northeast-2'),
)
logs=session.client('logs')
start_ms=int(datetime.datetime(2026,4,20,20,15,tzinfo=datetime.timezone.utc).timestamp()*1000)
end_ms=int(datetime.datetime(2026,4,21,1,30,tzinfo=datetime.timezone.utc).timestamp()*1000)
kwargs=dict(
    logGroupName='/aws/lambda/cafe24-worker',
    startTime=start_ms,
    endTime=end_ms,
    filterPattern='"will retry via SQS"'
)
events=[]
while True:
    resp=logs.filter_log_events(**kwargs)
    events.extend(resp.get('events', []))
    token=resp.get('nextToken')
    if not token or token==kwargs.get('nextToken'):
        break
    kwargs['nextToken']=token
mall_re=re.compile(r'rate-limited for ([^,]+), will retry via SQS')
by_mall=collections.Counter()
for e in events:
    m=mall_re.search(e['message'])
    if m:
        by_mall[m.group(1)] += 1
print(json.dumps(by_mall.most_common(), ensure_ascii=False, indent=2))
PY
```

### What to look for

- first and last retry log per mall → how long quota lock persisted
- counts per mall in the burst window
- whether logs are all `rate-limited` vs mixed with generic failures
- evidence of `30s` waits repeated many times
- evidence of `Redis backoff` sharing quota state across worker instances
- whether there are actually any raw `ERROR` or `Status: timeout` lines in the same window

Important operational nuance:
- the `cafe24-worker lambda error` alarm is driven by the metric filter `%ERROR|Status: timeout%`
- a window full of handled quota/rate-limit retries can therefore produce **zero lambda-error alerts** even while messages are exhausting SQS retries into the DLQ
- if `will retry via SQS` is high but `ERROR`/`Status: timeout` is zero, explain clearly that this is a handled retry-path failure mode, not an unhandled Lambda crash

## Step 5 — Correlate with SQS metrics

Use CloudWatch metrics to prove whether there was a burst and whether messages stuck in-flight.

Useful metrics on `cafe24-worker-queue`:
- `NumberOfMessagesSent`
- `NumberOfMessagesReceived`
- `NumberOfMessagesDeleted`
- `ApproximateNumberOfMessagesVisible`
- `ApproximateNumberOfMessagesNotVisible`

Example minute-level query around a suspected spike:

```bash
python - <<'PY'
import boto3, os, json, datetime
session=boto3.Session(
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    aws_session_token=os.environ.get('AWS_SESSION_TOKEN'),
    region_name=os.environ.get('AWS_DEFAULT_REGION','ap-northeast-2'),
)
cw=session.client('cloudwatch')
start=datetime.datetime(2026,4,20,20,20,tzinfo=datetime.timezone.utc)
end=datetime.datetime(2026,4,20,20,30,tzinfo=datetime.timezone.utc)
queries=[]
for qid,metric,stat in [
    ('sent','NumberOfMessagesSent','Sum'),
    ('received','NumberOfMessagesReceived','Sum'),
    ('deleted','NumberOfMessagesDeleted','Sum'),
    ('visible','ApproximateNumberOfMessagesVisible','Maximum'),
    ('notvisible','ApproximateNumberOfMessagesNotVisible','Maximum'),
]:
    queries.append({
        'Id': qid,
        'MetricStat': {
            'Metric': {'Namespace':'AWS/SQS','MetricName':metric,'Dimensions':[{'Name':'QueueName','Value':'cafe24-worker-queue'}]},
            'Period':60,
            'Stat':stat,
        },
        'ReturnData': True,
    })
resp=cw.get_metric_data(MetricDataQueries=queries, StartTime=start, EndTime=end, ScanBy='TimestampAscending')
print(json.dumps(resp['MetricDataResults'], ensure_ascii=False, indent=2, default=str))
PY
```

Interpretation pattern that mattered in practice:
- `Sent`/`Received` spike hard in one minute
- `Deleted` much lower than `Received`
- `NotVisible` jumps and stays high for minutes
- later DLQ receives the subset that exhausted receive attempts

This indicates **worker is running**, but a large burst caused repeated rate-limit deferrals and only some messages completed within retry budget.

## Practical findings worth checking first

These concrete patterns have already shown up and are highly reusable:

### Historical DLQ residue case
- DLQ visible count: `102`
- Aggregation result:
  - `drlabnosh`: 71
  - `chosunhnb`: 31
  - commands: `points_updated` 101, `add_user` 1
- `points_updated` payloads mostly had:
  - `case_text = "주문시 구매한 상품에 대한 적립금 부여(구매에 대한 적립금)"`
- 101 of 102 messages were sent in the same minute bucket
- retry logs lasted about one hour for the dominant malls
- This strongly suggested a **single burst of purchase-point events**, not a permanently broken consumer

### Current active 429 case
- `inertia22` showed new retry logs on a later day
- This means the issue pattern can recur by mall and is not only historical residue

## Root-cause extension: trace the upstream producer and propose mitigations

After confirming the DLQ composition and retry evidence, trace the producer path to answer **why prolonged 429s happen**.

### Producer path for `points_updated`

In Notifly, Cafe24 webhook events are accepted by API service and immediately enqueued to the cafe24 worker queue:

- `services/server/api-service/lib/api/webhook/index.js`
  - `/webhook/cafe24`
  - reads `event_no` and `resource`
  - maps `90148 -> points_updated`
  - calls `dispatchJob(mallId, command, resource)`
- `services/server/api-service/lib/api/webhook/cafe24/dispatch.js`
  - uses `process.env.SQS_CAFE24_WORKER_QUEUE_URL`
  - builds `{ mall_id, command, params }`
  - sends directly to SQS
- `services/server/api-service/lib/api/webhook/cafe24/sqs.js`
  - `DelaySeconds` default is `0`
  - no dedupe, no batching, no mall-aware throttling

This means a webhook burst is translated almost 1:1 into SQS messages.

### Consumer path for `points_updated`

The worker handles `points_updated` by doing a fresh Cafe24 API read per event:

- `services/lambda/cafe24-worker/lib/jobs/users.js`
  - `handlePointsUpdated(mallId, params)`
  - extracts `member_id`, `shop_no`
  - calls `delegate.getCustomer(shopNo, memberId, POINTS_PROPERTY_KEYS)`
  - then updates Notifly user properties

This is the key mechanism: **one `points_updated` event can become one Cafe24 customer lookup**.

### Relevant worker throttling knobs

- Lambda event source mapping in Terraform:
  - `batch_size = 5`
  - `scaling_maximum_concurrency = 16`
- Cafe24 API wrapper:
  - per-process limiter: `1 req/sec` per mall in local memory
  - Redis backoff only after 429 is observed
  - long waits are delegated back to SQS retry

Important experiential finding:
- the in-memory limiter is **instance-local**, not globally mall-serialized
- with many Lambda instances, total mall request rate can still exceed Cafe24 quota
- Redis backoff helps after quota is already blown, but does not absorb the initial burst

### Practical burst signatures already observed

These are worth checking and citing because they point directly to the mitigation:

- API service log group `/aws/ecs/notifly-services-prod/api-service`
- filter pattern: `"Received command: points_updated"`

Observed reusable patterns:

1. **Apr 21 purchase-points burst**
   - ~1079 `points_updated` webhook logs in one minute bucket
   - dominant malls: `drlabnosh`, `chosunhnb`
   - dominant `case_text`: purchase-point credit (`주문시 구매한 상품에 대한 적립금 부여...`)
   - worker retry logs then persisted for about an hour

2. **Apr 24 membership-grade burst**
   - ~252 `points_updated` logs in a 5-minute window
   - dominant mall: `inertia22`
   - dominant `case_text`: membership-grade point credit (`주문시 회원등급에 따른 적립금 부여...`)
   - same prolonged 429 pattern reappeared

3. **Duplicates are not the whole story**
   - some bursts include duplicate `(mall_id, member_id)` pairs
   - but even when duplicates are low, a single mall can still produce enough unique member events to overload quota
   - therefore member-level dedupe alone is helpful but not sufficient

### Recommended mitigations

Present mitigations in priority order and distinguish hotfix vs structural fix.

## Root-cause framing to state explicitly

When the evidence matches the common pattern, summarize the root cause precisely as:

- `points_updated` bursts arrive per mall
- Cafe24 quota is also enforced effectively per mall
- but the system admits work with global SQS/Lambda concurrency instead of mall-scoped serialization
- each `points_updated` message triggers a fresh `getCustomer()` read
- therefore the concurrency control boundary does not match the external quota boundary

This is sharper than saying only "there were many 429s".
The reusable formulation is:

**quota is mall-local, but admission control is global**.

That mismatch is the structural root cause. Retry/backoff may still be working correctly, but they are only mitigating a burst that should have been shaped before it hit Cafe24.

#### P0 — Best practical fix: split `points_updated` into a dedicated queue/worker

Why:
- isolates the noisiest command from other Cafe24 work
- allows much lower concurrency without slowing all commands

Recommended shape:
- new queue like `cafe24-points-worker-queue`
- route only `points_updated` to it
- separate worker / event source mapping with conservative settings:
  - `batch_size = 1` or `2`
  - `scaling_maximum_concurrency = 1` or `2`

#### P1 — Fast hotfix: lower current worker concurrency

If queue split cannot happen immediately:
- lower `scaling_maximum_concurrency` from `16` to `2~4`
- consider lowering `batch_size` from `5` to `1~2`

This is a blunt instrument: it reduces quota pressure quickly but slows every command type.

#### P2 — Add producer-side jitter / delay for `points_updated`

In API service producer path:
- apply small random `DelaySeconds` to `points_updated`
- spreads point-credit bursts that currently hit in the same minute

This is burst smoothing, not true load reduction.

#### P3 — Remove or collapse the per-event Cafe24 read

Highest long-term leverage:
- avoid calling `getCustomer()` for every `points_updated`
- either use webhook payload directly where sufficient
- or collapse many `(mall_id, member_id, shop_no)` updates into one delayed refresh job

Important nuance from real data:
- duplicate member events exist, but not enough to explain the whole load spike
- so dedupe/collapse is valuable, but mall-level burst shaping is still required

#### P4 — Ideal architecture: serialize by `mall_id`

If redesign is acceptable:
- use a FIFO queue with `MessageGroupId = mall_id`
- same mall becomes serialized, different malls remain parallel
- this aligns system concurrency with the external quota boundary

#### P5 — Be careful with DLQ redrive

Do not aggressively redrive old DLQ residue before mitigation is in place.
Otherwise you can recreate the same burst against the same mall and re-poison the queue.

## How to summarize conclusions

A strong answer should separate:

1. **DLQ composition**
   - by `mall_id`
   - by `command`
   - by time bucket
   - include `project_id` + product for each mall where discovered

2. **Retry health**
   - is retry logic firing at all?
   - are logs mostly `rate-limited ... will retry via SQS`?
   - if yes, retry is alive

3. **Root cause hypothesis**
   - most likely: per-mall Cafe24 quota saturation due to burst volume
   - more precisely: mall-scoped external quota is being hit by globally admitted worker concurrency
   - not likely: completely broken retry path

4. **Current vs historical state**
   - DLQ may contain old residue while main queue is healthy now
   - check whether DLQ visible count is stable or growing

5. **Purge vs redrive decision**
   - do not recommend purge only because DLQ is old
   - first verify root cause is actually fixed
   - then prefer controlled redrive over purge when `points_updated` is a state-sync style job
   - for `handlePointsUpdated`, the worker re-reads current Cafe24 customer points state rather than applying a raw delta, so post-fix redrive is often safer than purge
   - before recommending any destructive purge, sample whether DLQ member pairs later show successful `Successfully updated points for mallId ... memberId ...` logs; if many DLQ pairs still lack later success evidence, purge risks silent data loss

## Pitfalls

- `receive_message` on DLQ changes visibility temporarily. Keep `VisibilityTimeout` short.
- If a first `receive_message` returns empty even though attributes say messages exist, retry with small `WaitTimeSeconds`; SQS approximate counts are not perfectly fresh.
- Logs Insights `bin(...)` syntax can be annoying from API calls. Prefer `filter_log_events` + local Python aggregation unless you really need Insights.
- Product table may not always have a friendly `name`; still report `project_id`, project name, and product_id.
- Do not assume `project_id` is present in the DLQ payload. In practice it may need mall-based lookup via `cafe24_integration`.

## Output template

Use this shape for user-facing summaries:

- DLQ total count
- `mall_id / command` aggregation
- project mapping:
  - `mall_id` → `project_id`, project name, product_id
- timing:
  - dominant sent minute / burst window
- retry evidence from logs
- conclusion:
  - retry working vs broken
  - likely reason for prolonged 429s
