# Customer trend analysis notes

Use this reference when a user asks for a latest trend analysis for a specific Notifly customer/product rather than a pasted CloudWatch alert.

## Durable workflow

1. Resolve product/project safely.
   - Search the product registry by product_id/name when possible.
   - Use the non-dev project unless the user explicitly asks for a dev project.
   - Keep project IDs in working notes; Slack summaries may include them only when operationally useful.

2. Determine time windows in KST.
   - Latest completed day: yesterday KST unless a fresher complete partition/stat window is proven.
   - For partial “today” checks, compare same elapsed KST time against previous days, not full-day baselines.
   - Prefer trailing 28-day median for broad “latest trend”; use 7-day same-elapsed or same weekday as a secondary guard.

3. Start with aggregate/project-channel trend, then decompose by observed concentration.
   - Do **not** make push the default first-priority path. Prioritize whichever channel/source/resource explains the largest delta.
   - Channel first: Kakao Brand/Friendtalk/Alimtalk, text, email, webhook, in-app/in-web, push, etc.
   - Resource second: campaign vs user journey, then top campaign_id/user_journey_id/node contributors by absolute delta.
   - Context third: campaign/UJ names, status, timing, audit lifecycle events around the anomaly window.

4. Cross-check aggregate vs raw/freshness before making impact claims.
   - S3 `raw-events-query-logs/metrics/channel-daily/dt=YYYY-MM-DD/result.jsonl` is useful for quick daily channel counts, but older objects may not exist in the bucket. If the S3 baseline is sparse, use PG `delivery_result_${project_id}` and/or statistics tables for longer baselines.
   - PG `delivery_result_${project_id}` gives send_success/send_failure by KST day, channel, resource_type, campaign_id, and failure rate.
   - `campaign_statistics_${project_id}` and `user_journey_statistics_${project_id}` help identify failure reason groups and conversion metrics.

5. For large campaign/UJ spikes, quantify contribution.
   - For each top resource, report success, failure, previous median, delta, and share of total success/delta.
   - Join IDs to `campaigns_${project_id}` / `user_journeys_${project_id}` for human-readable names.
   - Check `audit_logs_${project_id}` for STARTED/STOPPED/TERMINATED/ACTIVATED/PAUSED/INACTIVATED events in the anomaly window.

6. Failure interpretation.
   - Treat provider/stat failure reason metrics as aggregated evidence; do not expose raw provider payloads.
   - Kakao failure groups like `3018` or friend/blocked/targeting messages often indicate audience/eligibility/friendship/receiver-state issues, but label mechanism confidence as medium unless raw provider payload/config confirms it.

## Implementation tip

When shell `psql` invocations become fragile due to secret quoting/masking, use a short Python `psycopg2` script that parses the profile `.env` and runs parameterized read-only queries. Do not print secrets.

## Slack-ready report shape

- 결론 first: normal/watch/urgent and whether it looks like customer campaign/UJ activity, reliability issue, or data freshness gap.
- 핵심 변화: latest value, baseline, delta, failure rate.
- 집중 축: channel/resource contributors and share.
- 원인 후보: confidence + evidence.
- 다음 확인: smallest human/customer-owner check.
- 데이터 한계: partial day, missing conversion/revenue, raw provider payload not inspected, sparse S3 baseline, etc.
