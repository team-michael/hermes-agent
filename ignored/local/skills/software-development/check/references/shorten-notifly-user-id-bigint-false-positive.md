# shortenNotiflyUserId BigInt Parse Failure False Positive

ECS / Lambda `ConsoleErrors` alarm triggered when `shortenNotiflyUserId()` encounters a `notifly_user_id` that is not a valid hexadecimal string and the `encode()` helper throws `SyntaxError` from `BigInt('0x' + partialUuid)`.

## Affected services

Any service that calls `shortenNotiflyUserId()` on untrusted or test-account `notifly_user_id` values:
- `segment-publisher` (most commonly observed)
- `kds-consumer` (push, webhook, Kakao, text, email, web push paths)
- `api-service` (campaign message preparation)

## Trigger signature

```
[ERROR] SyntaxError: Cannot convert 0x<invalid_hex> to a BigInt
```

Concrete examples observed in production logs:
- `0xtest_80`, `0xtest_20`, `0xtest_1` … `0xtest_99`
- `0xsdfsdf`, `0xasdfsdfdsfsd`
- `0x52d1f43f-c4f`, `0x82dde2b7-707` (hyphenated UUID fragments)

## Code path

1. Caller (e.g. `prepareRenderParams`):
   ```ts
   // services/task/segment-publisher/lib/util/utils.ts:118
   $notifly_user_id_short: shortenNotiflyUserId(userData.notifly_user_id),
   ```

2. `shortenNotiflyUserId`:
   ```ts
   // packages/util/src/util/shortenNotiflyUserId.ts:11
   return encode(notiflyUserId.slice(0, NOTIFLY_USER_ID_SHORTENED_LENGTH));
   ```

3. `encode`:
   ```ts
   // packages/util/src/base62/index.ts:14
   const number = BigInt('0x' + partialUuid);
   ```

`BigInt('0x' + partialUuid)` requires `partialUuid` to be a valid hexadecimal string. Test IDs such as `test_80` contain non-hex characters (`t`, `e`, `s`, `_`), causing an immediate `SyntaxError`.

## Why it is a false positive

`shortenNotiflyUserId` wraps the call in `try-catch`:

```ts
// packages/util/src/util/shortenNotiflyUserId.ts:10-15
try {
    return encode(notiflyUserId.slice(0, NOTIFLY_USER_ID_SHORTENED_LENGTH));
} catch (e) {
    console.error(e);
    return notiflyUserId;
}
```

The function **recovers gracefully** by returning the original `notifly_user_id` unchanged. Message rendering and delivery continue normally. However, it logs the caught exception at `ERROR` level, which trips the coarse `%ERROR%` metric filter even though no service fault occurred.

## Classification

- `AWS/Lambda Errors == 0` (when the caller is a Lambda)
- Service task continues normally; no delivery failure
- Scope: usually internal test projects (e.g. `michael` / `a0d696d1aba7535fad6710cddf3b1cab`)
- **Classify as `no_action`** for isolated spikes when the log contains only `0xtest_*` or similarly obvious test IDs
- Use `needs_fix` only when recurrence becomes noisy (daily sustained) or when real customer IDs (non-test) are observed

## Frequency observed

On `segment-publisher console error`:
- 30d OK→ALARM: 2
- 7d: 1
- 1d: 1
- Duration: single-minute spike (e.g. Sum=201) then immediate recovery

## Long-term remediation

Preferred: pre-validate the hex string before calling `BigInt` and downgrade to `WARN` / `INFO` for known invalid patterns.

Option A — validate in `encode` and return fallback:
```ts
// packages/util/src/base62/index.ts
function encode(partialUuid: string): string {
    if (!/^[A-Fa-f0-9]+$/.test(partialUuid)) {
        // not a valid hex string; return as-is so caller can decide
        return partialUuid;
    }
    const number = BigInt('0x' + partialUuid);
    // ... rest of encode
}
```

Option B — downgrade log level in `shortenNotiflyUserId`:
```ts
// packages/util/src/util/shortenNotiflyUserId.ts
try {
    return encode(notiflyUserId.slice(0, NOTIFLY_USER_ID_SHORTENED_LENGTH));
} catch (e) {
    console.warn('[shortenNotiflyUserId] non-hex user_id, returning original', {
        notiflyUserId,
        error: e.message,
    });
    return notiflyUserId;
}
```

Option A is safer because it removes the exception path entirely for non-hex IDs. Option B preserves the metric filter's ability to catch real `encode` bugs (e.g. integer overflow) while silencing the handled case.

## Bounded log check

When the helper returns empty `current_error_details` but the alarm breached:

```bash
python3 -c "
import boto3, datetime
session = boto3.Session(region_name='ap-northeast-2')
logs = session.client('logs')
# Anchor to StateReasonData.startDate
start = int(datetime.datetime(2026, 5, 20, 9, 9, tzinfo=datetime.timezone.utc).timestamp() * 1000)
end   = int(datetime.datetime(2026, 5, 20, 9, 11, tzinfo=datetime.timezone.utc).timestamp() * 1000)
resp = logs.filter_log_events(
    logGroupName='/aws/ecs/notifly-services-prod/segment-publisher',
    startTime=start, endTime=end,
    filterPattern='Cannot convert',
    limit=50
)
for e in resp.get('events', []):
    print(e['message'].strip()[:300])
"
```
