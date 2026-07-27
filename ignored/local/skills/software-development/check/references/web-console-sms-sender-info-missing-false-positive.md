# web-console: "문자 메시지 발신자 정보를 불러오는 중 오류가 발생했습니다" — missing SMS sender info, not a service bug

## Trigger signature
Sentry-proxied `ConsoleErrors` alarm on `/aws/ecs/notifly-services-prod/web-console/sentry`
(alarm name `/aws/ecs/notifly-services-prod/web-console/sentry alert`) firing on a browser-side
React error captured by Sentry and emailed to `ops@ops.greyboxhq.com` via SES, ingested by
`ops-email-receiver`.

`sentryAlert.issue.message` (and email subject `WEB-CONSOLE-E3 - Error: ...`):
```
문자 메시지 발신자 정보를 불러오는 중 오류가 발생했습니다.
```
`sentryAlert.issue.transaction`: `/console/products/[productId]/campaign/create`

## Root cause
Thrown intentionally in the client component that renders the "실패 시 대체 문자" (SMS failover)
sender-phone-number selector on the campaign-create page:

`services/server/web-console/src/domains/failover-text-message/components/sender-phone-number-selector.tsx:46`
```ts
const notiflySenderInfo = senderKeys?.textMessageSenderInfo?.notifly;
if (!notiflySenderInfo) {
    throw new Error('문자 메시지 발신자 정보를 불러오는 중 오류가 발생했습니다.');
}
```
This fires whenever a project opens the campaign-create screen's SMS-failover sender selector
without having registered a Notifly SMS/text-message sender number for that project. The
component's `AsyncBoundary errorFallback` catches it and renders a disabled selector plus an
inline Korean hint to register sender info in project settings — the UI degrades gracefully,
campaign creation and other channels are unaffected. Sentry still captures the thrown `Error`
because React error boundaries re-report to Sentry even when the app-level fallback handles it.

## Scope extraction
`sentryAlert.request.url` in the payload carries the console URL, e.g.
`https://console.notifly.tech/console/products/<productId>/campaign/create`. Extract
`<productId>` and map via DynamoDB `project` table GSI `product_id-project_id-index`
(same technique as `references/web-console-scope-attribution-via-access-logs.md` and
`references/sentry-email-alert-pipeline-false-positives.md`). No campaign/user-journey ID is
present — the error occurs before any campaign is created, so campaign/user journey scope is
correctly "특정 불가".

## Baseline / frequency
Observed sporadically (~1-3 times per 30 days across different projects), tied to individual
projects opening the SMS-failover selector while sender info is unregistered. Not correlated
with a deploy or traffic spike.

## Classification
`no_action` by default — this is a client-side UI guard for a per-project configuration gap,
not a service fault. No delivery/data-loss/campaign-blocking impact. Long-term noise reduction
(optional, non-urgent): downgrade the throw/catch in `sender-phone-number-selector.tsx` to a
handled state (e.g. render the fallback without `throw`, or wrap in a try/catch that only
`console.warn`s) so Sentry/`ConsoleErrors` stops treating an expected empty-config state as an
error-level event. Only escalate to `needs_fix` if this signature starts dominating alarm volume
or recurs many times for the same project (suggests a config-loading bug rather than genuine
missing sender info).
