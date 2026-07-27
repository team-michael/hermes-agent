# kds-consumer Lambda RangeError: Invalid count value

A recurring real error in the `kds-consumer` Lambda function, caught by the broad
`%ERROR|Status: timeout%` ConsoleErrors metric filter. This is **not** a false
positive; the `AWS/Lambda` `Errors` metric is elevated during the alarm window.

## Error signature

```
ERROR Error in preprocess event RangeError: Invalid count value: -1
  at String.repeat (<anonymous>)
  at getValidEventTimestampInMilliseconds (/var/task/lib/event_utils.js:420:37)
  at addValidTimestampToEventData (/var/task/lib/event_utils.js:464:15)
  at Array.map (<anonymous>)
  at _preprocessEvent (/var/task/index.js:49:14)
```

## Root cause

`getValidEventTimestampInMilliseconds` in
`services/lambda/kds-consumer/lib/event_utils.ts` computes:

```ts
const timestamp = time?.toString()?.replace(/\./g, '');
return parseInt(timestamp + '0'.repeat(TIME_LENGTH - timestamp.length), 10);
```

When the input `time` field has **more digits than `TIME_LENGTH`** after removing
decimal points, `TIME_LENGTH - timestamp.length` is negative and `String.repeat()`
throws a `RangeError`. Because `_preprocessEvent` does not catch this, the Lambda
invocation fails and the Kinesis batch record is lost for that item.

## How to distinguish from metric-filter noise

1. Check `AWS/Lambda` `Errors` metric for `kds-consumer`.
   - If `Errors > 0`, it is a real invocation failure, not harmless log text.
2. Check the `AWS/Lambda` `Throttles` metric.
   - If also zero, the issue is the code path, not concurrency limits.
3. Look at `LastModified` on the function configuration.
   - A deploy near the alarm window may have changed event validation logic.

## Scope

Log payloads often carry one or more `project_id` values (e.g. `melting`,
`regather`), but no `campaign_id` or `user_journey_id` because the failure
happens during generic event preprocessing before campaign matching.

Report the known project/product names from DynamoDB, but mark campaign/user
journey as unknown.

## Fix target

`services/lambda/kds-consumer/lib/event_utils.ts`, function
`getValidEventTimestampInMilliseconds`.

Guard the repeat count:

```ts
const pad = Math.max(0, TIME_LENGTH - timestamp.length);
return parseInt(timestamp + '0'.repeat(pad), 10);
```

Or validate the input timestamp length before padding and return `undefined`
for malformed values.

## Recurrence history

- First observed in large spikes (hundreds per day) when malformed event
timestamps arrive from specific project integrations.
- Quieter days show single-digit or low-double-digit errors.
- The alarm fires on any `ERROR` log line, so even one malformed event per
period crosses the threshold of `1.0`.

## Triage decision tree

- `Errors == 0`, `Throttles == 0`, and no stack trace in logs → likely metric
  filter noise or benign log text; consider `no_action`.
- `Errors > 0` with this stack trace → real code bug; use `needs_fix` and name
  the exact file/function target.
