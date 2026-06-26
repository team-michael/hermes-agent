# Scripted non-browser caller → TypeError on web-console API endpoint

## Pattern

A non-browser user agent (`Python-urllib/3.10`, `curl/7.81.0`, etc.) with no `Referer` header
POSTs to a web-console API route with a malformed or missing request body field.
The endpoint does not null-check the field before calling `.map()` or another array method,
producing `TypeError: Cannot read properties of undefined (reading 'map')`.
The `TypeError` matches the broad `%[Ee][Rr][Rr][Oo][Rr]|Exception%` metric filter and triggers
the `web-console console error` alarm.

The 500 response is logged in the morgan access log with the `projectId` directly in the URL path
(`/api/projects/<projectId>/campaigns/success_counts`), making scope attribution straightforward —
no `Referer`-based product-slug lookup needed.

## Concrete example: success_counts.ts (2026-06-25)

### Source location

`services/server/web-console/src/pages/api/projects/[projectId]/campaigns/success_counts.ts`

```typescript
const POST = async (req: NextApiRequest, res: NextApiResponse) => {
    try {
        const projectId = req.query.projectId as string;
        const campaigns = req.body.campaigns as Pick<Campaign, 'id'>[];
        // ↓ TypeError here when req.body.campaigns is undefined
        const successCountsByCampaign = await CampaignStatisticRepository.countSuccessByCampaignIds(
            projectId,
            campaigns.map((c) => c.id)
        );
        res.status(200).json(successCountsByCampaign);
    } catch (err) {
        console.warn(err);  // ← logged as WARN, but Sentry wrapper logs TypeError at ERROR level
        res.status(500).json({ error: err });
    }
};
```

### Trigger signature

```
TypeError: Cannot read properties of undefined (reading 'map')
at Array.l (/app/services/server/web-console/.next/server/pages/api/projects/[projectId]/campaigns/success_counts.js:1:9389)
at next (file:///app/node_modules/.pnpm/next-connect@1.0.0-next.4/node_modules/next-connect/dist/esm/router.js:48:36)
...
at Module.handleCallbackErrors (/app/node_modules/.pnpm/@sentry+core@10.39.0/...)
```

### Access log evidence

```
203.248.117.90 - - [2026-06-25T06:16:12.884Z] "POST /api/projects/cb0bf8882d145a6d81e466687caa8791/campaigns/success_counts HTTP/1.1" 500 12 "-" "Python-urllib/3.10" - 116.241 ms
```

Key indicators:
- User agent: `Python-urllib/3.10` (scripted, not browser)
- Referer: `-` (not from console UI)
- Response: 500, 12 bytes (compact error JSON)
- `projectId` directly in URL path — map via DynamoDB `project` table

### Frequency (7d)

- Python-urllib `success_counts` 500 calls: 2 (same caller, same project, same 1-minute window)
- Alarm overall: 26 ALARM transitions in 7d (dominated by other patterns — Sentry tunnel 429, Kakao validation, etc.)

## Triage steps

1. Check access logs in the alarm window for non-browser user agents (`Python-urllib`, `curl`, `axios`, `Go-http-client`, etc.) hitting the erroring endpoint.
2. The access log line contains the `projectId` in the URL path — map via DynamoDB `project` table directly. No `Referer` lookup needed.
3. Verify the TypeError is from missing null-check on `req.body.<field>` by reading the source file.
4. Check 7d frequency of the same non-browser caller + same endpoint + 500 pattern.
5. If frequency is low (1-5 in 7d) and the caller is scripted (not a browser user), classify as `no_action`.
6. Note the missing null-check as a non-urgent code improvement target in the final answer.

## Classification

- `no_action` when: scripted caller, internal/test project, no browser users affected, low frequency
- `needs_fix` when: frequency spikes across multiple projects or after a deployment, or browser users start hitting the same missing-null-check path

## Remediation direction

Add a guard before the `.map()` call:

```typescript
const campaigns = req.body?.campaigns;
if (!Array.isArray(campaigns)) {
    res.status(400).json({ error: 'campaigns field is required and must be an array' });
    return;
}
```

This applies to all web-console API routes that destructure `req.body` without validation — the
class-level fix is to add input validation (zod schema or manual guard) to POST handlers that
assume a specific body shape.

## Scope attribution

When the access log shows `POST /api/projects/<projectId>/...` with a 500 status, the `projectId`
is directly in the URL path. Use DynamoDB `project` table `get_item` with `id = <projectId>`.
This is simpler than the `Referer`-based product-slug lookup in
`web-console-scope-attribution-via-access-logs.md` and should be the first scope attribution
method attempted for any web-console API route error where the path contains `[projectId]`.
