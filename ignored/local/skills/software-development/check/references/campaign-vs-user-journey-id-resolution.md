# Resolving an ambiguous campaign/user-journey ID across sharded project tables

## When to use this

Any time a log line carries a bare ID (commonly under a `campaignId` field — Notifly
reuses that field name generically for both campaigns and user journeys) and:
- the project scope is not otherwise known from the log context, and/or
- the same ID string has previously been seen under more than one project
  (IDs are not globally unique — they are scoped per-shard).

Do not guess the project from memory of a prior session. Re-resolve every session;
the same ID can map to a different project on a different day, and a prior day's
answer for one project does not rule out the ID also existing (or now existing)
under another.

## Deterministic resolution procedure

There are two valid ways to enumerate candidate projects. Prefer method B when
the alarm/log context gives no product-name hint at all — it needs no guessing
step and is cheap enough (~1,500+ shards in a few seconds) to run unconditionally.

### Method A — narrow via DynamoDB first (when a product hint exists)

1. **Enumerate every plausible candidate `project_id`** in one DynamoDB scan rather
   than querying one-by-one by guessed name. `name` is a DynamoDB reserved word —
   always alias it:
   ```python
   table.scan(ProjectionExpression="id, product_id, #n",
              ExpressionAttributeNames={"#n": "name"})
   ```
   Paginate with `LastEvaluatedKey` until exhausted. Filter the result list in
   Python for the candidate product name(s) mentioned in the alarm/log context —
   don't re-query DynamoDB per candidate.

2. Check `campaigns_<project_id>` then `user_journeys_<project_id>` for just
   those candidates, as below.

### Method B — brute-force shard enumeration (when no product hint exists)

Skip DynamoDB entirely on the first pass. Ask Postgres which shards exist, then
query every one directly with the bare ID — this is fully deterministic and
doesn't depend on the alarm context naming a product:

```python
cur.execute("""SELECT table_name FROM information_schema.tables
               WHERE table_schema='public' AND table_name LIKE 'campaigns_%'""")
tables = [r[0] for r in cur.fetchall()]
for t in tables:
    pid = t.replace("campaigns_", "")
    try:
        cur.execute(f'SELECT id, updated_at FROM "{t}" WHERE id = %s', (candidate_id,))
        if cur.fetchall():
            found.append(pid)
    except Exception:
        conn.rollback()   # see schema-drift pitfall below
        continue
```
Repeat against `user_journeys_%` if the campaigns pass returns nothing. On a
~1,584-table `campaigns_*` / ~792-table `user_journeys_*` shard set this
completes in single-digit seconds and needs no candidate list at all.

**Pitfall — shard schema drift breaks blind `UNION ALL`**: some shards are
missing columns other shards have (observed: a `campaigns_<hash>` shard with no
`name` column), so a single `UNION ALL ... SELECT id, name, ...` across all
shards throws `psycopg2.errors.UndefinedColumn` and aborts the whole scan. Query
only guaranteed-present columns (`id`, `updated_at`), loop per-table instead of
one big UNION, and wrap each iteration in `try/except` with `conn.rollback()`
on failure so one bad shard doesn't kill the scan.

### Common steps (either method)

3. **Check `campaigns_<project_id>` first**, for every candidate `project_id`:
   ```sql
   SELECT id, name, created_at FROM "campaigns_<project_id>" WHERE id = %s
   ```
   Campaigns are checked first because campaign and user-journey scope are
   mutually exclusive in the final answer, and campaign is the more common case.

4. **If every campaign lookup returns `None`, fall back to `user_journeys_<project_id>`**
   for the same candidate list:
   ```sql
   SELECT id, name, created_at FROM "user_journeys_<project_id>" WHERE id = %s
   ```
   An empty `campaigns_*` result does NOT mean the ID was deleted — it very
   commonly means the ID is a user journey, not a campaign. See also the
   `check` SKILL.md pitfall "empty `campaigns_*` table does not mean deleted".

5. **Report exactly one of campaign or user journey**, matching whichever table
   produced a hit, and quote the resolved project name (not just the raw
   `project_id`). Never print both, and never label a `user_journeys_*` hit as a
   campaign just because the source log field was named `campaignId`.

## Concrete example (2026-07-04, `segment-publisher slow eic query`)

Log line: `campaignId: UL1T00, 923708 recipients published. (batch index: 19)`.

- DynamoDB `project` scan found 4 candidates across `stepup`/`proudp` (each has a
  dev + prod project_id pair).
- `campaigns_<project_id>` for `id='UL1T00'` returned `None` on all 4.
- `user_journeys_<project_id>` for `id='UL1T00'` hit on
  `project_id=32d8d9d6294d52e7a5427c036b471f91` (`stepup`), name
  `[만보기] 매일 적립 리마인드`.
- Final scope reported: `stepup` project, user journey `UL1T00` — not a campaign.

This is consistent with `references/segment-publisher-slow-eic-query-noise.md`
§ "Scope-attribution caveat for UL1T00", which already documented that this same
ID string had previously resolved to `stepup` on other days and to `proudp` on
others — confirming the ID is not globally unique and must be re-checked per
session rather than assumed from history.
