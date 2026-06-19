# Notifly Mixpanel cohort sync auth split

Use this when Mixpanel cohort recurring sync returns `401 Invalid credentials`, especially after an API key rotation.

## Mechanism

There are two related but distinct credential checks:

1. `api-service` `/authenticate`
   - Uses Cognito `USER_PASSWORD_AUTH` / `InitiateAuth` with `COGNITO_API_CLIENT_ID`.
   - A workflow that runs `aws cognito-idp admin-set-user-password` can make this path pass.

2. `integration-service` `/mixpanel/projects/{projectId}/cohorts`
   - Does **not** call Cognito.
   - Parses HTTP Basic Auth and compares `accessKey/password` by exact string match against `project.cognito_api_auth.username/password` loaded through `ProjectService`.
   - `ProjectService` first reads Redis key `project` and falls back to DynamoDB table `project`; it also has a short in-process Caffeine cache.

So Cognito can be correct while Mixpanel cohort sync still fails if `project.cognito_api_auth` or the Redis `project` cache is stale/different.

## Diagnostic sequence

1. Query integration-service logs for the project and `/mixpanel/projects/`.
   - `Received: action=add_members/remove_members, cohortId=..., members=...` proves Mixpanel delivered payloads.
   - `StatusCode=401` + `Invalid credentials` proves Basic Auth mismatch at integration-service, not URL reachability.
2. Compare with any API-key rotation workflow.
   - If the workflow only does `admin-set-user-password`, it changed Cognito only.
   - It did not update DynamoDB `project.cognito_api_auth` or invalidate Redis `project` cache.
3. Check audit logs / project update evidence around the rotation time.
   - Web-console key rotation path should update Cognito, update `project.cognito_api_auth` for projects under the product, and invalidate `project` cache.
4. Remediation is to make the three states agree:
   - Cognito API user password
   - DynamoDB `project.cognito_api_auth`
   - Redis `project` cache / invalidation

## User-facing explanation

Phrase the root cause as: “api-service passes because it authenticates against Cognito; integration-service fails because it validates Mixpanel Basic Auth against `project.cognito_api_auth` cached from project metadata. The workflow updated only Cognito, so the two sources diverged.”
