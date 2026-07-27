# Check Skill Helper: can_answer_root_cause Gate Pitfall

## Pitfall

The `check` skill helper returns `can_answer_root_cause: true` even when `missing_required_context` contains `required` severity items (e.g., `current_trigger_contexts: []`). This creates a false sense of permission — the helper has reached an internal confidence gate, but structural blockers remain.

**Symptom:**
```json
{
  "can_answer_root_cause": true,
  "missing_required_context": [
    {
      "key": "current_trigger_contexts",
      "severity": "required",
      "reason": "No CloudWatch log context found in current alarm window"
    }
  ]
}
```

Proceeding directly to final answer produces incomplete root cause (e.g., citing 7d/30d historical top signatures instead of the actual current trigger log).

## Correct Gate Logic

**Priority order: check `missing_required_context` FIRST**

1. If `missing_required_context` contains any `required` severity items → this is a blocker, regardless of `can_answer_root_cause` value.
2. If `can_answer_root_cause: false` AND no `required` items → check `required_followups` for reusable manual steps; execute prioritized read-only steps.
3. If `can_answer_root_cause: true` AND no `required` items in `missing_required_context` → safe to finalize from helper output alone.

## Required Context Items

Highest priority to fill when marked `required`:

- **`current_trigger_contexts`**: The actual log lines that triggered the most recent ALARM transition. Essential for root-cause description. Cannot finalize without seeing what actually breached the threshold.
- **`scope_basis`**: Project/product/campaign/user-journey attribution. Mandatory final-answer field. Must fill before answering "범위".
- **`logs.current_error_details`**: For log-derived alarms, the concrete error that crossed the filter. Distinguish from 7d/30d noise.

## Remediation in check Skill

When the helper produces `can_answer_root_cause: true` but critical context is empty:

1. **Manual log retrieval**: Use `filter-log-events` or `get-log-events` bounded to the exact alarm-transition window to extract current trigger logs
   - Alarm transition time: `history.latest_alarm_transition.timestamp`
   - Window: ±900s or per-alarm metric period

2. **Consult existing references**: If the alarm is a known pattern (e.g., `user-csv-mailer lambda error`, `segment-publisher slow eic query`), the `check` skill's `references/` directory already contains triage recipes. Check whether the pattern matches before inventing new investigation steps.

3. **Fail closed, not open**: If current trigger context remains unavailable after bounded attempts (e.g., logs not yet ingested, stream expired), state explicitly that the current trigger is unverified and cite only what is confirmed (recurrence, metrics, historical signature). Do NOT invent a specific root cause without evidence.

## Example: user-csv-mailer

**Helper output:**
```
can_answer_root_cause: true
missing_required_context: [
  { key: "current_trigger_contexts", severity: "required", reason: "No CloudWatch log context..." }
]
```

**Incorrect action**: Finalize from 30d top signatures alone, which show two distinct failure modes ("No such project" vs. "Status: timeout") without disclosing which one caused THIS alarm.

**Correct action**:
1. Note that `current_trigger_contexts` is required.
2. Run bounded `get-log-events` on the specific log stream identified in helper output.
3. Extract the actual trigger line (e.g., "ERROR Invoke Error" or "REPORT ... Status: timeout").
4. Check `references/user-csv-mailer-timeout-s3-multipart.md` for the pattern match.
5. Finalize with the specific root cause that applies to the current alarm, not all historical patterns combined.

## Session Example

From session 2026-06-17 (user-csv-mailer investigation):

**Helper returned:**
- `can_answer_root_cause: true`
- `missing_required_context: [ { key: "current_trigger_contexts", severity: "required" } ]`
- `top_signatures: [ "ERROR ... No such project", "REPORT ... Status: timeout" ]`

**Error**: Proceeding directly to final answer would blend both signatures.

**Correct**: Retrieved actual log stream for 2026/06/15/[$LATEST]a7f0a13f46424376a9b4616aa6bb2699 to extract "No such project" as the current trigger, distinguished from prior-day timeouts, and used the reference to confirm DynamoDB lookup failure is NOT the S3 multipart issue.

## Related

- `lambda-timeout-patterns` skill § "Triage Steps" — concrete log-extraction patterns.
- `references/lambda-timeout-empty-log-gap.md` (in check skill) — Generic Lambda timeout diagnosis workflow.
