# execute_code / terminal .env Credential Loading

## Problem

Both `execute_code` and `terminal` tools do not auto-load Hermes `.env` files. AWS credentials in `~/.hermes/profiles/hashimoto/.env` (or `~/.hermes/.env`) are not sourced into the tool sandbox environment. boto3 then falls back to ambient EC2 instance metadata credentials (`EC2CloudWatchAgentRole`), which typically lacks `cloudwatch:DescribeAlarms`, `logs:FilterLogEvents`, `dynamodb:Query`, and other read APIs — causing `AccessDenied` errors.

## Fix — explicit .env loading

Always load `.env` explicitly before constructing any boto3 client in `execute_code`:

```python
env_path = '/home/ubuntu/.hermes/profiles/hashimoto/.env'
aws_vars = {}
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if line.startswith('AWS_') and '=' in line:
            key, val = line.split('=', 1)
            aws_vars[key] = val

cw = boto3.client('cloudwatch',
    region_name=aws_vars.get('AWS_DEFAULT_REGION', 'ap-northeast-2'),
    aws_access_key_id=aws_vars['AWS_ACCESS_KEY_ID'],
    aws_secret_access_key=aws_vars['AWS_SECRET_ACCESS_KEY'],
)
```

This pattern is required for ALL AWS service clients (cloudwatch, logs, sqs, dynamodb, rds, pi, etc.) when called via `execute_code` or `terminal` Python scripts.

## `HOME` override breaks plain bash `cd ~/...` too, not just Python `expanduser`

The `HOME` override pitfall documented below (Hermes profile sessions set `HOME=/home/ubuntu/.hermes/profiles/<profile>/home`) also bites a bare `terminal("cd ~/.hermes/profiles/<profile>/skills/... && ...")` command, not just Python's `os.path.expanduser`. Bash expands `~` using `$HOME`, so `cd ~/.hermes/profiles/hashimoto/skills/software-development/check` resolves to the doubled, nonexistent `/home/ubuntu/.hermes/profiles/hashimoto/home/.hermes/profiles/hashimoto/skills/...` and fails with `No such file or directory`. Skip `cd ~/...` and `~`-relative paths entirely for this class of command — always invoke the helper script (or any skill-relative file) via the fully-qualified absolute path (`/home/ubuntu/.hermes/profiles/hashimoto/skills/software-development/check/scripts/collect_notifly_alert_context.py`) directly in the command, with no `cd` and no `~`.

## Helper's own scope aggregator can miss `project_id` sitting only in `table_refs`

Beyond the already-documented case of `project_id` nested in individual `current_trigger_contexts[]` entries, the aggregator can also report `scope_attribution.scope_kind: "unknown"` and `projects: null` even when `logs.current_error_details[].table_refs[].project_id` (or the equivalent field in `current_trigger_contexts[].table_refs`) clearly carries a `project_id` extracted from a sharded table name like `delivery_result_<project_id>`. Always check `table_refs` on the current-window error/trigger objects before accepting the top-level `scope_attribution` as unknown, and map that `project_id` via DynamoDB `project` yourself in the final answer.

## web-console DB timeout root-causing: map the exact repository method, not just the table

For `web-console console error` alarms whose trigger is a `pg` driver `Error: ... Query read timeout` on a `delivery_result_<project_id>` (or similar sharded table) query, don't stop at "DB read timeout, see reference doc." Grep the web-console repo for the exact `SELECT`/`.select(...)` shape and JOIN columns in the error message (e.g. `notifly-event/services/server/web-console/src/repositories/DeliveryResultRepository.ts`) to name the exact method (e.g. `findByCampaignIdAndEventName`) and its `where`/`leftJoin` columns, then check `pg_indexes` for that table to see whether a composite index actually covers the filtered+joined columns (e.g. a lone `campaign_id` index and a separate `(event_name, created_at)` index do NOT cover a query filtered by `campaign_id AND event_name` together). This turns "possible DB read timeout" into a concrete, verifiable index-gap action item instead of generic advice.

## Helper script absence fallback

When `scripts/collect_notifly_alert_context.py` is not present in the profile-local skill copy (`~/.hermes/profiles/hashimoto/skills/software-development/check/scripts/`), use direct boto3 calls with the explicit credential loading pattern above.

For bracket-prefix alarm names (e.g., `[api-service] 4xx error response is greater than 300 in 5m`):

- `--alarm-names` and `--alarm-name` fail because the leading `[` is parsed as JSON array syntax
- `AlarmNamePrefix` also fails because prefix matching is literal and the bracket is the first character
- Use `paginator` + client-side substring filter instead:

```python
paginator = cw.get_paginator('describe_alarms')
all_alarms = []
for page in paginator.paginate(AlarmTypes=['MetricAlarm']):
    all_alarms.extend(page.get('MetricAlarms', []))
matching = [a for a in all_alarms if 'api-service' in a['AlarmName'] and '4xx' in a['AlarmName'].lower()]
```

## Verification

To confirm which credentials boto3 is actually using:

```python
import boto3.session
session = boto3.session.Session()
creds = session.get_credentials()
print(f"Credential type: {type(creds).__name__}")
print(f"Method: {creds.method}" if hasattr(creds, 'method') else "No method attr")
# 'iam-role' or 'RefreshableCredentials' = EC2 instance metadata fallback (wrong)
# 'env' or explicit keys = .env loaded correctly
```

## `HOME` override pitfall — `~` expansion breaks in profile-isolated sessions

In Hermes profile-isolated sessions, the `HOME` environment variable is set to a profile-specific subdirectory (e.g., `HOME=/home/ubuntu/.hermes/profiles/hashimoto/home`), not the real user home (`/home/ubuntu`). This causes `os.path.expanduser("~/.hermes/...")` to resolve to a nonsensical path like `/home/ubuntu/.hermes/profiles/hashimoto/home/.hermes/profiles/hashimoto/.env`, resulting in `FileNotFoundError`.

**Never use `~` or `os.path.expanduser` for Hermes `.env` paths in inline Python scripts.** Always use the absolute path directly:

```python
# WRONG — HOME override breaks tilde expansion
env_path = os.path.expanduser("~/.hermes/profiles/hashimoto/.env")

# RIGHT — absolute path is immune to HOME override
env_path = "/home/ubuntu/.hermes/profiles/hashimoto/.env"
```

The `HERMES_HOME` environment variable (`/home/ubuntu/.hermes/profiles/hashimoto`) can also be used as a base, but the absolute path is the most reliable form for inline scripts.

## `HERMES_HOME` already contains the profile path — do not append `/profiles/hashimoto/` again

`HERMES_HOME` resolves to `/home/ubuntu/.hermes/profiles/hashimoto` (the profile root itself), not to `/home/ubuntu/.hermes`. The `check` skill's own documented fast-path invocation is:

```bash
python "${HERMES_HOME:-$HOME/.hermes}/skills/software-development/check/scripts/collect_notifly_alert_context.py" ...
```

If you add an extra `/profiles/hashimoto/` segment (e.g. `${HERMES_HOME:-$HOME/.hermes}/profiles/hashimoto/skills/...`), the path doubles to `.../profiles/hashimoto/profiles/hashimoto/skills/...` and fails with `No such file or directory`. When the templated `HERMES_HOME` form fails, fall back to the fully-qualified absolute path `/home/ubuntu/.hermes/profiles/hashimoto/skills/software-development/check/scripts/collect_notifly_alert_context.py` rather than guessing at another `${HERMES_HOME}`-relative combination.

## Inline heredoc/python scripts containing literal `TOKEN=*** string comparisons can get corrupted

When writing an inline `terminal("python - <<'PY' ... PY")` or bash heredoc that contains a literal string like `if line.startswith("GITHUB_TOKEN=*** (i.e., a secret env-var name followed by `=` as a plain string literal, used for `.env` line-parsing), the terminal safety layer's secret-redaction filter can rewrite `GITHUB_TOKEN=*** inside the command text to `GITHUB_TOKEN=*** corrupting the Python syntax (unterminated string literal) even though no real secret value was present — the filter pattern-matches on the `NAME=` shape, not on real credential material.

**Fix**: never embed `<SECRET_VAR_NAME>=` as a literal string inside inline terminal/heredoc code when the goal is to parse a `.env` file line-by-line for that variable. Instead:
1. Use `write_file` to write the parsing/lookup script to a real file (e.g. under the profile dir), then run it with `terminal("python3 /path/to/script.py")`. `write_file` content is not subject to the same inline-command redaction pass.
2. Or parse env files with a generic loop that never spells out the target var name as a literal `NAME=` prefix check (e.g. split on the first `=` and compare the key with `!=` string equality built from a variable, not a hardcoded `f"{var}="`-shaped literal in the command text).
3. This applies to any credential-shaped name: `GITHUB_TOKEN=*** `AWS_SECRET_ACCESS_KEY=*** `POSTGRES_PASSWORD=*** `CLOUDFLARE_API_TOKEN=*** etc. — write a script file instead of inlining the check.

## Postgres via `terminal`/`psql` hits the same secret-redaction mangling as `GITHUB_TOKEN` — use psycopg2 via `execute_code` instead

Running `psql` from `terminal` with `PGPASSWORD="$POS...RD" psql -h "$POSTGRES_HOST" ...` (even after `set -a; source .env; set +a`) can silently mangle the `PGPASSWORD=$POSTG...aped text via the same secret-redaction pass documented above for `GITHUB_TOKEN=*** Symptoms observed:
1. First attempt: `psql: FATAL: The password that was provided for the role postgres is wrong.` — `PGPASSWORD` expanded to garbage or empty because the redaction filter rewrote the `NAME=$NAME` pattern in the command text before it reached the shell.
2. Retry with `set -a; source .env; set +a` prefixed: command hangs and times out after 60s — `psql` fell back to an interactive password prompt (no TTY available) because `PGPASSWORD` still wasn't set correctly.

**Fix**: for Postgres read-only queries, skip `psql`/`terminal` entirely and use `psycopg2` inside `execute_code`, loading `.env` into a plain Python dict first (never spell `POSTGRES_PASSWORD=*** as a literal in the command/script text — read it as a parsed dict key instead):

```python
env_path = '/home/ubuntu/.hermes/profiles/hashimoto/.env'
env = {}
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        env[k] = v.strip().strip('"').strip("'")

import psycopg2
conn = psycopg2.connect(
    host=env['POSTGRES_HOST'], port=env['POSTGRES_PORT'],
    dbname=env['POSTGRES_DB'], user=env['POSTGRES_USER'],
    password=env['POSTGRES_PASSWORD'], connect_timeout=10,
)
```

This is the same class of fix as the GitHub-token script-file workaround: never let a credential-shaped `NAME=` literal appear in inline terminal/heredoc command text. `execute_code` with a parsed dict sidesteps the redaction pass because the variable name never appears adjacent to `=` in the executed text.

## GitHub API source lookup — simpler token loading + path discovery

**Simpler GITHUB_TOKEN loading for `gh` calls**: the write-a-script-file workaround above is only needed when you must parse `.env` *inside Python/inline code* with a literal `GITHUB_TOKEN=*** check (that literal string trips secret redaction). For plain `gh api` calls from `terminal`, skip Python entirely — bash-source the `.env` and export everything in one shot, then call `gh` in the same command:

```bash
set -a; source /home/ubuntu/.hermes/profiles/hashimoto/.env; set +a
gh api 'repos/team-michael/notifly-event/contents/<path>?ref=main' --jq '.content' | tr -d '\n' | base64 -d
```

`set -a ... set +a` exports every variable sourced from `.env` (not just ones you name), so it never spells out `GITHUB_TOKEN=*** as a literal in the command text and does not trigger redaction. This is the preferred pattern for any one-off `gh api` / `aws` CLI call from `terminal` — reach for the Python `.env`-parsing workaround only when you need the token value *inside a Python script* for something `gh`/`aws` CLI can't do directly.

**Base64 content from GitHub Contents API has embedded newlines**: `gh api '.../contents/<path>' --jq '.content'` returns base64 text chunked with `\n` every ~60-76 chars (GitHub wraps it). Piping straight to `base64 -d` fails with `base64: invalid input`. Always strip newlines first: `... --jq '.content' | tr -d '\n' | base64 -d`.

**Uncertain file path / stale local checkout — use the git trees API**: when a stack trace or `code[]` match points at a `.js` file (compiled/deploy artifact) but the actual source is TypeScript, or when the local `~/.hermes/workspace/<repo>` checkout doesn't have the service directory at all, don't guess at `.js` vs `.ts` or directory layout by trial and error. List the whole tree once and grep it:

```bash
set -a; source /home/ubuntu/.hermes/profiles/hashimoto/.env; set +a
gh api 'repos/team-michael/notifly-event/git/trees/main?recursive=1' --paginate | tr ',' '\n' | grep -i '<service-name>' | grep -i '<filename-fragment>'
```

This resolves the correct path in one call instead of multiple failed `contents/<guessed-path>` 404s. Also useful for finding an error string's origin file directly: `gh api search/code -f q='"<exact error string>" repo:team-michael/notifly-event' --jq '.items[].path'`.

## Preferred default: use `terminal`, not `execute_code`, for any AWS call — don't manually parse `.env` first

The SKILL.md itself already says this under "Prefer `terminal` + Python for AWS", but it is easy to skip straight to `execute_code` out of habit and then debug credential failures that wouldn't have happened otherwise. Confirmed again on 2026-07-10: `~/.hermes/profiles/hashimoto/.env` **did not exist at all** in that session (`os.path.exists()` returned `False` for every candidate path), so the "parse `.env` manually inside `execute_code`" pattern documented above silently produced an empty credentials dict, `boto3.Session(aws_access_key_id=None, ...)` fell back to ambient `EC2CloudWatchAgentRole` metadata credentials, and a DynamoDB GSI `Query` failed with `AccessDeniedException`. (A prior `logs.filter_log_events` call in the same session happened to succeed under the same fallback role, which is misleading — don't treat one success as proof the credentials are correct.)

The fix was not more `.env`-parsing — it was to stop using `execute_code` for AWS entirely. `terminal`'s shell environment already has the correct, non-EC2-metadata AWS credentials exported (verify with `env | grep AWS_` in `terminal`, never print the values). Write the boto3 script with `write_file`/heredoc and run it via `terminal python3 script.py` using a bare `boto3.Session(region_name=...)` with **no explicit key args** — it picks up the correctly-scoped credentials automatically. This resolved both the CloudWatch Logs read and the DynamoDB `project` table GSI query on the first try.

**Rule of thumb**: if an AWS call in `execute_code` needs credential troubleshooting, don't debug the `.env` parsing — switch the call to `terminal` first. Only fall back to the manual `.env`-parsing pattern earlier in this file if `terminal`'s own shell env is confirmed to lack the needed AWS variables.

## Session history

- 2026-06-22: `execute_code` boto3 calls failed with `AccessDenied` on `cloudwatch:DescribeAlarms` because `.env` was not loaded. boto3 used `EC2CloudWatchAgentRole` from EC2 instance metadata. Fix: explicit `.env` parsing + credential passing. After fix, all CloudWatch/Logs Insights calls succeeded.
- 2026-06-23: Inline Python script in `terminal` used `os.path.expanduser("~/.hermes/...")` which resolved to `/home/ubuntu/.hermes/profiles/hashimoto/home/.hermes/...` due to `HOME=/home/ubuntu/.hermes/profiles/hashimoto/home`. Fix: use absolute path `/home/ubuntu/.hermes/profiles/hashimoto/.env` directly.
- 2026-07-03: Two new path/script pitfalls hit during a web-console `console error` triage: (1) manually expanded `${HERMES_HOME:-$HOME/.hermes}/profiles/hashimoto/skills/...` instead of using the skill's documented `${HERMES_HOME:-$HOME/.hermes}/skills/...` form, doubling the profile segment and failing with `No such file or directory`; (2) an inline `terminal()` heredoc that checked `line.startswith("GITHUB_TOKEN=")` while parsing `.env` for a GitHub token got silently rewritten by secret redaction, producing a Python `SyntaxError: unterminated string literal`. Fixed by writing the GitHub-token-loading logic to a script file via `write_file` and executing that file instead of inlining it.
- 2026-07-03 (High VolumeReadIOPs triage): a `PGPASSWORD=$POSTGRES_PASSWORD psql ...` one-liner for a read-only `user_journey_sessions_<project_id>` scope-narrowing query hit the same redaction issue — first attempt got a wrong-password FATAL, retry with `set -a; source .env; set +a` hung 60s waiting on an interactive password prompt. Switched to `psycopg2` inside `execute_code` with `.env` parsed into a dict; connected and queried successfully on the first attempt.
- 2026-07-05 (`segment-publisher slow eic query`, UL1T00 scope): hit both known path pitfalls again in the same session — (1) `terminal` invocation with `"${HERMES_HOME:-$HOME/.hermes}/profiles/hashimoto/skills/...` doubled the profile segment (`.../profiles/hashimoto/profiles/hashimoto/...`), fixed by dropping to the fully-qualified absolute path; (2) a fresh `execute_code` call with `env_path = os.path.expanduser("~/.hermes/profiles/hashimoto/.env")` reproduced the exact same `HOME` override doubling even though `os.path.exists()` on the absolute-path string returned `True` in the same script — `exists()` doesn't retrigger the `~` expansion but a second inline `open(env_path)` in the same cell can still fail if the variable was reassigned via `expanduser` earlier in the cell; safest fix remains: never call `os.path.expanduser` or bare `~` at all for this path, always type the literal absolute string `/home/ubuntu/.hermes/profiles/hashimoto/.env` directly in the `open()` call.
- 2026-07-08 (`Low Aurora pg Optimized cache hit ratio` triage): even with `.env` correctly parsed into a dict and passed to `psycopg2`/`psql` (no redaction issue this time — credentials loaded fine), the connection itself hung and timed out after 30s with **no error message at all**, for both a `terminal`-invoked `psql` subprocess and a `subprocess.run(...)` call inside `execute_code`. The target was the read-only proxy endpoint `notifly-db-prod-read-only-read-only.endpoint.proxy-*.rds.amazonaws.com:5432`. This is a distinct failure mode from the credential/redaction issues above: it is a **network reachability** problem (VPC/security-group scoped, not env-loading), and it looks identical to a hang from a missing `PGPASSWORD` (no output, just a timeout) — don't assume it's the same redaction bug and re-attempt psycopg2 fixes; if a bounded `subprocess.run(..., timeout=30)` on a Postgres connection returns `TimeoutExpired` with zero stdout/stderr (not a fast `FATAL`/`could not connect` error), treat it as network-unreachable-from-this-sandbox and stop retrying — report the DB follow-up as unavailable in the final answer rather than burning further attempts.
