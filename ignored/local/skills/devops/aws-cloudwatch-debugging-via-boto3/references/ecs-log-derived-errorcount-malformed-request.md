# ECS log-derived ErrorCount: malformed/empty request bodies

Use this reference when an ECS service alarm is driven by a CloudWatch Logs metric filter like `%ERROR|Error|Exception%` and the pasted logs show framework request-body conversion errors.

## Recognize the pattern

Typical Ktor/Jackson example:

```text
BadRequestException: Failed to convert request body to class ...
JsonConvertException: Illegal json parameter found: No content to map due to end-of-input
MismatchedInputException: No content to map due to end-of-input
```

This usually means the request reached the route/auth boundary, but JSON deserialization failed before business logic. It is different from:

- DB/storage failure
- downstream queue failure
- application validation failure after parsing
- ECS task/process health failure

For Ktor, inspect route handlers for `call.receive<T>()`, `call.receiveNullable<T>()`, `call.request.contentLength()`, and the installed `ContentNegotiation` converter. If handlers catch `Exception` and respond `200`/empty while also logging `log.error`, CloudWatch can alarm even though clients see HTTP 200.

## Investigation workflow

1. **Parse the Chatbot/custom-action output**
   - log group, region, account, start/end window
   - exact exception class and target request class
   - repeated target endpoints/classes

2. **Verify account before querying logs**
   - run STS identity before CloudWatch calls
   - if credentials point to another account, do not infer from missing log groups; state the account mismatch and continue from repo + pasted evidence

3. **Map exception target class to routes**
   - search the repo for the request class and the log prefix
   - read the route files and note where `receive<T>()` happens relative to auth/business services
   - confirm whether request body is required in OpenAPI/proto/docs

4. **Inspect alarm definition, not just logs**
   - find Terraform/log metric filter definitions for the service
   - capture `filterPattern`, `period`, `evaluation_periods`, `threshold`, and `statistic`
   - a 1-minute / threshold=1 log metric alarm means one malformed request with `ERROR` can page/notify

5. **Correlate to deploy/provenance**
   - inspect prior fixes for the same symptom (`git log --follow`, PR search by exact file/error phrase)
   - check whether the latest prod deploy commit contains the fix (`git merge-base --is-ancestor <fix> <deploy-sha>`)
   - if a prior fix only handled `Content-Length == 0`, consider blank/whitespace/truncated bodies or `Content-Length > 0` with EOF as remaining cases

6. **Classify impact**
   - if parsing fails before service calls, affected rows/events/properties were not written
   - if the handler returns `200 + empty response`, client-side failure detection may be poor
   - separate “server health incident” from “malformed client request causing data drop + noisy alarm”

## Final-answer shape

- Verdict: server/infra fault vs malformed client request vs needs live log access
- Trigger: exact log-derived metric and threshold
- Code path: route file + `receive<T>()` line + serialization plugin
- Scope: endpoints/classes affected; whether business logic ran
- Deploy/fix status: prior fixes and whether deployed
- Next actions:
  - identify client via access log/user-agent/requestId
  - make SDK/client send valid JSON (`{"events":[]}`, `{"properties":[]}`, etc.) or skip empty POSTs
  - handle empty/blank body consistently server-side
  - downgrade expected malformed-request logs from `ERROR` or exclude them from server ErrorCount alarms

## Pitfalls

- Do not call it an ECS outage just because the alarm name is ECS ErrorCount; log-derived metrics often count application/framework log text.
- Do not assume `Content-Length == 0` is the only empty-body failure mode. `No content to map due to end-of-input` can also come from blank/truncated bodies.
- Do not claim live CloudWatch verification if credentials are for a different AWS account; use repo evidence and pasted logs, and mark that live log lookup was blocked by account scope.
- Do not dump API keys or request payloads from `.http` files or logs in the final answer; only cite path/line mechanics and redact sample credentials.
