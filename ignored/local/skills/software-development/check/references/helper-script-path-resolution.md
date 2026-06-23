# Helper script path resolution in profile sessions

## Problem

The `check` skill examples use a template path with `HERMES_HOME`:
```bash
python "${HERMES_HOME:-$HOME/.hermes}/skills/software-development/check/scripts/collect_notifly_alert_context.py" ...
```

In Hermes profile sessions, `HERMES_HOME` may resolve to `~/.hermes/profiles/<profile>/` rather than `~/.hermes/`, causing the command to fail with a doubled or missing path segment.

## Solution

Always resolve the helper script against the absolute path shown in the injected `[Skill directory]` annotation at the bottom of the loaded SKILL.md. For the current profile the path is:
```bash
python /home/ubuntu/.hermes/profiles/hashimoto/skills/software-development/check/scripts/collect_notifly_alert_context.py ...
```

If the annotation is not visible, derive the path from the active Hermes profile directory (`~/.hermes/profiles/<profile>/skills/software-development/check/scripts/collect_notifly_alert_context.py`).

## When the helper script is entirely missing

If the `scripts/` directory does not exist under the skill directory (not a path resolution issue but a deployment gap), do not block the investigation. Follow this fallback order:

1. Load the relevant `references/` file for the alarm family (e.g., `api-service-4xx-authenticate-noise.md` for `[api-service] 4xx` alarms, `segment-publisher-slow-eic-query-noise.md` for segment-publisher alarms).
2. If the reference contains classification guidance with clear `no_action` / `needs_fix` thresholds and 10+ documented sessions confirming the same pattern, classify directly from the reference.
3. State in the final answer that live verification was not possible due to missing helper script, but the reference pattern match is sufficient for classification.
4. Do not retry the helper or attempt to reconstruct it — use direct AWS CLI via `terminal` if credentials are available, or proceed with reference-based classification.
5. Do not block the final answer on environment issues when the alarm pattern is unambiguous and the reference contains sufficient classification guidance.