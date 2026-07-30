#!/usr/bin/env bash
set -euo pipefail

hermes_root="/home/ubuntu/.hermes"
repo="$hermes_root/hermes-agent"
sync_script="$repo/ignored/local/scripts/sync-local-state.py"
cache_dir="$hermes_root/cache"
env_file="$hermes_root/profiles/andrej/.env"

fail() {
  printf 'Hermes local-state backup failed: %s\n' "$*" >&2
  exit 1
}

[ -x "$sync_script" ] || [ -f "$sync_script" ] || fail "missing sync script: $sync_script"
mkdir -p "$cache_dir"

askpass=$(mktemp "$cache_dir/git-askpass.XXXXXX")
sync_log=$(mktemp "$cache_dir/hermes-local-state-sync.XXXXXX")
cleanup() {
  unlink "$askpass" 2>/dev/null || true
  unlink "$sync_log" 2>/dev/null || true
}
trap cleanup EXIT

cat >"$askpass" <<'ASKPASS'
#!/usr/bin/env bash
set -euo pipefail
prompt="${1:-}"
case "$prompt" in
  *Username*)
    printf '%s\n' 'x-access-token'
    ;;
  *Password*)
    env_file="/home/ubuntu/.hermes/profiles/andrej/.env"
    [ -f "$env_file" ] || exit 1
    while IFS= read -r line || [ -n "$line" ]; do
      case "$line" in
        GITHUB_TOKEN=*|GH_TOKEN=*)
          token="${line#*=}"
          token="${token%$'\r'}"
          token="${token%\"}"
          token="${token#\"}"
          token="${token%\'}"
          token="${token#\'}"
          printf '%s\n' "$token"
          exit 0
          ;;
      esac
    done <"$env_file"
    exit 1
    ;;
  *)
    printf '\n'
    ;;
esac
ASKPASS
chmod 700 "$askpass"

export GIT_ASKPASS="$askpass"
export GIT_TERMINAL_PROMPT=0
export HERMES_ROOT="$hermes_root"

set +e
python3 "$sync_script" \
  --repo "$repo" \
  --remote team-michael \
  --branch main \
  --lock-timeout 0 >"$sync_log" 2>&1
rc=$?
set -e

if [ "$rc" -ne 0 ]; then
  printf 'Hermes local-state backup failed (exit %s):\n' "$rc" >&2
  while IFS= read -r line || [ -n "$line" ]; do
    printf '%s\n' "$line" >&2
  done <"$sync_log"
  exit "$rc"
fi
