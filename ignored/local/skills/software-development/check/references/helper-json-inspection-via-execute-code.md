# Inspecting `collect_notifly_alert_context.py` output — canonical rule

**Recurred again 2026-07-11** (`payment-executor lambda error` Slack-subscription
session): the very first helper invocation was piped through
`... 2>&1 | head -c 6000`, got a truncated fragment, retried with `head -c 8000`
(still the banned shortcut, just a bigger number). Then, after correctly
redirecting to a file on the *second* helper run, an `execute_code` call did
`outer = json.loads(raw); data = json.loads(outer['output'])` against that file
— the exact banned double-unwrap — and hit `KeyError: 'output'`. The next
`execute_code` call repeated the identical mistake a second time in the same
session (`inner = json.loads(outer['output'])` again). Recovery only worked on
the third attempt, after abandoning `execute_code` entirely and reading the
file with `terminal` + `jq`. This is now confirmed recurring even when the
agent has full knowledge that this reference exists and is loaded as part of
the auto-loaded `check` skill — reading the pitfall is not the failure mode,
*habit at the keyboard* is. Treat `head -c` / `tail -c` on helper stdout, and
`json.loads(x['output'])` on anything that isn't literally `terminal()`'s own
just-returned dict, as banned keystrokes, not "usually a bad idea." If you
catch yourself typing either shape, stop mid-command and go straight to
`terminal(...) > /home/ubuntu/.hermes/profiles/hashimoto/tmp/<name>.json` then
`jq` — do not "finish this one call the old way and fix it next time."

This exact mistake has recurred 11+ times across sessions (most recently 2026-07-10, `[api-service] 4xx error response is greater than 300 in 5m` Slack-subscription session, where the tail-piping pitfall was repeated on the *first* invocation — `tail -c 6000` then a retried `tail -c 8000`, both against raw helper stdout — and then a follow-up `execute_code` call did `json.loads(outer['output'])` against a *file* that had already been redirected with `> file.json 2>&1`, hitting `KeyError: 'output'` twice in a row across two separate `execute_code` calls, exactly matching the already-documented 2026-07-09 recurrence of the same alarm/session type below. Recovery only worked after abandoning `execute_code` entirely and switching to `terminal` + `jq` directly against the file. This confirms the pitfall note in this file was not sufficient to prevent the repeat — the mandate to go straight to `terminal`+`jq` on the first pass needs to be followed literally, not treated as an optional shortcut-avoidance tip. Before that, most recently 2026-07-10, `web-console console error` session, where the tail-piping pitfall *and* the malformed-JSON-on-inline-output pitfall were both made in the same session — first `head -c 6000` on the raw helper stdout on the first invocation, then a follow-up `execute_code` call ran `terminal()` and tried `json.loads(r['output'])` directly, hitting `Invalid control character` and then, after retrying with `json_parse`/`strict=False`, a different `Expecting ',' delimiter` error further into the string — both caused by raw stack-trace newlines/control chars embedded in `logs.current_trigger_contexts`/`current_error_details`, not just the previously-documented `code[].context_excerpt` Terraform blobs. Recovery only worked after redirecting to a file and switching to `search_files` + `read_file` line-based inspection. Before that, 2026-07-09, `[api-service] 4xx error response` session, where the tail-piping pitfall *and* the unwrap-on-a-file mistake were both made in the same session — first `tail -c 12000` on the raw helper stdout produced a garbled mid-string fragment, then two separate `execute_code` calls tried `json.loads(outer['output'])` against a file that was already the raw unwrapped stdout, hitting `KeyError: 'output'` twice before falling back to plain `json.load(open(path))`. Before that, 2026-07-08, `ScheduledBatchDelivery-P2-FCMLatencyP99` session, made the identical unwrap mistake twice in the same session). Read this once, apply it, stop re-deriving it from scratch.

**This pitfall keeps recurring specifically because the two-step workflow (run helper, then inspect) tempts a "quick peek" via `head`/`tail`/`execute_code` before committing to the file+jq path below. Do not take that shortcut on the first pass, even for a "just checking if it worked" glance — go straight to step 1 of the preferred workflow every time, no exceptions.**

**Default to `jq` via `terminal`, not `execute_code`, for the first inspection pass.** `jq` never has this ambiguity — there's no `['output']` envelope to accidentally apply. Reach for `execute_code` + `json.load(open(path))` only when you need to cross-reference multiple fields programmatically (see workflow step 3 below), and even then apply the one rule exactly: no unwrap, no shape-sniffing, no retry-with-a-different-parser.

## The one rule

There are exactly two possible shapes for helper output, and they are never nested:

1. **`terminal()`'s own inline return value** (shown directly in the conversation) — wrapped as `{"output": "<script stdout>", "exit_code": N, "error": ...}`. To get the real data here: `json.loads(result['output'])`.
2. **A file on disk written via `terminal("... > file.json 2>&1")`** — contains the script's raw, unwrapped stdout. It starts with `{"can_answer_root_cause": ...`, NOT `{"output": ...}`. To get the real data here: `json.load(open(path))` directly. There is no `['output']` key to unwrap — that envelope only exists on `terminal`'s own return value, never on a file it redirected into.

If `json.loads(data['output'])` raises `KeyError: 'output'` even once, that error *is* the diagnostic: it means you're looking at shape (2) and applying the shape-(1) unwrap. Fix immediately by dropping the unwrap — do not retry the same code, do not add a second defensive check, do not try `ast.literal_eval`. Just do `json.load(open(path))` and move on.

Fastest way to disambiguate when unsure: `data = json.load(open(path)); print(list(data.keys()))`. If you see `['can_answer_root_cause', 'alarm', 'history', 'logs', ...]` you're already holding the real data — stop unwrapping.

## Pitfall — piping the first invocation through `tail`/`head` for a "quick look"

Do not run the helper with `--text ...` and pipe its stdout straight through `tail -c N` or
`head -c N` as a fast preview before deciding whether to redirect to a file. The helper's JSON
often exceeds the truncation window in the middle of a `code[].context_excerpt` blob (embedded
Terraform/log text), so `tail -c 6000` can hand you a fragment that starts mid-string with
broken escaping — unreadable and not valid JSON, costing a wasted call. Always go straight to
step 1 below (redirect to an absolute file path) on the *first* invocation, then inspect with
`jq`. There is no cheaper "peek first" shortcut that reliably works on this helper's output.

## Preferred workflow

1. Run the helper via `terminal`, redirecting to a **fully-qualified absolute path** (never `~` — in this environment `$HOME` is remapped to `/home/ubuntu/.hermes/profiles/hashimoto/home`, so `~/...` silently expands to a doubled `.../home/.hermes/profiles/hashimoto/...` path you'll lose track of):
   ```bash
   mkdir -p /home/ubuntu/.hermes/profiles/hashimoto/tmp
   python /home/ubuntu/.hermes/profiles/hashimoto/skills/software-development/check/scripts/collect_notifly_alert_context.py \
     --text '<alert text>' --alarm-name '<exact alarm name>' --region ap-northeast-2 \
     > /home/ubuntu/.hermes/profiles/hashimoto/tmp/<name>.json 2>/home/ubuntu/.hermes/profiles/hashimoto/tmp/<name>.err
   ```
2. Inspect with **`jq`** via `terminal` for exact nested values in one shot — faster and more precise than guessing line ranges with `search_files`/`read_file`, and avoids `execute_code` shape confusion entirely:
   ```bash
   F=/home/ubuntu/.hermes/profiles/hashimoto/tmp/<name>.json
   jq '{can_answer_root_cause, missing_required_context, alarm, history, scope: .scope_attribution}' "$F"
   jq '.logs.current_error_details' "$F"
   ```
3. Use `execute_code` + `json.load(open(path))` only when you need to cross-reference multiple fields programmatically (e.g. correlating `logs.current_error_details` against `scope_attribution`). Apply the one rule above — no unwrap, no `try/except` shape-sniffing.
4. Fall back to `search_files`/`read_file` against the file only when you need unstructured free-text context (e.g. `code[].context_excerpt` blocks) that `jq` can't cleanly extract.
5. `rm -f` the temp JSON/err files once the final answer is composed — don't leave alert-context dumps on disk between sessions.

## Fallback when the JSON file itself won't parse (even with `strict=False`)

Sometimes the helper's own output is not strictly valid JSON — this has been observed when `code[].context_excerpt` embeds large raw Terraform/log blocks with unescaped control characters or malformed nesting from the token-preview truncation. Symptoms: `json.load(open(path))` raises `Invalid control character` or, after retrying with `hermes_tools.json_parse` (`strict=False`), a *different* error like `Expecting ':' delimiter` at a later offset — meaning the file is genuinely malformed past a certain point, not just strict-mode pickiness.

Do not keep retrying JSON parsers (`ast.literal_eval`, manual regex repair, etc.) on a file that fails both strict and non-strict `json.loads`. Instead, drop straight to line-based inspection, which works regardless of JSON validity:
1. `read_file(path, limit=N, offset=M)` to page through the raw text and read `can_answer_root_cause`, `alarm`, `history`, `scope_attribution`, etc. directly off the printed `key: value` lines — the file is still human-readable JSON text even if a downstream parser chokes on one embedded blob.
2. `search_files(pattern='"current_error_details"|"current_trigger_contexts"|"scope_attribution"|"lambda":|"errors_sum"', path=file, output_mode='content')` to jump straight to the line numbers of the fields you need, then `read_file(offset=that_line, limit=100)` to read the surrounding block.
3. This combination (search_files to locate, read_file to read the window) fully replaces JSON parsing for triage purposes — every field needed for the fixed 5-label answer format is reachable this way without ever getting a clean parse.

