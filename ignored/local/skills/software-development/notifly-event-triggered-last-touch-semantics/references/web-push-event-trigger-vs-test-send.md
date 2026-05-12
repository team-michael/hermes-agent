# Web Push: event-triggered vs test-send visibility

Session learning from a Notifly `track-event` investigation.

## Symptom

A customer says:
- Web push **test send** works.
- A running event-triggered campaign does not visibly fire after `curl /track-event`.

The event/campaign may still be healthy. Do not stop at “send_success exists”; explain the channel/device semantics.

## Evidence chain

1. Athena `notifly_event_logs`
   - Confirm event name exact match (`hj_sent` vs `hjsent` etc.).
   - Confirm `external_user_id` and generated `notifly_user_id`.
   - Public `/track-event` treats `userId` as `external_user_id`.

2. Postgres campaign row
   - `campaigns_${projectId}` with `id`, `status`, `timing_type`, `channel`, `triggering_conditions`.
   - For event-triggered active campaigns expect `status = 1` and `timing_type = 1`.

3. Delivery/result rows
   - `delivery_result_${projectId}`: `send_success`/`send_failure`.
   - `message_events_${projectId}`: for web push, `push_delivered` is logged by the service worker after receiving the push event and attempting `showNotification(...)`.

4. Device selection
   - Event-triggered KDS path may not have `notifly_device_id` on server-side curl events.
   - It then selects one device using `device_${projectId} ORDER BY updated_at DESC LIMIT 1` via `selectMostRecentDeviceIdByUser`.
   - Web-console test-send resolves by `external_user_id` and can fan out to multiple JS/web device tokens.

## Interpretation

If test-send succeeds but event-triggered delivery is “not visible”, and DB/logs show `send_success` + `push_delivered`, likely explanations are:

- Event trigger sent to the latest web device, not the browser/profile the user is watching.
- Browser/OS notification display suppressed it despite service worker receiving the push.
- The user expected web popup/in-web-message semantics, but the campaign channel is `web-push-notification`.

## Useful queries

```sql
SELECT created_at, event_name, channel, campaign_id, notifly_user_id
FROM delivery_result_${projectId}
WHERE campaign_id = '<campaign_id>'
  AND created_at >= timestamp '<start>'
ORDER BY created_at;

SELECT created_at, event_name, channel, campaign_id, event_params->>'notifly_message_id' AS notifly_message_id
FROM message_events_${projectId}
WHERE campaign_id = '<campaign_id>'
  AND created_at >= timestamp '<start>'
ORDER BY created_at;

SELECT notifly_device_id, platform, sdk_type, sdk_version,
       device_token IS NOT NULL AS has_token,
       updated_at, created_at
FROM device_${projectId}
WHERE notifly_user_id = '<notifly_user_id>'
ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST;
```

## Reporting pattern

Say explicitly:

> 백엔드 기준으로는 트리거/발송/서비스워커 수신까지 갔습니다. “묵묵부답”은 트리거 실패라기보다, 이벤트 트리거가 선택한 최신 device id와 지금 보고 있는 브라우저/프로필이 다르거나 OS/브라우저 알림 표시가 막힌 케이스로 보입니다.

Then give the selected `notifly_device_id` and what to compare in the browser.