# Event-triggered email timing vs delivery-queue timing

Use when a customer asks why `이벤트 발생 시각` and `이메일 수신/발송 시각` differ for an event-based email campaign.

## Durable mechanism

Event-based email delivery is asynchronous:

```text
customer/server event
→ Notifly event ingestion / Kinesis processing
→ campaign matching in kds-consumer
→ email-delivery SQS enqueue
→ email-delivery Lambda consumes SQS
→ SES SendBulkTemplatedEmail success
→ recipient mailbox arrival
```

Therefore the event timestamp and email send/result timestamp are not expected to be identical.

## How to explain the time gap

Separate three clocks:

1. **Event time** — when the customer's server/browser emitted the event and Notifly ingested it.
2. **Notifly send-processing time** — when `email-delivery` Lambda consumed the SQS message and SES returned send success/failure.
3. **Mailbox arrival/visibility time** — downstream provider/client behavior after SES accepts the send.

For a campaign with `delay = null` or `delay < 300s`, the kds-consumer path is direct-to-channel-queue, not `scheduled_messages_*`. Any multi-minute gap is usually queue/backlog/provider processing, not configured campaign delay.

## Verification checklist

1. Map project by DynamoDB `project` table; choose the dev/prod project explicitly.
2. Confirm campaign config in PostgreSQL:
   - `campaigns_${projectId}.id`
   - `timing_type = 1`
   - `channel = 'email'`
   - `delay` value
   - forbidden timing / frequency / fatigue settings if relevant
3. Check raw event evidence in Athena `notifly_analytics.notifly_event_logs`:
   - filter `project_id`, `dt`, exact event `name`, `notifly_user_id` / `external_user_id`
   - render microsecond timestamps with `from_unixtime(time / 1000000.0) AT TIME ZONE 'Asia/Seoul'`
   - event-name matching is exact; underscores/camelCase differences matter.
4. Check kds-consumer CloudWatch logs for `email queued for delivery directly` with the campaign id/user id. This proves Notifly matched the campaign and enqueued email work.
5. Check email-delivery CloudWatch logs for:
   - `Received event from SQS`
   - `SendResultsInsertQuery` / `send_success` or failure
6. Check PostgreSQL `delivery_result_${projectId}` for `send_success` / `send_failure` with `created_at` converted to KST.
7. If the gap is large, check SQS CloudWatch metrics for `email-delivery-queue` around the event time:
   - `ApproximateNumberOfMessagesVisible`
   - `ApproximateAgeOfOldestMessage`

## Reporting pattern

Good wording:

> 이벤트 발생 시각은 고객 서버/브라우저에서 이벤트가 발생한 시각이고, 이메일 발송 시각은 Notifly가 이메일 발송 큐를 처리해 SES에 발송 요청을 성공시킨 시각입니다. 이벤트 기반 발송은 비동기 큐를 거치기 때문에 두 시각이 같지 않을 수 있습니다. 해당 캠페인에 별도 delay가 없다면, 다분 단위 차이는 캠페인 지연 설정이라기보다 email-delivery queue backlog / delivery Lambda processing / SES 이후 수신 측 처리로 분리해서 봐야 합니다.

If SES `send_success` exists but the customer says “not received,” say Notifly-side send succeeded and the remaining investigation is downstream mailbox visibility: spam/promotions folder, recipient domain filtering, client sync delay, or bounce/complaint tracking.

## Pitfalls

- Do not infer “미발송” from customer mailbox non-visibility alone. Verify `delivery_result_${projectId}` and email-delivery logs.
- Do not check `scheduled_messages_${projectId}` for direct-send campaigns; no row is expected when `delay < 300s`.
- Do not conflate configured campaign delay with queue backlog. Confirm `campaign.delay` first.
- Do not normalize event names mentally. `admin_trialEnding_scheduled` and `admintrialEndingscheduled` are different names.
