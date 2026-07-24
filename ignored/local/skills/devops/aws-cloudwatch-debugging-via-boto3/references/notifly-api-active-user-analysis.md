# Notifly API active-user analysis from live logs

Use this when asked to estimate active users for a customer/project hitting `api.notifly.tech`, especially when the question says "all logs", "active users", "DAU/MAU-ish", or asks broadly rather than a single endpoint.

## Sources and what each proves

1. **Project inventory**
   - Confirm all project IDs for the customer/product in DynamoDB `project` first.
   - This prevents undercounting customers with prod/stage/migrated project IDs.

2. **Application CloudWatch logs — best for Notifly user IDs**
   - Log group: `/aws/ecs/notifly-services-prod/api-service`.
   - `http-metrics` EMF logs include `ProjectId`, `NormalizedPath`, `RawPath`, `StatusCode`, `RequestDuration` for requests that reach `api-service`.
   - For user-facing active users, union distinct users from:
     - `/user-state/:projectId/:userId?` by parsing `RawPath` `/user-state/<projectId>/<userId>`
     - `sse-connection-opened` logs by `projectId` + `notiflyUserId`
   - Useful windows: 5m now-ish, 15m stable current active, 1h short-term active, 6h half-day trend, 24h DAU-like.

Logs Insights pattern:

```sql
fields ProjectId, projectId, RawPath, NormalizedPath, notiflyUserId, message
| filter (ProjectId in ["<projectId1>", "<projectId2>"] and NormalizedPath="/user-state/:projectId/:userId?")
    or (projectId in ["<projectId1>", "<projectId2>"] and message="sse-connection-opened")
| parse RawPath "/user-state/*/*" as pidPath, userPath
| fields coalesce(ProjectId, projectId) as pid, coalesce(userPath, notiflyUserId) as uid
| stats count(*) as events, count_distinct(uid) as unionUniqueUsers by pid
| sort events desc
```

3. **Endpoint mix and latency**
   - Aggregate `RequestCount` EMF rows by `ProjectId`, `NormalizedPath`, `StatusCode`.
   - `/sdk-configurations` is useful traffic context but not a user identity signal; do not count it as users.

4. **Cloudflare GraphQL analytics — best for edge-only failures and client/IP shape**
   - Query `httpRequestsAdaptiveGroups` filtered by `clientRequestHTTPHost: "api.notifly.tech"` and path prefix like `/user-state/<projectId>%`.
   - Pull groups by `edgeResponseStatus`, `originResponseStatus`, method, cache status, IP/country/OS/device.
   - Interpretation: `edgeResponseStatus=504`, `originResponseStatus=0`, very low edge TTFB/origin duration means the request failed before origin response; not an `api-service` handler 5xx.

5. **ALB access logs and metrics — verify origin reality**
   - Prod ALB access log bucket observed in Terraform: `notifly-api-service-access-logs`.
   - Cross-check `AWS/ApplicationELB` metrics: `HTTPCode_ELB_5XX_Count`, `HTTPCode_Target_5XX_Count`, `TargetConnectionErrorCount`, `TargetResponseTime`.
   - If ALB access logs show only 200/204 and no ELB/target 5xx while Cloudflare shows 504, report the split explicitly: “origin까지 도달한 성공 사용자” vs “edge에서 실패한 시도”.

## Reporting shape

- Lead with the number: “현재 15분 활성은 약 N명, 5분 now-ish는 M명.”
- Show broader windows: 5m / 15m / 1h / 6h / 24h.
- State the exact definition: successful `api-service` logs with user IDs from user-state + SSE open events.
- Add the edge caveat only if present: Cloudflare edge failures may imply additional attempted users but should not be counted as successful active users unless path-level distinct user IDs can be recovered and deduped.

## Pitfalls

- Do not count `/sdk-configurations` as users.
- Do not use Athena `notifly_event_logs` for very fresh “current” analysis unless partitions are known current; app logs are the live source.
- Do not equate Cloudflare 504 with `api-service` 5xx. Cross-check ALB target/ELB metrics and access logs.
- CloudWatch `count_distinct` is approximate; label it as approximate.
- 24h unique from API paths is DAU-like, not necessarily canonical product DAU.
