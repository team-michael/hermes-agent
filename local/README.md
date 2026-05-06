# Local Hermes Maintenance

This directory contains local, team-managed Hermes assets that should survive
`hermes update` through the `local/hermes-patches` branch.

Tracked here:

- `skills/`: common custom skills shared by profiles.
- `profiles/<name>/skills/`: profile-specific custom skills.
- `profiles/<name>/SOUL.md`: profile identity source copy.
- `profiles/<name>/config.overlay.yaml`: safe config fragments to merge into
  live profile configs.
- `scripts/apply-local-state.py`: reapply overlays and skill symlinks.
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
