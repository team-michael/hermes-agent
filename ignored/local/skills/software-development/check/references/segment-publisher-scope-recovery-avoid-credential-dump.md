# Segment-Publisher Scope Recovery — Avoid Dumping FCM/APNs Credentials

Applies to: `/aws/ecs/notifly-services-prod/segment-publisher slow eic query`
(Pattern A: `EventCounterCteManager.extract:{project_id} took too long: {ms}ms`)
and any other segment-publisher alarm where campaign/user-journey scope must
be recovered from the log stream.

## The pitfall

The trigger line (`EventCounterCteManager.extract:{project_id} took too
long`) only carries `project_id`. To get `campaign_id`/`schedule_type` the
obvious next step is `get_log_events` on the same stream/window and reading
the `Received event: {...}` JSON line that precedes it. **Do not do this.**
That payload embeds the full FCM service-account credential blob
(base64-encoded private keys under `fcm_service_account.ios` /
`fcm_service_account.android`) and can also carry APNs certs. Printing or
even scratch-copying that line violates the "never print raw CloudWatch log
dumps" / "never expose secrets" rules in the parent `check` skill.

## The fix — targeted filter instead of full stream read

Recover scope with a narrow `filter-log-events` call scoped to the exact
alarm window, matching only on `"schedule_type"`, then regex out just the two
safe fields:

```bash
aws logs filter-log-events --region ap-northeast-2 \
  --log-group-name '/aws/ecs/notifly-services-prod/segment-publisher' \
  --start-time <ms> --end-time <ms> \
  --filter-pattern '"schedule_type"' \
  --query 'events[].message' --output json \
  | python3 -c "import sys,json,re; [print(m.group(0)) for l in json.load(sys.stdin) for m in re.finditer(r'\"campaign_id\":\"[^\"]+\"|\"schedule_type\":\"[^\"]+\"', l)]"
```

This returns lines like:

```
"campaign_id":"nxmfsB"
"schedule_type":"campaign"
```

Map the `project_id` from the trigger line via DynamoDB `project` as usual;
the `campaign_id` recovered this way pairs directly with it since both come
from the same alarm-window SQS payload (`Received event`).

## General rule

For ANY log line known to embed credential/secret material (service account
keys, API tokens, signed URLs, sender auth), never widen the read to the full
line just to extract one benign adjacent field. Use a second, narrower
`filter-log-events` call with a distinguishing substring pattern for the
field(s) you actually need, then regex-extract only those fields client-side.
This generalizes beyond segment-publisher to any Notifly log stream that logs
full `Received event` / provider credential payloads verbatim.
