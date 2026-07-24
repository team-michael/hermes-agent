# kds-consumer notif_auth_status_enum validation failure

## Alarm shape

- Service: `kds-consumer` Lambda
- Metric filter: `%ERROR|Status: timeout%` on `/aws/lambda/kds-consumer`
- Error signature: `invalid input value for enum notif_auth_status_enum: "authorized"`
- Secondary signature: `Error in upserting user/device data error: invalid input value for enum notif_auth_status_enum ... Query: INSERT INTO device_<project_id> ...`

## Error pattern

The Lambda tries to INSERT/UPSERT into `device_<project_id>` and passes a `notif_auth_status` value that is **not in the PostgreSQL enum**.

DB enum `notif_auth_status_enum` values (verified from `pg_enum`):
```
-1, 0, 1, 2, 3
```

These are stored as string literals in the application type system (`packages/types/src/Device.ts`):
- `'-1'` = Not Determined
- `'0'`  = Denied
- `'1'`  = Authorized
- `'2'`  = Provisional
- `'3'`  = Ephemeral

## Root cause

The value `"authorized"` (or similar stringified platform-native enum names) arrives in `event_params.notif_auth_status` during the **`session_start` event** (`INTERNAL_EVENTS.USER.SESSION_START`) and is passed unvalidated into the raw SQL INSERT.

Exact code path:
1. `services/lambda/kds-consumer/lib/event_utils.ts:241-242` — for `eventData.name == SESSION_START`, the device attribute extractor reads:
   ```ts
   deviceData.notif_auth_status = eventData.event_params?.notif_auth_status;
   ```
2. `services/lambda/kds-consumer/lib/device_utils.ts:57` — `upsertDevice` interpolates this raw value via `convertToPGText(deviceData.notif_auth_status)` into the raw SQL INSERT for `device_<project_id>`.

This happens when:
1. A customer sends `session_start` events directly via the HTTP API with a non-Notifly value for `notif_auth_status`.
2. A custom SDK integration serializes a platform-native enum name (e.g. iOS `UNAuthorizationStatus.authorized` → `"authorized"`) instead of the Notifly numeric mapping.

## SDK mappings (source of truth)

**iOS SDK**: `UNAuthorizationStatus` → `Int` mapping (`TrackingManager.swift`)
- `.authorized`    → `1`
- `.denied`        → `0`
- `.notDetermined` → `-1`
- `.provisional`   → `2`
- `.ephemeral`     → `3`

**Android SDK**: `NotificationAuthorizationStatus` enum (`NotificationAuthorizationStatus.kt`)
- `AUTHORIZED` → `1`
- `DENIED`     → `0`

## Client-side fix example

For direct API callers or custom SDK wrappers that send `session_start`, map the platform-native status to Notifly string codes before sending.

**iOS example**:
```swift
func mapNotifAuthStatus(_ status: UNAuthorizationStatus) -> String {
    switch status {
    case .notDetermined: return "-1"
    case .denied:        return "0"
    case .authorized:    return "1"
    case .provisional:   return "2"
    case .ephemeral:     return "3"
    @unknown default:    return "-1"
    }
}
// event_params["notif_auth_status"] = mapNotifAuthStatus(status)
```

**Android example**:
```kotlin
fun mapNotifAuthStatus(areNotificationsEnabled: Boolean): String {
    return if (areNotificationsEnabled) "1" else "0"
}
// event_params["notif_auth_status"] = mapNotifAuthStatus(areNotificationsEnabled)
```

## Triage

1. Verify `AWS/Lambda` `Errors` = 0 (the Lambda catches the error and continues).
2. Extract `project_id` from the table name (`device_<project_id>`) in the log line.
3. Map `project_id` via DynamoDB `project` table.
4. Check daily volume. Single-digit or sporadic occurrences → customer-side bad input.
5. If volume spikes after a deployment, check whether a new SDK version changed the serialization format.

## Scope

- Project is known from the sharded table suffix (`device_<project_id>`).
- Campaign/user journey are **not applicable** — this is a `session_start` device upsert path.

## Classification

| Volume / Errors | Classification | Rationale |
|-----------------|---------------|-----------|
| `Errors=0`, sporadic, single project | `no_action` | Handled DB rejection; device record not updated but pipeline continues. |
| `Errors=0`, recurring across multiple projects after deploy | `needs_fix` | Likely SDK regression or missing input validation in `event_utils.ts:242`. |
| `Errors > 0` | `needs_fix` | Unhandled exception path; investigate `device_utils.ts` and `event_utils.ts`. |

## Long-term fix options

1. **Server-side validation** in `services/lambda/kds-consumer/lib/event_utils.ts:242` (or `device_utils.ts`) — coerce or reject illegal `notif_auth_status` values before SQL construction.
2. **Log-level downgrade** if the rejection is handled gracefully — the Lambda already catches and continues, so the ERROR log is mostly noise. Keep `ERROR` only if `notif_auth_status` is required for downstream features.
3. **Documentation** — the HTTP API docs and SDK integration guides should explicitly list accepted `notif_auth_status` values since the field is visible in `event_params` for direct API callers.

 see `references/api-service-invalid-project-tracing.md` for how to trace direct-API callers by `userAgent` and `ip`.
