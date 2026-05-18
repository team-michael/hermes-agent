# web-console "maximum number of registered templates" console error

## Context

`web-console console error` CloudWatch alarm fires with the log signature:

```
Error: The maximum number of registered templates.
```

## Root cause

This error string does **not** exist in the Notifly codebase. It originates from **external provider APIs** during campaign upsert:

- **Kakao Biz Message Center** (`KakaoBizMessageApiClient.createTemplate`)
- **NHN Cloud SMS** (`TextMessageTransformer` → `_makeTemplate` → NHN Cloud templates API)

When a user saves or updates a campaign with Kakao brand message or text-message nodes, `MessageTransformer.transform` delegates to channel-specific transformers that register templates with the external provider. If the provider-side template quota for that sender key/project is full, the provider returns this exact error message.

**Not** an AWS limit. **Not** a limit set in our code. Purely an external provider business restriction.

## Code path

```
CampaignService.upsertCampaign
  → upsertStandardCampaign
    → MessageTransformer.transform
      → KakaoBrandMessageTransformer.transform  → KakaoBizMessageApiClient.createTemplate
      → TextMessageTransformer.transform          → NHN Cloud create template API
```

Files involved:
- `services/server/web-console/src/services/CampaignService.ts`
- `services/server/web-console/src/domains/message/transformers/MessageTransformer.ts`
- `services/server/web-console/src/domains/message/transformers/KakaoBrandMessageTransformer.ts`
- `services/server/web-console/src/domains/message/transformers/TextMessageTransformer.ts`
- `services/server/web-console/src/clients/KakaoBizMessageApiClient.ts`
- `services/server/web-console/src/pages/api/lib/text_message/nhncloud.ts`

## Triage guidance

- **Scope**: Usually service-wide (`web-console`). The log does not contain `project_id` or `campaign_id`.
- **Impact**: Campaign save/update failure for users whose provider template quota is exhausted.
- **Frequency**: Often recurrent for specific tenants; daily counts vary with campaign editing activity.
- **Immediate action**: Generally `no_action` for the alert itself — the provider rejection is a handled expected business outcome.
- **Long-term fix**: Log-level downgrade from `ERROR` → `WARN`/`INFO` for this specific handled provider rejection, plus pre-flight template quota check or user-facing guidance.

## Verification

If asked whether this is "our code limit" vs "external limit", grep the exact string:

```bash
grep -rI "The maximum number of registered templates" --include="*.ts" --include="*.tsx" --include="*.js" services/ packages/ lambdas/
```

Result: **no matches** — confirming external origin.

## Related pattern: Kakao BizMessage content max length

A second, distinct Kakao BizMessage validation error caught by the same coarse metric filter:

```
Error: Failed to create Kakao BizMessage template: 파라미터 content은(는) 최대길이(76) 제약 조건을 준수하지 않습니다.
```

**Root cause**: Kakao BizMessage Center template parameter validation. The `content` field exceeds the provider's max length (76 characters for this template type). This is a **handled external provider rejection**, not a service bug.

**Distinguishing from template count limit**: This error is about **content length**, not **template count**. The two signatures are mutually exclusive:
- `The maximum number of registered templates.` → provider-side template quota exhausted
- `파라미터 content은(는) 최대길이(76) 제약 조건을 준수하지 않습니다.` → single template content too long

**Triage guidance**: Same as template count limit — `no_action` for the alert itself. Long-term fix is log-level downgrade (`ERROR` → `WARN`/`INFO`) or pre-flight client-side length validation before calling the provider.

## Related

- `ops-email-receiver` Sentry pipeline can also trigger `web-console console error` alarms; see `references/sentry-email-alert-pipeline-false-positives.md` for a different `web-console`-specific false-positive pattern.
