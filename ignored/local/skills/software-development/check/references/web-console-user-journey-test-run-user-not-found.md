# web-console `console error` — user journey "test run" `Error: user not found`

## Signature
```
Error: user not found
    at d.reduce.databaseSessions (/app/services/server/web-console/.next/server/pages/api/projects/[projectId]/user_journeys/[userJourneyId]/run.js:...)
```

## Root cause
Endpoint: `services/server/web-console/src/pages/api/projects/[projectId]/user_journeys/[userJourneyId]/run.ts`
(POST handler, "test run this user journey" feature in the console UI).

Flow:
1. Console user enters one or more `externalUserIds` and clicks "test run" on a user journey.
2. Handler calls `UserRepository.getUserByExternalUserId(projectId, externalUserId)` for each ID.
3. `users.reduce(...)` at line 36-40: if `user[0]` is falsy (external user ID not found in
   `users_<project_id>`), it does `throw new Error('user not found')`.
4. Caught by the route's own `catch (err) { console.error(err); res.status(500).json({ error: err.message }); }`
   (lines 78-81).

This is a **handled console-side input validation failure**: the operator typed/pasted an external
user ID that doesn't exist for that project. The 500 status + `console.error` is just how this
particular route reports the validation failure back to the browser — there is no data loss, no
service crash, and no other request is affected.

## Why it trips the alarm
`/aws/ecs/notifly-services-prod/web-console console error` uses a broad `ConsoleErrors` metric
filter (`%ERROR%`-style) on the whole `web-console` log group, `threshold=1`, `period=60s`,
`evaluation_periods=1`. Any single `console.error(...)` call anywhere in web-console can trip it.
This alarm's 7d/30d top signatures are a grab-bag of unrelated handled rejections (see
`ecs-console-error-false-positive-patterns.md`, `web-console-max-registered-templates-external-provider.md`,
`web-console-kakao-image-upload-validation-error.md`, `web-console-liquidjs-abort-message-false-positive.md).
`Error: user not found` from this route is one more member of that family.

## Scope
The current trigger line for this route does not include `projectId`/`userJourneyId` in the log
message itself (they're in the request path, not printed). If scope is required, check the access
log line immediately before/after the error timestamp for the `/api/projects/<projectId>/user_journeys/<userJourneyId>/run`
path segment. Otherwise report project/user-journey scope as unknown for this specific error.

## Classification
`no_action` when this is the sole or dominant current-window trigger and the alarm has already
returned to `OK`. Not a service bug — no code path change needed for a single occurrence.

Escalate to `needs_fix` only if this specific signature becomes the *dominant* driver of alarm
volume across many days (would suggest console UX around test-run user ID entry needs a friendlier
client-side existence check before submit, rather than a 500).

## Long-term fix (only if this signature becomes a repeat contributor)
In `run.ts`, return `400` with a structured `{ error: 'user_not_found', externalUserId }` instead of
throwing and falling into the generic `catch -> console.error -> 500`. That keeps the failure mode
visible in application logs at `warn` (or omits it from the ERROR metric filter) without inflating
the noisy `console error` alarm.
