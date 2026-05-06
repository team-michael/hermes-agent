# Local Hermes Maintenance

This directory contains local, team-managed Hermes assets that should survive
`hermes update` through the fork's `team-michael/main` branch. The local
checkout stays on `main`: upstream updates come from `origin/main`, while
local profile and patch changes are pushed to `team-michael/main`.

This state is stored at `ignored/local/` so upstream `origin/main` ignores it
through the existing `ignored/` rule, while `team-michael/main` force-tracks it.

Tracked here:

- `skills/`: common custom skills shared by profiles.
- `profiles/<name>/skills/`: profile-specific custom skills.
- `profiles/<name>/SOUL.md`: profile identity source copy.
- `profiles/<name>/config.overlay.yaml`: safe config fragments to merge into
  live profile configs.
- `profiles/<name>/memories/*.md`: profile memory Markdown files that should
  survive updates. Runtime `.lock` files are intentionally excluded.
- `scripts/apply-local-state.py`: reapply overlays, memories, and skill
  symlinks.
- `scripts/audit-local-state.py`: check for drift and accidental secrets.

The repo-managed Andrej identity is a normal named profile at
`profiles/andrej/`; it is not the default `~/.hermes` profile.

Do not commit runtime state or credentials here:

- `.env`
- `auth.json`
- `state.db*`
- `sessions/`
- `logs/`
- `gateway.pid`
- `gateway.lock`
- OAuth/cache files

Runtime skill directories under `~/.hermes/**/skills` should point back to
this repo with symlinks. The live profile configs must include the matching
`skills.external_dirs` entries so Hermes treats the repo paths as trusted skill
directories.
