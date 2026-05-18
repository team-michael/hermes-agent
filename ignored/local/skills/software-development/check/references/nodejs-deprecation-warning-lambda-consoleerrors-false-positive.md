# Node.js Deprecation Warning Lambda ConsoleErrors False Positive

## Trigger signature

```
<timestamp> undefined ERROR (node:2) [DEP0040] DeprecationWarning: The `punycode` module is deprecated. Please use a userland alternative instead. (Use `node --trace-deprecation ...` to show where the warning was created)
```

## When it fires

- Node.js 22.x Lambda cold starts emit deprecation warnings to stderr.
- CloudWatch Logs captures the line because it contains the literal string `ERROR`.
- A coarse metric filter such as `%ERROR|Status: timeout%` on `/aws/lambda/<name>` matches this line and increments the `ConsoleErrors` metric.
- Scheduled/cron Lambdas that cold-start once a day (e.g., `payment-executor`) will trip this reliably at every invocation.

## Triage

1. Cross-check `AWS/Lambda Errors` for the function. **If `Errors == 0`, this is a false positive.**
2. The `undefined` request ID in the log line confirms it is a runtime-level warning, not an application `console.error`.
3. Run `aws logs filter-log-events` on the exact alarm-datapoint window (±5 min) to distinguish:
   - the deprecation warning (first line, `undefined` request ID)
   - any real handled business rejections that may appear later in the same invocation
4. Do **not** treat the deprecation warning as the sole root cause if a second real ERROR line exists in the same window; report both.

## Co-triggers in scheduled Lambdas

In `payment-executor` and similar scheduled batch Lambdas, the deprecation warning often appears alongside handled business errors caught in `try...catch`:

```
ERROR Failed to execute payment for <project_name>: PaymentError: Payple payment failed: [SPCD0002] 결제가능 최저금액은 100원 입니다.
ERROR Failed to execute payment for <project_name>: Error: Pricing plan is specified as 'enterprise', but no price found in spreadsheet
```

These are **handled rejections** in `services/lambda/payment-executor/lib/candidates.ts` (`try ... catch (e) { console.error(...) }`). The Lambda exits normally (`Errors=0`), and other projects continue processing.

## Scope attribution

- If a `project_id` is visible in `Payment details` INFO logs inside the same stream, use it directly.
- If only a project **name** is present (e.g., `Failed to execute payment for notifly-gamelog`), scan DynamoDB `project` table by `name` attribute to resolve the ID.

## Status

- `no_action` when `Lambda Errors=0` and the dominant signal is the deprecation warning or a handled business rejection.

## Remediation

- The deprecation warning itself is runtime-level and cannot be trivially suppressed without a Node.js version or dependency upgrade.
- For handled business rejections (e.g., missing spreadsheet entry), the fix is usually a **data/business configuration change**, not an engineering code change.
- Long-term, consider narrowing the metric filter to exclude `DeprecationWarning` or downgrading handled payment-failure logs to `WARN` after confirming the path is fully safe.
