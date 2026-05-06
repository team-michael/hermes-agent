---
name: notifly-default-user-condition-tracing
description: Trace whether Notifly campaign default user conditions are actually applied as additional filters, from web-console save path to runtime delivery checks and campaign data verification.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [notifly, campaign, segmentation, default-user-condition, additional-filter, debugging]
    related_skills: [systematic-debugging]
---

# Notifly Default User Condition Tracing

Use when someone asks whether "기본 유저 조건" is working as an "추가 필터", or when a campaign appears to have sent to users who should have been excluded.

## Goal

Establish three things:
1. **Product semantics** — does the UI/backend intend default user conditions to become additional filters?
2. **Code path** — where are defaults merged and how are they evaluated?
3. **Concrete campaign state** — does a specific campaign actually have the default conditions persisted into runtime `segment_info.additional_conditions`?

## High-signal files

### UI / save path
- `services/server/web-console/public/locales/ko/common.json`
  - Contains the product wording: default user conditions are added to campaign additional filters.
- `services/server/web-console/src/utils/campaign/index.ts`
  - New campaign defaults: `enableDefaultUserCondition`, `defaultChannelConditions`.
- `services/server/web-console/src/components/segment/condition/index.tsx`
  - Toggle behavior; enabling copies metadata defaults into `defaultChannelConditions`.
- `services/server/web-console/src/utils/campaign/adapter/index.ts`
  - Passes `defaultChannelConditions` into segment adapter only when `enableDefaultUserCondition` is true.
- `services/server/web-console/src/utils/campaign/adapter/segment/index.ts`
  - Critical merge point into `details.additionalConditions`.
- `services/server/web-console/src/utils/campaign/defaultValue.ts`
  - Strips previously merged defaults back out of `view_state` for editing; important when interpreting stored data.
- `services/server/web-console/src/schemas/campaign/view/index.ts`
  - Validation logic; empty segment is allowed if default conditions are enabled.

### Runtime evaluation
- `packages/segment-helper/src/segment.ts`
  - Core semantics: `groupMatched && additionalConditionMatched`.
- `packages/segment-helper/src/condition.ts`
  - How user/device/event/file-based conditions are evaluated.
- `services/task/segment-publisher/lib/segment/recipients/recipient.ts`
  - Uses `matchSegment(...)` before publish.
- `services/task/segment-publisher/lib/segment/segment_publisher.ts`
  - Calls `matchesSegmentCondition(...)` when filtering recipients.
- `services/task/segment-publisher/lib/message/push_notification.ts`
  - Push payload includes `additional_conditions`.
- `services/lambda/scheduled-batch-delivery/lib/delivery_policy.js`
  - Delivery-time recheck of `additional_conditions` before send.
- Other channel delivery handlers often follow the same `inspectRecipientsWithAdditionalConditions(...)` pattern.
- `packages/delivery-policy/src/index.ts`
  - Implementation of `inspectRecipientsWithAdditionalConditions(...)`.

## Investigation workflow

### 1. Confirm intended product semantics
Read the Korean locale strings first.

Look for wording like:
- "캠페인의 추가 필터에 기본으로 추가되는 유저 조건"
- existing-campaign caveat that changing default conditions later does **not** retroactively update old campaigns unless the toggle is re-enabled.

This is important because some incidents are really **expectation mismatches**, not code bugs.

### 2. Trace the save-time merge
Verify this path:
1. campaign form has `enableDefaultUserCondition`
2. `defaultChannelConditions` stores channel-specific default conditions
3. on save, segment adapter prepends these into `details.additionalConditions`
4. persisted runtime field becomes `segment_info.additional_conditions`

Important caveat:
- If `conditionTargetingMode === ALL`, the merge is skipped.
- So default user condition can exist in `view_state` but not affect runtime filtering for ALL-target campaigns.

### 3. Confirm AND semantics mechanically
Use `packages/segment-helper/src/segment.ts`.

The key model is:
- groups are the main targeting groups
- additional conditions are evaluated as a synthetic AND group
- final result is `groupMatched && additionalConditionMatched`

This is the cleanest proof that default user conditions, once merged into additional conditions, behave as extra filters.

### 4. Trace runtime rechecks
For scheduled / queued delivery, confirm both layers if relevant:
- segment-publisher filters candidate recipients with `matchSegment(...)`
- delivery lambda may re-check `additional_conditions` before actual send, especially for delayed delivery

This matters because even if query extraction is broad, later layers can still enforce the filter.

### 5. Verify a specific campaign in prod data
For a concrete campaign ID, query PostgreSQL `campaigns_<projectId>` tables.

#### Finding the campaign table
There are many per-project campaign tables. A reliable approach is:
- list public tables matching `^campaigns_[0-9a-f]{32}$`
- probe each table for `WHERE id = $1`
- stop when a row is found

Python + `asyncpg` works well because `psql` may not be installed while env vars are present:
- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`

#### What to inspect
From the matching row, inspect both:
- `segment_info`
- `view_state`

Interpretation:
- `view_state.enableDefaultUserCondition = true` means UI toggle was on
- `view_state.defaultChannelConditions` shows the configured defaults in editor schema
- `view_state.segment.details.additionalConditions` may be empty by design after the 2026-04-08 change
- `segment_info.additional_conditions` is the runtime truth for actual filtering

### 6. Check campaign timing/status before overgeneralizing
Also inspect fields like:
- `status`
- `timing_type`
- `starts`
- `created_at`
- `updated_at`

Reason: users often refer to a campaign as “daily” or “current”, but the stored campaign may actually be a one-time or terminated campaign. That mismatch is highly diagnostic.

## Practical database snippets

### Find campaign across per-project campaign tables
Use Python `asyncpg` to iterate over `campaigns_<projectId>` tables and fetch `id, name, channel, segment_info, view_state, status`.

### Inspect recipient outcome counts
For push cases, query:
- `delivery_result_<projectId>`
- filter by `campaign_id` and `channel = 'push-notification'`
- group by `event_name`

This tells you whether the campaign actually sent and roughly how many unique users were involved.

## How to interpret user-property evidence safely
A common trap: reading current values from `users_<projectId>.encrypted_user_properties` and treating them as the values at send time.

Be careful:
- current user table values are **not guaranteed** to be the send-time snapshot
- if values changed after send, you can see apparent mismatches that are not filtering bugs
- delivery logs usually do not contain the fully decrypted user-property snapshot used at evaluation time

So if current DB values appear inconsistent with send eligibility, phrase the conclusion carefully:
- you can prove the campaign **was configured** to enforce the filter
- you often cannot prove from current tables alone whether a specific user violated the filter **at send time**

## Decrypting recipient properties in practice

### Where the encrypted values live
For current projects, user properties typically live in:
- `users_<projectId>.encrypted_user_properties`

Do not assume `user_<projectId>` exists; some projects only have the shadowing/encrypted table.

### Preferred way to decrypt
If you need actual plaintext user properties, prefer existing code paths that already do the right thing:
- `packages/userdb/src/index.ts`
  - `executeQueryWithShadowing(...)`
  - `decryptUserModels(...)`
- `services/server/web-console/src/repositories/UserRepository.ts`
  - uses the shadowing query path and returns decrypted rows

These paths handle:
1. fetching `encrypted_email`, `encrypted_phone_number`, `encrypted_user_properties`
2. loading per-column keys with `getCachedPlainDataKey(...)`
3. decrypting with `decryptWithAES256CBC(...)`
4. restoring original value types with `superjson.parse(...)`

### Permission caveat
Direct decryption requires AWS KMS decrypt permission.

If you try to reimplement decryption manually and hit something like:
- `AccessDeniedException` on `kms:Decrypt`

then the environment can still read PostgreSQL but **cannot** produce plaintext user properties.
In that case:
- fall back to proving campaign configuration / runtime additional conditions
- cluster recipients by raw encrypted buckets from `encrypted_user_properties->>'<attr>'`
- report that plaintext verification requires a runtime/role with KMS decrypt access (for example web-console/api-service task role)

### What you can still do without KMS decrypt
Even without decrypt permission, you can still:
- identify the campaign row and confirm `segment_info.additional_conditions`
- count delivery outcomes from `delivery_result_<projectId>`
- join recipients to `users_<projectId>`
- group by raw encrypted values of relevant properties (e.g. `push`, `마트오픈여부`) to find outliers

This is useful for narrowing suspicious recipients, but do **not** overstate it: encrypted bucket mismatches are not the same as plaintext proof.

## Known product / implementation caveats

1. **ALL targeting mode bypasses default user condition merge**
   - if `conditionTargetingMode === ALL`, defaults do not become runtime additional conditions

2. **Existing campaigns are not auto-updated when setting-level defaults change**
   - product explicitly warns that defaults changed later only apply automatically to newly created campaigns
   - for existing campaigns, the toggle must be turned off/on again to refresh from settings

3. **Editor schema vs runtime schema differ intentionally**
   - `view_state` may show defaults in `defaultChannelConditions`
   - runtime `segment_info.additional_conditions` is the operational field
   - do not assume empty `view_state.segment.details.additionalConditions` means defaults were not applied

## Useful git history
If behavior seems surprising, inspect these commits:
- `2a3fb8356` — `fix(web-console): 모수 계산 시 기본 유저 조건 반영 (#3418)`
- `441a1df71` — `fix(web-console): 기본유저조건을 저장 시점에만 merge하도록 수정 (#3404)`

These explain why the UI/editor may no longer show merged defaults directly while runtime still uses them.

## Recommended response structure
When reporting findings, keep it crisp:
1. **Conclusion** — yes/no: does it work as an additional filter?
2. **Code proof** — mention save-time merge and AND evaluation.
3. **Campaign proof** — mention actual `segment_info.additional_conditions` for the campaign.
4. **Caveats** — ALL mode, existing-campaign refresh behavior, current-value-vs-send-time limitation.

## Example conclusion template
- "구현상 기본 유저 조건은 추가 필터로 merge되어 AND 적용됩니다."
- "해당 캠페인도 `enableDefaultUserCondition=true`이고 runtime `segment_info.additional_conditions`에 조건이 저장되어 있습니다."
- "따라서 로직 자체가 빠진 것은 아니고, 특정 유저 사례는 발송 시점 속성값 / 캠페인 refresh 여부를 추가로 봐야 합니다."
