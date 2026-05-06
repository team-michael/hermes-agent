---
name: notifly-event-triggered-last-touch-semantics
description: Determine whether a Notifly event-triggered campaign can personalize from the latest matching event, and whether settings-only workarounds like cancellation conditions can approximate last-touch behavior.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [notifly, campaign, event-triggered, personalization, last-touch, cancellation-conditions]
    related_skills: [systematic-debugging]
---

# Notifly Event-Triggered Last-Touch Semantics

Use when someone asks questions like:
- "If a user triggers the same event multiple times, can the message use the last event's property?"
- "Is event personalization first-touch or last-touch?"
- "Can this be solved by Notifly settings only?"
- "Will the button URL use the most recent trigger event?"

## Goal

Establish four things:
1. **When event properties are captured** — at trigger time, schedule time, or delivery time
2. **Whether multiple matching events are deduplicated deterministically**
3. **Whether cancellation conditions can approximate last-touch**
4. **Whether the requested behavior is truly supported by settings only**

## High-signal files

### Trigger → schedule path
- `services/lambda/kds-consumer/lib/event.ts`
  - Main event ingestion path; passes `eventParams` into message queueing
- `services/lambda/kds-consumer/lib/message.ts`
  - Channel dispatch and direct-send vs scheduled-send split
- `services/lambda/kds-consumer/lib/db.ts`
  - `buildSchedule(...)` inserts rows into `scheduled_messages_<projectId>`
- `services/lambda/kds-consumer/lib/campaign.ts`
  - `shouldSendDirectly(...)` uses the 5-minute threshold
- `services/lambda/kds-consumer/lib/send_messages/*.ts`
  - Actual message personalization logic per channel

### Scheduler / delayed delivery path
- `services/lambda/event-triggered-message-scheduler/lib/db.js`
  - Reads pending rows from `scheduled_messages_<projectId>`
- `services/lambda/event-triggered-message-scheduler/lib/schedule_messages.js`
  - Duplicate/noisy handling and deletion behavior
- `services/server/web-console/queries/create_tables.sql`
  - Schema/indexes for `scheduled_messages_<projectId>`

### Cancellation condition path
- `services/lambda/kds-consumer/lib/cancellation_utils.ts`
  - Extracts cancellation conditions from campaign config
- `services/lambda/kds-consumer/lib/event_utils.ts`
  - Matches cancellation events and attaches `campaignIdsToDeschedule`
- `services/lambda/kds-consumer/lib/db.ts`
  - `descheduleDeferredMessages(...)` actually deletes pending schedules
- `services/server/web-console/src/domains/timing/transformers/EventBasedTimingTransformer.ts`
  - Web-console timing config → `cancellation_conditions`
- `services/server/web-console/public/locales/ko/products.json`
  - Product wording: cancellation condition only available when delay is 5 minutes+

### Delivery-time rendering / proof of snapshot semantics
- `services/lambda/email-delivery/...`
- `services/lambda/webhook-delivery/...`
- `services/lambda/scheduled-batch-delivery/lib/push_utils.js`
- `packages/common/src/delivery/utils.ts`

These show whether delivery re-renders from live/latest state or merely uses the stored payload / stored render params.

## Investigation workflow

### 1. Confirm whether trigger properties are stored immediately
Read `event.ts` → `message.ts` → the relevant `send_messages/<channel>.ts`.

What to look for:
- `eventParams` passed into queue functions
- message/button/link personalization done from `eventParams`
- `buildSchedule(...)` called with an already-personalized or already-snapshotted payload

This is the key question: **is the system saving a snapshot of the triggering event, or re-querying the latest event later?**

### 2. Check whether delayed sends read "latest event" at delivery time
Inspect the scheduler and delivery lambdas.

Key checks:
- scheduler selects from `scheduled_messages_<projectId>`
- delivery lambdas consume the stored message payload
- no lookup against raw event history / latest matching event before send

If true, the semantics are **trigger snapshot**, not true last-touch lookup.

### 3. Check duplicate handling carefully
The scheduler has a noisy-filter pass.

Important file:
- `event-triggered-message-scheduler/lib/schedule_messages.js`

Important questions:
- Does it explicitly keep the latest row?
- Is there an `ORDER BY` when fetching pending schedules?
- Are duplicates skipped based only on encounter order?

Important finding pattern:
- `getMessagesToSendPerProjectQuery(...)` has no `ORDER BY`
- `markNoisyMessagesAsSkipped(...)` skips later-seen duplicates for same `recipient_id + campaign_id`
- then processed rows are deleted

This means duplicate resolution is **not a reliable last-touch mechanism**.

### 4. Evaluate cancellation conditions as the settings-only workaround
Cancellation conditions are the main built-in approximation for last-touch.

Mechanism:
1. Trigger event creates a delayed schedule
2. A later event matching `cancellation_conditions` removes older pending schedules
3. The later trigger event can then create a new schedule with newer `eventParams`

This yields practical "latest surviving schedule" behavior for delayed campaigns.

But document the caveat:
- it only deletes **pending rows in `scheduled_messages_*`**
- if the message is on the **direct-send path** (`delay < 5 min`), there may be no scheduled row to replace
- therefore this is an approximation, not a universal last-touch guarantee

### 5. Verify the 5-minute product constraint
Use both code and locale strings.

Important references:
- `campaign.ts`: `SEND_DIRECTLY_TO_PUSH_QUEUE_SECONDS = 300`
- `public/locales/ko/products.json`:
  - cancellation condition helper text says it can be used only when delay is 5 minutes+

This is essential when answering CS questions.

## Channel-specific personalization clues

### Text / Kakao / Push
Many channel queue functions build render params like:
- `event: { ...eventParams, $campaign_id, $variant_id }`
- `user: { ...user_properties, ... }`
- `device: deviceData`

Examples:
- `send_messages/text_message.ts`
- `send_messages/kakao_friendtalk.ts`
- `send_messages/push_notification.ts`

If button URLs or template variables are rendered there, the values come from the **current trigger event**, then get stored.

### Delivery-time rerender caveat
Push connected-content can re-render later, but from **stored template/render params snapshot**, not by querying the latest matching raw event.
So this still does not create true last-touch semantics.

## Reliable conclusion templates

### Case A: user asks whether last-touch is natively supported
- "기본 동작상 동일 유저의 다중 트리거 이벤트 중 마지막 이벤트를 조회해서 그 프로퍼티를 쓰는 구조는 아닙니다."
- "트리거 시점의 event_params가 예약 메시지 payload에 반영되는 형태입니다."

### Case B: user asks whether settings-only workaround exists
- "다만 이벤트 기반 발송 + 동일 이벤트를 발송 취소 조건으로 두면, 기존 예약을 지우고 최신 이벤트 기준으로 다시 예약하는 방식으로 실무적으로 구현 가능합니다."
- "즉 true last-touch 조회 기능이라기보다 최신 이벤트가 이전 예약을 대체하도록 만드는 방식입니다."

### Case C: user asks whether it is fully guaranteed
- "완전한 의미의 last-touch 보장은 아닙니다. 특히 5분 미만 direct-send 경로에는 취소 조건 기반 대체가 적용되지 않습니다."

## Recommended response structure
1. **Conclusion** — supported / not supported / workaround available
2. **Mechanism** — trigger snapshot vs latest-event lookup
3. **Workaround** — cancellation condition on same event for delayed sends
4. **Caveat** — not universal for direct-send or already-queued sends

## Known durable findings

1. Event-triggered campaigns snapshot `eventParams` into the scheduled or queued message path.
2. `scheduled_messages_<projectId>` rows are inserted, not upserted/overwritten.
3. Scheduler duplicate handling is not a deterministic keep-latest algorithm.
4. Cancellation conditions can delete pending delayed schedules and thereby approximate last-touch behavior.
5. Cancellation conditions require delay >= 5 minutes.

## When not to overstate
Do **not** say:
- "Notifly supports last-touch personalization"
- "The last event is always used"

Prefer:
- "기본 기능으로 true last-touch 조회는 아니고, delayed event-triggered campaign에서는 cancellation condition 조합으로 원하는 동작에 가깝게 세팅 가능합니다."
