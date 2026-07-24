# BG Hermes Profile Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create and verify an isolated personal Hermes profile named `bg` for Brad Gilbert, connected only to Minyong Lee's Slack, OpenAI Codex, and GitHub accounts, with the complete installed Hermes skill inventory.

**Architecture:** Keep safe, durable BG assets in `ignored/local/profiles/bg/` and runtime/authentication state in `/home/ubuntu/.hermes/profiles/bg/`. Use a dedicated Hermes user service and profile-scoped `CODEX_HOME`, `GH_CONFIG_DIR`, and `GIT_CONFIG_GLOBAL` so the BG process cannot inherit another user's Codex or GitHub state. Keep the standard Hermes runtime as the default and enable Codex app-server runtime on demand.

**Tech Stack:** Hermes Agent v0.18.2, Python/YAML profile overlays, OpenAI Codex CLI 0.144.4, GitHub CLI 2.91.0, Slack Agent View with Socket Mode, systemd user services, Git.

**Design reference:** `docs/superpowers/specs/2026-07-19-hermes-bg-profile-design.md`

## Global Constraints

- Work on EC2 host `ubuntu@10.0.171.186` in `/home/ubuntu/.hermes/hermes-agent`.
- Freeze the current Hermes deployment while setting up BG. Do not run `hermes update`, rebase, merge `origin/main`, or change dependencies in this plan. The deployment branch tracks `team-michael/main`; `origin/main` is the official upstream used only to report the available update gap.
- Do not clone any existing profile and do not read or copy another profile's `.env`, OAuth files, GitHub state, sessions, logs, databases, or caches.
- Do not modify, delete, or repair unrelated profiles or shared assets. The existing local-state audit findings are a recorded baseline, not part of this change.
- Never paste OAuth tokens, Slack tokens, GitHub tokens, device authorization codes, or the contents of auth files into Git, this task, terminal commands, or logs.
- Stop at each marked **USER CHECKPOINT** and let the user complete browser authorization or private value entry.
- Use `/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes` and `/home/ubuntu/.nvm/versions/node/v24.15.0/bin/codex` explicitly in non-interactive shells.
- Use `apply_patch` to create or change version-controlled text. Since `apply_patch` is not installed on the EC2 host, create the patch artifact locally, copy it to the exact remote path, and inspect `git diff` before committing.
- Commit only safe repository assets. Live profile data, manifests, `.env`, `auth.json`, Codex/GitHub state, runtime databases, and systemd runtime files remain untracked.

## Review Findings That Affect Execution

1. The attached guide's `local/` path has moved to `ignored/local/`; its `local/hermes-patches` branch has been replaced by the current `main` branch tracking `team-michael/main`.
2. The deployment branch is not behind `team-michael/main`; it is currently ahead only by the safe setup-document commits. It is 17 commits behind the official `origin/main`. Updating from the official upstream must be a separate, post-BG change so setup failures are not mixed with upgrade failures.
3. The original SSH key at `/Users/minyonglee/Desktop/notifly/14_행정_보안_증빙/keys/notifly-pg-bastion-server-keypair.pem` has mode `0644`; OpenSSH correctly rejects it. It must be changed to `0600` before direct use.
4. `ignored/local/scripts/audit-local-state.py` already reports one unrelated `hashimoto` memory lock and Python `__pycache__` files in a shared skill. This plan verifies that BG adds no new finding and does not delete the existing files.
5. Some existing profiles contain loose file permissions and allow-all environment-variable names. BG must use `0600` for credential-bearing files and must not define `SLACK_ALLOW_ALL_USERS` or `GATEWAY_ALLOW_ALL_USERS`.
6. “All skills installed” means all Hermes skills are present and enabled. Skills backed by other services still require those services' own credentials; this plan activates personal Codex, personal GitHub, and the dedicated Slack app only.

---

## Task 1: Secure Access and Capture the Immutable Preflight Baseline

**Files:**

- Modify permissions only: `/Users/minyonglee/Desktop/notifly/14_행정_보안_증빙/keys/notifly-pg-bastion-server-keypair.pem`
- Read only: `/home/ubuntu/.hermes/hermes-agent`
- Read only: `/home/ubuntu/.hermes/profiles`

- [ ] **Step 1: Fix the original key's local permissions**

Run on the user's Mac:

```bash
chmod 600 '/Users/minyonglee/Desktop/notifly/14_행정_보안_증빙/keys/notifly-pg-bastion-server-keypair.pem'
stat -f '%Sp %N' '/Users/minyonglee/Desktop/notifly/14_행정_보안_증빙/keys/notifly-pg-bastion-server-keypair.pem'
```

Expected: permissions begin with `-rw-------`.

- [ ] **Step 2: Verify the pinned SSH host**

Use the already observed host keys and stop if either changes unexpectedly:

```text
RSA     SHA256:RpGXktJirP2O/U6IQBsSxXbhYsUhGWFhJeNKwRg+mnQ
ED25519 SHA256:nljCKFy07ycjQ9yOWP4DWCqNBPvt+ifsK7x735r5Wu8
```

- [ ] **Step 3: Prove BG does not already exist**

Run on EC2:

```bash
test ! -e /home/ubuntu/.hermes/profiles/bg
test ! -e /home/ubuntu/.hermes/hermes-agent/ignored/local/profiles/bg
/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes profile list
```

Expected: both `test` commands exit 0 and `bg` is absent from the list. If either path exists, stop and inspect it; do not overwrite or delete it.

- [ ] **Step 4: Record repository and version state**

```bash
cd /home/ubuntu/.hermes/hermes-agent
git status --short
git branch --show-current
git rev-list --left-right --count HEAD...team-michael/main
git rev-list --left-right --count HEAD...origin/main
/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes version
```

Expected: working tree clean, branch `main`, no commits missing from `team-michael/main`, deployment version `v0.18.2`, and no action taken on the 17-commit official-upstream gap. Local ahead counts include the safe design and plan commits.

- [ ] **Step 5: Record the existing local-state audit baseline**

```bash
cd /home/ubuntu/.hermes/hermes-agent
ignored/local/scripts/audit-local-state.py 2>&1 | tee /tmp/bg-preflight-local-state-audit.txt
```

Expected non-zero status with only the previously observed unrelated findings:

- `ignored/local/profiles/hashimoto/memories/MEMORY.md.lock`
- shared `ignored/local/skills/software-development/check/scripts/notifly_alert_context/__pycache__/` entries

Stop if the baseline includes any BG path or new secret/runtime category.

---

## Task 2: Create the Fresh Profile and Canonical BG Assets

**Files:**

- Create live profile: `/home/ubuntu/.hermes/profiles/bg/`
- Create: `ignored/local/profiles/bg/SOUL.md`
- Create: `ignored/local/profiles/bg/config.overlay.yaml`
- Create: `ignored/local/profiles/bg/memories/MEMORY.md`
- Create: `ignored/local/profiles/bg/memories/USER.md`
- Create: `ignored/local/profiles/bg/skills/.gitkeep`

- [ ] **Step 1: Create a fresh, non-cloned profile**

```bash
/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes profile create bg \
  --description "Brad Gilbert (BG), Minyong Lee's isolated personal AI and coding agent for Slack, Codex, and GitHub work."
mkdir -p /home/ubuntu/.hermes/profiles/bg/workspace
chmod 700 /home/ubuntu/.hermes/profiles/bg
chmod 600 /home/ubuntu/.hermes/profiles/bg/.env
```

Expected: a new `/home/ubuntu/.hermes/profiles/bg` exists with a fresh config and empty, mode-`0600` `.env`. No existing profile was used as a clone source.

- [ ] **Step 2: Add the exact BG persona file**

Create `ignored/local/profiles/bg/SOUL.md` with:

```markdown
# Brad Gilbert (BG)

You are Brad Gilbert, usually called BG. You are Minyong Lee's personal AI and coding agent.

## Communication

- Use polite, natural Korean by default. Use English when the user asks or when the artifact should be in English.
- Lead with the answer or outcome. Keep routine updates concise and make decisions, assumptions, and blockers explicit.
- Produce directly usable work. Verify important facts against the real source before presenting them as current.

## Working Style

- Use the available skill that best matches the task and follow its instructions.
- For coding work, inspect the actual repository, preserve unrelated changes, test in proportion to risk, and report what was verified.
- Use Hermes memory for durable user preferences and project context, but never store passwords, tokens, private keys, or OAuth material in memory.
- Treat destructive actions, external publishing, purchases, and messages to other people as confirmation-required unless Minyong has explicitly authorized the exact action.

## Isolation and Security

- Operate only with BG's own profile state and authenticated accounts.
- Do not inspect, copy, or use another Hermes profile's credentials, sessions, memories, or runtime files unless Minyong explicitly requests a narrowly scoped comparison.
- Never reveal secrets. Redact sensitive values from logs, summaries, and messages.
- GitHub changes must use BG's isolated GitHub CLI and Git identity. Confirm the repository and account before pushing or opening a pull request.
```

- [ ] **Step 3: Add the exact safe overlay**

Create `ignored/local/profiles/bg/config.overlay.yaml` with:

```yaml
model:
  provider: openai-codex
  default: gpt-5.6-sol
  openai_runtime: auto
providers:
  openai-codex:
    request_timeout_seconds: 900
    stale_timeout_seconds: 900
compression:
  enabled: true
  threshold: 0.85
  target_ratio: 0.30
  protect_last_n: 20
  hygiene_hard_message_limit: 400
agent:
  reasoning_effort: high
  gateway_notify_interval: 0
terminal:
  cwd: /home/ubuntu/.hermes/profiles/bg/workspace
display:
  busy_input_mode: queue
  interim_assistant_messages: false
  tool_progress: all
  platforms:
    slack:
      streaming: false
      tool_progress: all
approvals:
  mode: manual
  timeout: 60
  cron_mode: deny
security:
  redact_secrets: true
session_reset:
  mode: none
platform_toolsets:
  cli:
    - browser
    - clarify
    - code_execution
    - cronjob
    - delegation
    - file
    - image_gen
    - memory
    - messaging
    - session_search
    - skills
    - terminal
    - todo
    - tts
    - vision
    - web
  slack:
    - browser
    - clarify
    - code_execution
    - cronjob
    - delegation
    - file
    - image_gen
    - memory
    - messaging
    - session_search
    - skills
    - terminal
    - todo
    - tts
    - vision
    - web
update:
  local_patch_branch: main
skills:
  external_dirs:
    - /home/ubuntu/.hermes/hermes-agent/ignored/local/profiles/bg/skills
    - /home/ubuntu/.hermes/hermes-agent/ignored/local/skills
```

- [ ] **Step 4: Add the exact initial memory files**

Create `ignored/local/profiles/bg/memories/USER.md` with:

```markdown
# User

- Name: Minyong Lee
- Default language: polite, natural Korean
- BG is Minyong's personal Hermes agent.
- Personal Codex, GitHub, and Slack accounts must remain isolated from every other Hermes profile.
```

Create `ignored/local/profiles/bg/memories/MEMORY.md` with:

```markdown
# BG Memory

This file stores durable, non-secret context learned while working with Minyong Lee.

## Security Boundary

- Never store tokens, passwords, private keys, device codes, cookies, or OAuth files here.
- Never copy memories or runtime state from another Hermes profile without explicit approval.
```

Create the empty directory marker `ignored/local/profiles/bg/skills/.gitkeep`.

- [ ] **Step 5: Test the local-state application before applying**

```bash
cd /home/ubuntu/.hermes/hermes-agent
ignored/local/scripts/apply-local-state.py --dry-run --link-soul bg
```

Expected: only BG paths are proposed; no existing profile or shared file is replaced.

- [ ] **Step 6: Apply and verify BG state**

```bash
cd /home/ubuntu/.hermes/hermes-agent
ignored/local/scripts/apply-local-state.py --link-soul bg
readlink -f /home/ubuntu/.hermes/profiles/bg/SOUL.md
/home/ubuntu/.hermes/hermes-agent/venv/bin/python - <<'PY'
from pathlib import Path
import yaml

config = yaml.safe_load(Path('/home/ubuntu/.hermes/profiles/bg/config.yaml').read_text())
assert config['model']['provider'] == 'openai-codex'
assert config['model']['default'] == 'gpt-5.6-sol'
assert config['model']['openai_runtime'] == 'auto'
assert config['agent']['reasoning_effort'] == 'high'
assert config['approvals']['mode'] == 'manual'
assert config['security']['redact_secrets'] is True
assert 'memory' in config['platform_toolsets']['slack']
assert 'delegation' in config['platform_toolsets']['slack']
PY
```

Expected: `SOUL.md` resolves to `ignored/local/profiles/bg/SOUL.md`; assertions exit 0.

- [ ] **Step 7: Commit only the safe canonical assets**

```bash
cd /home/ubuntu/.hermes/hermes-agent
git add -f ignored/local/profiles/bg/SOUL.md \
  ignored/local/profiles/bg/config.overlay.yaml \
  ignored/local/profiles/bg/memories/MEMORY.md \
  ignored/local/profiles/bg/memories/USER.md \
  ignored/local/profiles/bg/skills/.gitkeep
git diff --cached --check
git diff --cached --name-only
git diff --cached | grep -E '(xox[baprs]-|gh[pousr]_[A-Za-z0-9_]+|sk-[A-Za-z0-9])' && exit 1 || true
git commit -m "feat: add isolated BG Hermes profile assets"
```

Expected: only the five safe BG files are committed and the token-pattern scan returns no match.

---

## Task 3: Install and Compare the Complete Hermes Skill Inventory

**Files:**

- Modify live profile: `/home/ubuntu/.hermes/profiles/bg/skills/`
- Read only reference: `/home/ubuntu/.hermes/profiles/waddle_dee/skills/`
- Temporary snapshot: `/tmp/bg-waddle-skills-snapshot.json`
- Temporary inventories: `/tmp/bg-reference-skill-names.txt`, `/tmp/bg-skill-names.txt`

- [ ] **Step 1: Export only the reference skill installation snapshot**

```bash
/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes -p waddle_dee \
  skills snapshot export /tmp/bg-waddle-skills-snapshot.json
chmod 600 /tmp/bg-waddle-skills-snapshot.json
```

Expected: the snapshot contains skill package metadata, not credentials. Inspect the keys and run the same token-pattern scan before import.

- [ ] **Step 2: Seed bundled and every official optional skill**

```bash
/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes -p bg skills opt-in --sync
/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes -p bg \
  skills repair-official all --restore --yes
```

Expected: bundled skills are present and all optional official skills in this Hermes version are restored.

- [ ] **Step 3: Import the reference profile's non-bundled skill packages**

```bash
/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes -p bg \
  skills snapshot import /tmp/bg-waddle-skills-snapshot.json
cd /home/ubuntu/.hermes/hermes-agent
ignored/local/scripts/apply-local-state.py bg
```

Expected: the reference's hub/URL/official installations are installed for BG, and repo-managed shared/BG skill links are applied. If Hermes reports a caution verdict, inspect the exact skill and provenance; do not use `--force` without a separate safety decision.

- [ ] **Step 4: Compare effective enabled skill names without relying on a fixed count**

```bash
COLUMNS=300 /home/ubuntu/.hermes/hermes-agent/venv/bin/hermes -p waddle_dee \
  skills list --enabled-only \
  | awk -F '│' '/enabled/ {name=$2; gsub(/^ +| +$/, "", name); print name}' \
  | sort -u > /tmp/bg-reference-skill-names.txt

COLUMNS=300 /home/ubuntu/.hermes/hermes-agent/venv/bin/hermes -p bg \
  skills list --enabled-only \
  | awk -F '│' '/enabled/ {name=$2; gsub(/^ +| +$/, "", name); print name}' \
  | sort -u > /tmp/bg-skill-names.txt

comm -23 /tmp/bg-reference-skill-names.txt /tmp/bg-skill-names.txt
```

Expected: `comm` prints nothing. BG may legitimately contain additional official skills; it must not miss a reference skill.

- [ ] **Step 5: Verify sources and explain credential-dependent skills**

```bash
COLUMNS=300 /home/ubuntu/.hermes/hermes-agent/venv/bin/hermes -p bg skills list --enabled-only
```

Expected: all skills are enabled. Record any skill that requires an external account as installed but not yet service-authenticated. Do not copy another user's environment variables to make such a skill appear operational.

### Authorized Task 3 Remediation Addendum

If the exact snapshot import produces a fresh `CAUTION` or `BLOCKED` verdict, stop that import path and never use `--force`. Minyong approved this no-force remediation for the blocked community `accessibility` entry and the retired `building-native-ui` catalog entry:

1. Run the three application/retrieval RED evaluations before authoring, then repeat them as GREEN evaluations against the installed compatibility skills.
2. Add BG-only compatibility trees under `ignored/local/profiles/bg/skills/`, preserving each MIT license and exact provenance:
   - `accessibility`: `addyosmani/web-quality-skills@95d6e255afe1596b557d7a8498517884438f5b3a`, patch `security-1`.
   - `building-native-ui`: compatibility alias for `expo-native-ui` from `expo/skills@8d72763f53c4fe11ed3ae0441b921bda821d2a74`, patch `compatibility-1`.
3. Pin accessibility audit commands to `lighthouse@13.4.0` and `@axe-core/cli@4.12.1`. Remove unsafe/global or generic unpinned install examples without inventing versions.
4. Require exact frontmatter/path/static checks, a fresh Hermes `SAFE` verdict for each tree, no new local-state audit finding beyond the Task 1 baseline, and the focused 225-test suite before commit.
5. Commit only the two compatibility trees and these two tracked documents. Fast-forward clean deployment `main`, then apply BG state from the deployment checkout so live links never resolve into the worktree.
6. Install `frontend-design`, `copywriting`, and the HWP direct URL pinned to `NomaDamas/k-skill@19f1ced7834c9dccf7f89ec1d4917dc66758b4a8` without force and only on fresh `SAFE` verdicts.
7. Generate normalized, non-empty `COLUMNS=300` inventories. `comm -23` must be empty, so the reference missing count is zero; extras are allowed and recorded.

---

## Task 4: Connect Minyong's Personal Codex Account in Both Runtime Layers

**Files:**

- Create private state: `/home/ubuntu/.hermes/profiles/bg/codex/`
- Create private config: `/home/ubuntu/.hermes/profiles/bg/codex/config.toml`
- Modify private Hermes auth store under `/home/ubuntu/.hermes/profiles/bg/`

- [ ] **Step 1: Create the private Codex home**

```bash
mkdir -p /home/ubuntu/.hermes/profiles/bg/codex
chmod 700 /home/ubuntu/.hermes/profiles/bg/codex
```

- [ ] **Step 2: Authenticate the Hermes `openai-codex` provider**

Run in an interactive SSH terminal:

```bash
/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes -p bg \
  auth add openai-codex --type oauth --label minyong-personal --no-browser --timeout 900
```

**USER CHECKPOINT:** The command prints a device/browser authorization flow. Minyong completes it while signed in to the personal Codex account. Do not paste the code into this task.

Verify:

```bash
/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes -p bg auth status openai-codex
```

Expected: the BG profile reports a usable `openai-codex` OAuth credential.

- [ ] **Step 3: Authenticate the isolated Codex CLI**

```bash
CODEX_HOME=/home/ubuntu/.hermes/profiles/bg/codex \
  /home/ubuntu/.nvm/versions/node/v24.15.0/bin/codex login --device-auth
```

**USER CHECKPOINT:** Minyong completes the Codex device authorization in the browser using the same intended personal account.

Verify without printing credentials:

```bash
CODEX_HOME=/home/ubuntu/.hermes/profiles/bg/codex \
  /home/ubuntu/.nvm/versions/node/v24.15.0/bin/codex login status
find /home/ubuntu/.hermes/profiles/bg/codex -maxdepth 1 -type f \
  -exec stat -c '%a %n' {} \;
```

Expected: login status succeeds; `auth.json` exists and is mode `0600` or stricter. Correct permissions immediately if needed, without displaying the file.

- [ ] **Step 4: Add the isolated Codex config**

Create `/home/ubuntu/.hermes/profiles/bg/codex/config.toml` with mode `0600` and this content:

```toml
model = "gpt-5.6-sol"
model_reasoning_effort = "high"

[projects."/home/ubuntu/.hermes/profiles/bg/workspace"]
trust_level = "trusted"
```

Do not copy `/home/ubuntu/.codex/config.toml` or `/home/ubuntu/.codex/auth.json`.

- [ ] **Step 5: Verify the selected Hermes model against the authenticated account**

```bash
/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes -p bg model
```

Expected: `gpt-5.6-sol` appears and is selected. If it is absent, select the current provider-recommended Codex model shown by this live picker, update only BG's overlay and Codex config to that exact model, reapply local state, and commit the safe overlay change.

- [ ] **Step 6: Smoke-test the default Hermes runtime**

```bash
cd /home/ubuntu/.hermes/profiles/bg/workspace
/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes -p bg \
  -z "Reply with exactly: BG Hermes runtime OK"
```

Expected: `BG Hermes runtime OK` with no authentication or model error.

---

## Task 5: Connect Minyong's Personal GitHub Account and Codex GitHub Plugin

**Files:**

- Create private GitHub CLI state: `/home/ubuntu/.hermes/profiles/bg/gh/`
- Create isolated Git config: `/home/ubuntu/.hermes/profiles/bg/home/.gitconfig`
- Modify BG Codex plugin config under `/home/ubuntu/.hermes/profiles/bg/codex/`

- [ ] **Step 1: Create isolated GitHub and Git homes**

```bash
mkdir -p /home/ubuntu/.hermes/profiles/bg/gh
mkdir -p /home/ubuntu/.hermes/profiles/bg/home
chmod 700 /home/ubuntu/.hermes/profiles/bg/gh
chmod 700 /home/ubuntu/.hermes/profiles/bg/home
```

- [ ] **Step 2: Authenticate GitHub CLI with the personal account**

```bash
GH_CONFIG_DIR=/home/ubuntu/.hermes/profiles/bg/gh \
GIT_CONFIG_GLOBAL=/home/ubuntu/.hermes/profiles/bg/home/.gitconfig \
  gh auth login --hostname github.com --git-protocol https --web
```

**USER CHECKPOINT:** Minyong completes GitHub's browser/device authorization while signed in to the intended personal GitHub account.

Verify identity without printing a token:

```bash
GH_CONFIG_DIR=/home/ubuntu/.hermes/profiles/bg/gh gh auth status --hostname github.com
GH_CONFIG_DIR=/home/ubuntu/.hermes/profiles/bg/gh \
  gh api user --jq '{login: .login, name: .name, email: .email}'
```

**USER CHECKPOINT:** Minyong confirms the displayed GitHub login is the correct personal account. Stop immediately if it is not.

- [ ] **Step 3: Configure only BG's Git identity and HTTPS credential helper**

Run in an interactive shell; the API supplies name/email where public, and the shell asks for a commit email only when GitHub keeps it private:

```bash
export GH_CONFIG_DIR=/home/ubuntu/.hermes/profiles/bg/gh
export GIT_CONFIG_GLOBAL=/home/ubuntu/.hermes/profiles/bg/home/.gitconfig

bg_github_login=$(gh api user --jq '.login')
bg_git_name=$(gh api user --jq '.name // .login')
bg_git_email=$(gh api user --jq '.email // empty')
if [ -z "$bg_git_email" ]; then
  read -r -p "Git commit email for BG: " bg_git_email
fi

git config --global user.name "$bg_git_name"
git config --global user.email "$bg_git_email"
gh auth setup-git --hostname github.com
git config --global url.https://github.com/.insteadOf git@github.com:
git config --global --add url.https://github.com/.insteadOf ssh://git@github.com/
chmod 600 /home/ubuntu/.hermes/profiles/bg/gh/hosts.yml
chmod 600 /home/ubuntu/.hermes/profiles/bg/home/.gitconfig
unset bg_github_login bg_git_name bg_git_email
```

Verify:

```bash
GH_CONFIG_DIR=/home/ubuntu/.hermes/profiles/bg/gh \
GIT_CONFIG_GLOBAL=/home/ubuntu/.hermes/profiles/bg/home/.gitconfig \
  git config --global --list --show-origin
```

Expected: only the confirmed name/email, GitHub CLI credential helper, and HTTPS rewrite rules appear from BG's isolated `.gitconfig`; no token is printed.

- [ ] **Step 4: Install the GitHub plugin only in BG's Codex home**

First confirm the authenticated Codex account has synced the official curated marketplace:

```bash
CODEX_HOME=/home/ubuntu/.hermes/profiles/bg/codex \
  /home/ubuntu/.nvm/versions/node/v24.15.0/bin/codex plugin marketplace list
```

Expected: `openai-curated` appears. If it does not, stop and inspect the current official Codex marketplace source; do not copy another user's Codex home or guess a marketplace URL.

Install and verify:

```bash
CODEX_HOME=/home/ubuntu/.hermes/profiles/bg/codex \
  /home/ubuntu/.nvm/versions/node/v24.15.0/bin/codex \
  plugin add github@openai-curated --json
CODEX_HOME=/home/ubuntu/.hermes/profiles/bg/codex \
  /home/ubuntu/.nvm/versions/node/v24.15.0/bin/codex plugin list --json
```

Expected: `github@openai-curated` is installed and enabled in BG's config only.

- [ ] **Step 5: Authorize and verify the Codex GitHub connector**

Start an interactive BG-scoped Codex session from the BG workspace and ask it to list the authenticated GitHub login without changing anything:

```bash
cd /home/ubuntu/.hermes/profiles/bg/workspace
CODEX_HOME=/home/ubuntu/.hermes/profiles/bg/codex \
GH_CONFIG_DIR=/home/ubuntu/.hermes/profiles/bg/gh \
GIT_CONFIG_GLOBAL=/home/ubuntu/.hermes/profiles/bg/home/.gitconfig \
  /home/ubuntu/.nvm/versions/node/v24.15.0/bin/codex
```

**USER CHECKPOINT:** If the Codex GitHub plugin requests a separate browser authorization, Minyong connects the same personal GitHub account and confirms the displayed login. Do not authorize repository writes during this read-only test unless the connector's normal scope requires them and Minyong approves.

---

## Task 6: Generate, Review, and Install the Dedicated Brad Gilbert Slack App

**Files:**

- Generate live manifest: `/home/ubuntu/.hermes/profiles/bg/slack-manifest.json`
- Modify private secrets: `/home/ubuntu/.hermes/profiles/bg/.env`

- [ ] **Step 1: Generate the manifest with the permanent display name**

```bash
/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes -p bg slack manifest \
  --agent-view \
  --name "Brad Gilbert" \
  --description "BG, Minyong's personal AI agent" \
  --write /home/ubuntu/.hermes/profiles/bg/slack-manifest.json
chmod 600 /home/ubuntu/.hermes/profiles/bg/slack-manifest.json
```

- [ ] **Step 2: Test the irreversible identity fields and required Slack mode**

```bash
jq -e '
  .display_information.name == "Brad Gilbert" and
  .features.bot_user.display_name == "Brad Gilbert" and
  (.features.agent_view != null) and
  .settings.socket_mode_enabled == true and
  (.settings.event_subscriptions.bot_events | index("message.im") != null)
' /home/ubuntu/.hermes/profiles/bg/slack-manifest.json
```

Expected: `jq` exits 0. Also inspect the complete manifest for generated slash commands, scopes, `app_home_opened`, and Agent View before uploading it.

- [ ] **Step 3: Create the Slack app from the reviewed manifest**

**USER CHECKPOINT:** Minyong opens Slack's app creation page, chooses **From an app manifest**, selects the intended workspace, pastes the exact generated JSON, and verifies the preview still says `Brad Gilbert` in both app and bot identity fields before clicking Create. Agent View cannot be reversed after creation, so do not proceed if Slack shows a different messaging surface.

Then:

1. Enable Socket Mode if Slack did not preserve it.
2. Create an app-level token with `connections:write`; retain the `xapp-` value privately.
3. Install the app to the workspace; retain the bot `xoxb-` token privately.
4. Copy Minyong's Slack Member ID from the Slack profile.

- [ ] **Step 4: Enter Slack secrets directly on EC2 without shell history or chat**

Open the exact file in an interactive SSH editor:

```bash
umask 077
nano /home/ubuntu/.hermes/profiles/bg/.env
```

Add exactly these keys with the private values obtained from Slack:

```dotenv
SLACK_BOT_TOKEN=
SLACK_APP_TOKEN=
SLACK_ALLOWED_USERS=
```

The saved file contains actual values after each `=`. Do not add `SLACK_ALLOW_ALL_USERS` or `GATEWAY_ALLOW_ALL_USERS`.

Verify key names and permissions without printing values:

```bash
chmod 600 /home/ubuntu/.hermes/profiles/bg/.env
awk -F= '/^(SLACK_BOT_TOKEN|SLACK_APP_TOKEN|SLACK_ALLOWED_USERS)=/ {print $1}' \
  /home/ubuntu/.hermes/profiles/bg/.env | sort
if grep -Eq '^(SLACK_ALLOW_ALL_USERS|GATEWAY_ALLOW_ALL_USERS)=' \
  /home/ubuntu/.hermes/profiles/bg/.env; then
  exit 1
fi
stat -c '%a %n' /home/ubuntu/.hermes/profiles/bg/.env
```

Expected: only the three expected names print; permission is `600`; allow-all grep is false.

---

## Task 7: Install the Dedicated BG Gateway Service with Account Isolation

**Files:**

- Create live service: `/home/ubuntu/.config/systemd/user/hermes-gateway-bg.service`
- Create live drop-in: `/home/ubuntu/.config/systemd/user/hermes-gateway-bg.service.d/10-profile-isolation.conf`

- [ ] **Step 1: Install but do not start the generated profile service**

```bash
/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes -p bg gateway install \
  --force --no-start-now --start-on-login
systemctl --user cat hermes-gateway-bg.service
```

Expected: `ExecStart` contains `--profile bg`, `WorkingDirectory` and `HERMES_HOME` point to `/home/ubuntu/.hermes/profiles/bg`, and the PATH contains the current Hermes venv and Codex binary directory. Stop if the generated unit references another profile.

- [ ] **Step 2: Add the profile-scoped Codex, GitHub, and Git environment**

Create `/home/ubuntu/.config/systemd/user/hermes-gateway-bg.service.d/10-profile-isolation.conf` with:

```ini
[Service]
Environment="CODEX_HOME=/home/ubuntu/.hermes/profiles/bg/codex"
Environment="GH_CONFIG_DIR=/home/ubuntu/.hermes/profiles/bg/gh"
Environment="GIT_CONFIG_GLOBAL=/home/ubuntu/.hermes/profiles/bg/home/.gitconfig"
```

Do not override `HOME` and do not place these non-secret path settings in `.env`.

- [ ] **Step 3: Reload, start, and inspect the service**

```bash
systemctl --user daemon-reload
systemctl --user enable --now hermes-gateway-bg.service
systemctl --user is-enabled hermes-gateway-bg.service
systemctl --user is-active hermes-gateway-bg.service
systemctl --user show hermes-gateway-bg.service \
  -p ExecStart -p WorkingDirectory -p Environment
journalctl --user -u hermes-gateway-bg.service --since '5 minutes ago' \
  --no-pager | tail -200
```

Expected: enabled and active; only BG paths appear; logs contain no `invalid_auth`, token lock, duplicate gateway, profile mismatch, or configuration error.

- [ ] **Step 4: Verify deep gateway status**

```bash
/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes -p bg gateway status --deep --full
```

Expected: the BG gateway and Slack Socket Mode connection are healthy.

---

## Task 8: End-to-End Verification and Safe Handoff

**Files:**

- Read only: all BG safe and live paths
- Update only if required by a verified model/config correction: `ignored/local/profiles/bg/config.overlay.yaml`

- [ ] **Step 1: Run profile health checks**

```bash
/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes -p bg status
/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes -p bg doctor
/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes -p bg security audit
```

Expected: no BG-specific blocking error. Record dependency advisories separately; do not change shared dependencies in this plan.

- [ ] **Step 2: Verify account isolation and file permissions**

```bash
test "$(readlink -f /home/ubuntu/.hermes/profiles/bg/SOUL.md)" = \
  "/home/ubuntu/.hermes/hermes-agent/ignored/local/profiles/bg/SOUL.md"
CODEX_HOME=/home/ubuntu/.hermes/profiles/bg/codex \
  /home/ubuntu/.nvm/versions/node/v24.15.0/bin/codex login status
GH_CONFIG_DIR=/home/ubuntu/.hermes/profiles/bg/gh gh auth status --hostname github.com
find /home/ubuntu/.hermes/profiles/bg \
  \( -name '.env' -o -name 'auth.json' -o -name 'hosts.yml' -o -name '.gitconfig' \) \
  -type f -exec stat -c '%a %n' {} \;
```

Expected: each account reports authenticated from its BG-scoped directory; credential-bearing files are `0600` or stricter.

- [ ] **Step 3: Re-run the local-state audit against the baseline**

```bash
cd /home/ubuntu/.hermes/hermes-agent
ignored/local/scripts/audit-local-state.py 2>&1 | tee /tmp/bg-postflight-local-state-audit.txt
diff -u /tmp/bg-preflight-local-state-audit.txt /tmp/bg-postflight-local-state-audit.txt
```

Expected: no new BG-related finding. Timestamp or ordering noise may be normalized for comparison, but any added path must be inspected.

- [ ] **Step 4: Run Slack acceptance tests as Minyong**

In a DM with **Brad Gilbert**, run these tests in order:

1. `/help` — slash commands and Agent View respond.
2. `/model` — provider is `openai-codex` and the verified model is selected.
3. Ask `제 이름과 기본 응답 언어를 기억해 주세요.` then ask what was remembered — Hermes memory works.
4. `/codex-runtime codex_app_server` — switch succeeds and reports plugin migration.
5. Ask a read-only coding question and a read-only GitHub account/repository question — BG uses the isolated Codex/GitHub identities.
6. `/codex-runtime auto` — return to the full Hermes tool surface.
7. Ask for the current skill inventory summary — BG can access the complete enabled inventory.

Expected: all seven pass without another profile's name, account, memory, or workspace appearing.

- [ ] **Step 5: Test that an unauthorized Slack user is blocked**

Ask one explicitly approved colleague or test account not present in `SLACK_ALLOWED_USERS` to DM the bot once.

Expected: access is denied or pairing is required; the agent does not answer the request. Do not add the tester to the allowlist.

- [ ] **Step 6: Perform the final Git and secret review**

```bash
cd /home/ubuntu/.hermes/hermes-agent
git status --short
git diff --check
git diff --cached --check
git ls-files | grep -E '(^|/)(\.env|auth\.json|hosts\.yml|slack-manifest\.json)$' && exit 1 || true
git diff HEAD | grep -E '(xox[baprs]-|gh[pousr]_[A-Za-z0-9_]+|sk-[A-Za-z0-9])' && exit 1 || true
```

Expected: no uncommitted safe asset remains, no runtime/auth file is tracked, and no token pattern is present.

- [ ] **Step 7: Push only after all acceptance tests pass**

```bash
cd /home/ubuntu/.hermes/hermes-agent
git log --oneline --decorate -8
git push team-michael main
```

Expected: safe design, plan, and BG canonical-asset commits are pushed. No live profile state or secret leaves EC2.

- [ ] **Step 8: Hand off operational commands**

Provide Minyong these exact commands:

```bash
systemctl --user status hermes-gateway-bg.service
journalctl --user -u hermes-gateway-bg.service -f
systemctl --user restart hermes-gateway-bg.service
/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes -p bg gateway status --deep
```

Also record that Hermes upgrade, existing audit cleanup, and activation of any additional service-backed skill credentials are separate follow-up changes.

## Rollback

If any step fails after the service is installed:

```bash
systemctl --user disable --now hermes-gateway-bg.service
```

Leave the BG live profile and Slack app intact for diagnosis. Do not delete either without Minyong's explicit approval. Existing Hermes profile services remain untouched throughout rollback.
