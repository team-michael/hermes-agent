# User push history exists but current device is missing

Case pattern captured from project `3ee6e5f95be353e48af47a7081f1716a`, external user `289331`.

## Diagnostic goal

Explain why a user detail page can show push history while current device info is empty.

The usual distinction:
- `users_<projectId>` / `device_<projectId>` show **current identity-device linkage**.
- `delivery_result_<projectId>` and `message_events_<projectId>` preserve **historical send / SDK-side message outcomes** for the `notifly_user_id` at event time.

## SQL recipe

Resolve current identified user:

```sql
select notifly_user_id, external_user_id, source, timezone, created_at, updated_at
from users_<projectId>
where external_user_id = '<externalUserId>';
```

Check whether the current user has devices:

```sql
select *
from device_<projectId>
where external_user_id = '<externalUserId>'
   or notifly_user_id = '<oldNotiflyUserId>';
```

Summarize delivery results:

```sql
select channel, event_name, count(*), min(created_at), max(created_at)
from delivery_result_<projectId>
where notifly_user_id = '<oldNotiflyUserId>'
group by channel, event_name
order by max(created_at) desc;
```

Find whether historical push token now belongs to another device/user:

```sql
with dr as (
  select extra_data->>'token' as token, min(created_at) first_sent, max(created_at) last_sent, count(*) cnt
  from delivery_result_<projectId>
  where notifly_user_id = '<oldNotiflyUserId>'
    and channel = 'push-notification'
    and extra_data ? 'token'
  group by 1
)
select
  md5(dr.token) as token_md5, -- do not print raw token
  dr.cnt,
  dr.first_sent,
  dr.last_sent,
  d.notifly_user_id,
  d.external_user_id,
  d.notifly_device_id,
  d.platform,
  d.app_version,
  d.os_version,
  d.sdk_type,
  d.sdk_version,
  d.notif_auth_status,
  d.device_token_status,
  d.created_at,
  d.updated_at
from dr
left join device_<projectId> d on d.device_token = dr.token
order by dr.last_sent desc;
```

Pair provider/send-request success with SDK-side receipt/display events:

```sql
select event_name, event_params->>'reason' as reason, count(*), min(created_at), max(created_at)
from message_events_<projectId>
where notifly_user_id = '<oldNotiflyUserId>'
group by event_name, event_params->>'reason'
order by count(*) desc;
```

Show combined history as the web-console user log effectively does:

```sql
with logs as (
  select created_at, 'delivery_result' as source, channel, event_name, campaign_id
  from delivery_result_<projectId>
  where notifly_user_id = '<oldNotiflyUserId>'
  union all
  select created_at, 'message_events' as source, channel, event_name, campaign_id
  from message_events_<projectId>
  where notifly_user_id = '<oldNotiflyUserId>'
)
select created_at, source, channel, event_name, campaign_id
from logs
order by created_at desc
limit 30;
```

## Athena recipe for identity transition

Use Athena `notifly_analytics.notifly_event_logs` around the suspected transition window:

```sql
select
  from_unixtime(cast(time as bigint) / 1000000 + 9 * 3600) as time_kst,
  name,
  notifly_user_id,
  coalesce(external_user_id, '') as external_user_id,
  coalesce(notifly_device_id, '') as notifly_device_id,
  coalesce(platform, '') as platform,
  coalesce(app_version, '') as app_version,
  coalesce(os_version, '') as os_version,
  coalesce(sdk_type, '') as sdk_type,
  coalesce(sdk_version, '') as sdk_version,
  case when device_token is null or device_token = '' then 'no_token' else 'has_token' end as token_state
from notifly_event_logs
where project_id = '<projectId>'
  and dt between '<YYYY-MM-DD>' and '<YYYY-MM-DD>'
  and (
    external_user_id = '<externalUserId>'
    or notifly_user_id in ('<oldNotiflyUserId>', '<newNotiflyUserId>')
    or notifly_device_id = '<notiflyDeviceId>'
  )
order by time asc
limit 300;
```

Signal to look for:
- `session_start` / normal events under the old identified `notifly_user_id` with `external_user_id`.
- `remove_external_user_id` under a new anonymous `notifly_user_id` for the same `notifly_device_id`.

## Code proof

- `services/lambda/kds-consumer/lib/event_utils.ts`
  - `getDeviceAttributesToUpdate(...)` handles `remove_external_user_id`.
  - It sets `deviceData.force_update_user_id = true` for `REMOVE_EXTERNAL_USER_ID`.
- `services/lambda/kds-consumer/lib/device_utils.ts`
  - `upsertDevice(...)` performs `ON CONFLICT (notifly_device_id) DO UPDATE`.
  - If `force_update_user_id` is true, it updates `notifly_user_id` and `external_user_id` to `EXCLUDED` values.

## Interpretation template

> 현재 유저에는 기기 row가 없지만, 과거 발송 당시에는 해당 기기가 유저에 연결되어 있었습니다. 이후 `remove_external_user_id` 이벤트가 발생하면서 같은 `notifly_device_id`가 익명 `notifly_user_id`로 이동했고, 그래서 현재 유저 상세에서는 기기 정보가 비어 보입니다. 과거 발송 이력은 기존 `notifly_user_id` 기준으로 남아 있는 것이 정상입니다.

If `message_events` shows `push_not_delivered` with `missing POST_NOTIFICATIONS permission`:

> `delivery_result.send_success`는 푸시 발송 요청 성공을 의미하고, 실제 기기 수신/표시 성공과는 다릅니다. 이 케이스는 SDK-side 이벤트가 `push_not_delivered`이며 사유가 `missing POST_NOTIFICATIONS permission`이므로, Android 알림 권한 미허용으로 실제 수신/표시는 실패한 것으로 보는 것이 맞습니다.

## Privacy / safety

- Do not print raw `device_token`; hash it with `md5`/`sha256` if comparing.
- Avoid exposing encrypted user fields or raw credential/env values in outputs.
