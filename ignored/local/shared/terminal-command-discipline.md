# Terminal Command Discipline

Use credentials already loaded in the active Hermes environment. Do not export, echo, print prefixes of, or embed `GITHUB_TOKEN`, `GH_TOKEN`, AWS keys, Cloudflare tokens, database passwords, or other secrets in command text, logs, Git remotes, URLs, or final answers.

Never create or delete files outside `~/.hermes`. This is a hard boundary. If a task requires temporary files, generated artifacts, scratch work, caches, logs, or cleanup, use only paths under `~/.hermes`. Do not write to or remove files from `/tmp`, the current project checkout, the home directory outside `~/.hermes`, or any other filesystem location unless the user explicitly names that exact path and asks for that exact mutation.

Avoid terminal command shapes that trigger avoidable approval prompts while preserving the same functionality:

- Do not pipe network or CLI output directly into interpreters: avoid `curl | python`, `gh | python`, `aws | python`, `git | python`, `sed | python`, `npm | python`, and the same forms with `python3`, `node`, `bash`, or `sh`.
- Prefer structured CLI filters: use `gh api ... --jq '...'`, `aws ... --query '...' --output json`, `jq`, `git --format`, or purpose-built helper scripts.
- For generic HTTP JSON, fetch to a temporary file first, then inspect with `jq` or a script file. Do not use `python -c` or heredoc scripts for routine JSON parsing.
- Prefer `hermes-github-api` for GitHub REST reads. It uses the existing `GITHUB_TOKEN`/`GH_TOKEN` environment value without exposing it and supports `--jq`.
- Use full `https://` URLs. Do not pass schemeless URLs to download or execution commands.
- Keep real approval prompts for genuinely risky operations such as destructive file deletion, `git reset --hard`, force push, database writes/truncation, service restarts, or commands that mutate infrastructure.

Safe examples:

```bash
gh api 'repos/team-michael/notifly-event/pulls?head=team-michael:branch&state=all' --jq '[.[] | {n:.number,state,title,url:.html_url,merged:.merged_at}]'
hermes-github-api 'repos/team-michael/notifly-event/pulls?head=team-michael:branch&state=all' --jq '[.[] | {n:.number,state,title,url:.html_url,merged:.merged_at}]'
tmp=$(mktemp); curl -fsS -o "$tmp" 'https://example.com/data.json'; jq '{id,name}' "$tmp"; rm -f "$tmp"
aws cloudwatch describe-alarms --alarm-names "$alarm" --query 'MetricAlarms[0].{Name:AlarmName,State:StateValue}' --output json
```
