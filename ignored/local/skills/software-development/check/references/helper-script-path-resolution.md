# Helper script path resolution in profile sessions

## STOP — do this before typing any path (read this first)

Never type `$HOME`, `${HERMES_HOME:-...}`, or any shell-variable-based path
for the `check` helper. Every failure logged below (8+ sessions,
2026-07-02 through 2026-07-09) started from a variable-expansion template
and produced a doubled or malformed path. The only call shape with a 100%
success rate is a **fully hardcoded absolute path**, taken verbatim from the
`[Skill directory]` annotation injected at the bottom of this SKILL.md, on
the *first* try:

```
terminal(
  command="python /home/ubuntu/.hermes/profiles/hashimoto/skills/software-development/check/scripts/collect_notifly_alert_context.py --text '...' --alarm-name '...' --region ap-northeast-2",
  workdir="/home/ubuntu"
)
```

`workdir="/home/ubuntu"` is cheap insurance but not required if the path is
fully literal (no `$HOME`/`${HERMES_HOME}` anywhere in the string) — a fully
literal absolute path has succeeded even without an explicit `workdir`.

## Why this happened

Named profiles use an isolated `HOME`. Reconstructing the helper path with
`~/.hermes/profiles/<name>` or by appending `/profiles/<name>` to
`HERMES_HOME` therefore creates doubled paths such as:

- `.../profiles/hashimoto/profiles/hashimoto/skills/...`
- `.../profiles/hashimoto/home/.hermes/profiles/hashimoto/skills/...`

`SKILL.md` v1.3.0 fixes the former variable-based fast-path example. It now
requires copying the fully resolved script path from the injected
`linked_files`/`[Skill directory]` metadata and forbids broad filesystem
searches. Keep this reference as the detailed failure explanation; do not add
new dated occurrence logs for the same path-construction mistake.

## Solution

Always copy the helper's fully resolved absolute path from the injected
`linked_files`/`[Skill directory]` metadata. For this Hashimoto profile it is:

```bash
python /home/ubuntu/.hermes/profiles/hashimoto/skills/software-development/check/scripts/collect_notifly_alert_context.py ...
```

If the annotation is not visible, use
`skill_view(name="check", file_path="scripts/collect_notifly_alert_context.py")`
to verify the linked file and its resolved skill directory. Do not derive the
path from `~`, `$HOME`, or `HERMES_HOME`.

## Pitfall — skill name for self-patching

When calling `skill_manage`/`skill_view` to patch this skill's own files, the
registered skill `name` is the bare `check` (not the qualified
`software-development/check` shown in the injected directory header). Use
`skills_list(category="software-development")` to confirm the bare name
before patching.

## When the helper script is entirely missing

If `scripts/` doesn't exist under the skill directory, don't block the
investigation:
1. Load the relevant `references/` file for the alarm family (e.g.
   `api-service-4xx-authenticate-noise.md` for `[api-service] 4xx` alarms).
2. If the reference has clear classification thresholds and many confirmed
   sessions, classify directly from the reference.
3. State in the final answer that live verification wasn't possible due to
   missing helper script, but the reference pattern match is sufficient.
4. Don't retry the helper or try to reconstruct it — use direct AWS CLI via
   `terminal` if credentials are available, or proceed reference-based.

## Pitfall — `search_files` false negatives for the helper script

`search_files` (ripgrep-backed) can return 0 results for
`collect_notifly_alert_context.py` even though the file exists on disk. Use
`skill_view(name="check", file_path="scripts/collect_notifly_alert_context.py")`
or try the absolute path directly in `terminal` instead of trusting a
negative `search_files` result.

## Pitfall — helper script requires PYTHONPATH for local package import

The entry point imports `from notifly_alert_context.cli import main`, and
that package lives alongside it in `scripts/`. A bare
`python /absolute/path/to/collect_notifly_alert_context.py` can fail with
`ModuleNotFoundError: No module named 'notifly_alert_context'` if `scripts/`
isn't on `PYTHONPATH`.

Fix:
```bash
SKILL_DIR="/home/ubuntu/.hermes/profiles/hashimoto/skills/software-development/check"
PYTHONPATH="$SKILL_DIR/scripts" python "$SKILL_DIR/scripts/collect_notifly_alert_context.py" \
  --text '...' --alarm-name '...' --region ap-northeast-2
```
Always derive `SKILL_DIR` from the `[Skill directory]` annotation, never from
`HERMES_HOME` or `$HOME/.hermes`.

## Pitfall — large helper JSON output gets truncated when captured through `execute_code`'s `terminal()`

The helper's full JSON output routinely exceeds 20KB. Calling
`hermes_tools.terminal(...)` from inside `execute_code` and then
`json.loads(r['output'])` directly truncates around ~20,000 chars, so
`json.loads` fails partway through. This is a capture-buffer limit, not a
helper bug.

Fix:
1. Run the helper via the top-level `terminal` tool (not `execute_code`),
   redirecting stdout to a file under the profile dir, e.g.
   `... > /home/ubuntu/.hermes/profiles/<profile>/scratch_alert.json`.
2. In a follow-up `execute_code` call, `json.load(open(path))` — reads the
   full file from disk, not subject to the stdout capture cap.
3. Do not double-`json.loads()` the result. If you redirected raw stdout to
   the file, the file already **is** the helper's top-level JSON object
   (`can_answer_root_cause`, `detected`, `alarm`, `history`, `logs`, ...).
   Wrapping it in `outer = json.loads(raw); inner = json.loads(outer['output'])`
   is wrong and raises `KeyError: 'output'`.

## Pitfall — do not double-unwrap `{"output": ...}` when reading a redirected file with plain file I/O

The `{"output": "...", "exit_code": ..., "error": ...}` envelope you see when
viewing a `terminal()` tool-call result is the **tool call's own response
envelope**, not bytes written to disk. A file written via shell redirect
(`... > out.json 2>&1`) contains only the script's raw stdout/stderr text —
plain JSON starting with `{"can_answer_root_cause": ...}`, no wrapper. Reading
that file back with plain file I/O (`open(path).read()` or `read_file`) gives
the true raw bytes directly; only unwrap `['output']` when parsing the result
of a `terminal()` tool call itself, never when reading a file a shell
redirect wrote directly.
