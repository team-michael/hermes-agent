#!/usr/bin/env bash
set -euo pipefail

repo="/home/ubuntu/.hermes/hermes-agent"
sync_script="$repo/ignored/local/scripts/sync-local-state.py"
cache_dir="/home/ubuntu/.hermes/cache"
env_file="/home/ubuntu/.hermes/profiles/andrej/.env"

fail() {
  printf 'Hermes local-state backup failed: %s\n' "$*" >&2
  exit 1
}

[ -x "$sync_script" ] || [ -f "$sync_script" ] || fail "missing sync script: $sync_script"
mkdir -p "$cache_dir"

askpass=$(mktemp "$cache_dir/git-askpass.XXXXXX")
cleanup() {
  unlink "$askpass" 2>/dev/null || true
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

exec python3 "$sync_script" \
  --repo "$repo" \
  --remote team-michael \
  --branch main \
  --lock-timeout 0
