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