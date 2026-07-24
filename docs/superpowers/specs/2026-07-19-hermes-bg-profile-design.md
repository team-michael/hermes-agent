# BG Hermes Profile Design

## Summary

Create a fully isolated named Hermes profile for Brad Gilbert (`bg`) on the existing EC2 deployment. The profile uses its own Slack app, personal OpenAI Codex authentication, and personal GitHub authentication, receives the full current skill set, and can switch between the default Hermes runtime and Codex app-server runtime without sharing credentials or runtime state with another profile.

## Current Deployment Constraints

- Repository: `/home/ubuntu/.hermes/hermes-agent`
- Deployment branch: `main`, tracking `team-michael/main`
- Safe local assets: `ignored/local/`
- Live named profiles: `/home/ubuntu/.hermes/profiles/<name>`
- One user-level systemd gateway service per profile
- Secret and runtime files must never be committed

The older `local/hermes-patches` and `local/` paths in the supplied guide have been superseded by `team-michael/main` and `ignored/local/`. The isolation, overlay, canonical-source, and audit principles remain unchanged.

## Profile Identity and Source of Truth

Use `bg` as the profile slug. The Slack-facing name is `Brad Gilbert`, and the persona may refer to itself as `BG`.

Track only safe, durable assets:

```text
ignored/local/profiles/bg/
  SOUL.md
  config.overlay.yaml
  memories/
    MEMORY.md
    USER.md
  skills/
    .gitkeep
    accessibility/
      SKILL.md
      LICENSE
      references/
    building-native-ui/
      SKILL.md
      LICENSE
      references/
```

The live `SOUL.md` is a symlink to the repository copy. The overlay is deep-merged into the live config by `ignored/local/scripts/apply-local-state.py`. Runtime state stays under `/home/ubuntu/.hermes/profiles/bg`.

## Credential Isolation

Do not clone another profile. In particular, do not copy `.env`, `auth.json`, Slack tokens, AWS credentials, GitHub credentials, sessions, logs, databases, caches, or OAuth files.

BG receives two separate personal Codex logins:

1. Hermes `openai-codex` OAuth in the BG Hermes auth store.
2. Codex CLI OAuth in `/home/ubuntu/.hermes/profiles/bg/codex` for app-server mode.

Set `CODEX_HOME` only for the BG process. Existing profiles and the default Codex home remain untouched.

BG also receives an isolated personal GitHub login:

- GitHub CLI state: `/home/ubuntu/.hermes/profiles/bg/gh`
- Git global config: `/home/ubuntu/.hermes/profiles/bg/home/.gitconfig`
- Codex GitHub plugin state: inside the BG-specific `CODEX_HOME`

Set `GH_CONFIG_DIR` and `GIT_CONFIG_GLOBAL` only for the BG process. Authenticate GitHub CLI using the user's browser/device flow, then derive the GitHub username from `gh api user`. Set the commit name and email in the isolated Git config only after the user confirms them. Configure BG's GitHub remotes to use HTTPS through GitHub CLI so an unrelated machine-level SSH identity cannot be selected silently.

## Model and Runtime

- Provider: `openai-codex`
- Initial model: use `gpt-5.6-sol` when it appears in the authenticated account's Hermes model inventory and passes a smoke turn; otherwise use the provider-recommended Codex model shown by the live model picker
- Reasoning effort: `high` or lower for Slack reliability
- Default runtime: `auto` (Hermes agent loop)
- Optional coding runtime: `codex_app_server`

The default runtime keeps Hermes memory, session search, delegation, todo, and the complete Hermes tool surface. For code-heavy work, `/codex-runtime codex_app_server` enables Codex shell, patch, sandbox, plugins, and MCP migration. `/codex-runtime auto` returns to the complete Hermes runtime. Both runtime paths use BG-scoped credentials.

## Skills

The target is a capability superset of the current most complete profile, not a hard-coded count. The current baseline is `waddle_dee`, which reports 104 enabled skills. BG must contain every baseline skill plus every official optional skill available in the installed Hermes version.

Provision skills without copying credentials or runtime state:

1. Create a fresh profile so Hermes seeds the bundled skills.
2. Opt in and sync bundled skills.
3. Repair or restore all official optional skills.
4. Export the reference profile's non-bundled skill snapshot and import it into BG.
5. Apply repo-managed shared and BG-specific canonical skill symlinks.
6. Compare enabled skill names and sources with the reference profile and resolve any missing baseline entries.

Do not make a test assert an exact permanent count. Verification compares the two live inventories during setup and records differences because skill inventories legitimately change over time.

Never force-install a skill after a `CAUTION` or `BLOCKED` verdict. The approved fallback for a blocked reference entry is a BG-only, versioned compatibility copy with preserved MIT licensing, pinned provenance, minimal security/discovery edits, and a fresh `SAFE` Hermes scan. The accessibility copy is pinned to `addyosmani/web-quality-skills@95d6e255afe1596b557d7a8498517884438f5b3a`; the retired `building-native-ui` name aliases Expo's current `expo-native-ui` skill pinned to `expo/skills@8d72763f53c4fe11ed3ae0441b921bda821d2a74`. Safe external hub/direct installs still require their own fresh `SAFE` verdict. The final gate remains a normalized live inventory comparison with zero names missing from `waddle_dee`.

## Slack

Create a separate Slack app in Agent View with Socket Mode. Generate the manifest from the BG profile:

```bash
hermes -p bg slack manifest \
  --agent-view \
  --name "Brad Gilbert" \
  --description "BG, Minyong's personal AI agent" \
  --write
```

Verify both `display_information.name` and `features.bot_user.display_name` are `Brad Gilbert` before creating the Slack app.

Store only these Slack secrets in the live BG `.env`:

- `SLACK_BOT_TOKEN`
- `SLACK_APP_TOKEN`
- `SLACK_ALLOWED_USERS`
- optional home-channel identifiers

Do not enable `SLACK_ALLOW_ALL_USERS` or `GATEWAY_ALLOW_ALL_USERS`. The allowlist initially contains only the owner's Slack Member ID.

## Gateway Service

Install a dedicated user-level service named `hermes-gateway-bg.service`, with:

- `HERMES_HOME=/home/ubuntu/.hermes/profiles/bg`
- working directory `/home/ubuntu/.hermes/profiles/bg`
- the existing Hermes virtual environment and Node/Codex PATH
- restart-on-failure and start-on-login behavior matching current profile services
- BG-scoped `CODEX_HOME`, supplied through a profile-specific systemd drop-in rather than the secrets-only `.env`

Start the service only after Slack and model authentication are complete.

## Execution Sequence

1. Record the implementation plan and preflight the clean repository and current profile list.
2. Create the fresh `bg` live profile.
3. Add repository-managed BG identity, overlay, memory stubs, and skills directory.
4. Dry-run and apply local state, including the SOUL symlink.
5. Seed, restore, import, and compare the complete skill inventory.
6. Complete Hermes Codex OAuth and isolated Codex CLI OAuth with the user.
7. Complete isolated GitHub CLI authentication, Git identity setup, and BG-scoped Codex GitHub plugin installation.
8. Generate and validate the Slack manifest.
9. Have the user create and install the Slack app, then enter tokens directly on EC2.
10. Install and start the BG gateway service.
11. Run configuration, security, auth, service, GitHub, and Slack smoke checks.
12. Commit only safe assets and push the deployment branch after verification.

## Verification

- `ignored/local/scripts/audit-local-state.py` reports no new BG-related findings compared with the recorded preflight baseline. Existing findings in unrelated profiles or shared assets are documented and changed only with separate approval.
- `git diff --cached` contains no `.env`, auth files, tokens, runtime state, or credential material.
- The live `SOUL.md` resolves to the BG repository source.
- Overlay fields appear in the live BG config without overwriting unrelated defaults.
- Enabled skill inventory contains the complete reference set and all available official optional skills; every missing entry is resolved or documented.
- Hermes Codex authentication and Codex CLI authentication both succeed in BG-scoped stores.
- GitHub CLI reports the user's confirmed personal account from the BG-scoped config directory, Git uses the isolated identity and credential helper, and the Codex GitHub plugin is installed only in the BG Codex home.
- The Slack manifest contains the correct two display-name fields, Agent View, Socket Mode, required events, and required scopes.
- `hermes-gateway-bg.service` is active and enabled without `invalid_auth`, token-lock, or config errors.
- Slack DM smoke tests pass for `/help`, `/model`, `/codex-runtime`, a memory task, and a code/file task.

## Rollback

Before applying the overlay, keep the script-generated live-config backup. If setup fails, stop and disable only `hermes-gateway-bg.service`; existing profiles are unaffected. Do not delete the BG profile or Slack app without explicit user approval. Retain the safe repository assets for diagnosis unless the user requests removal.
