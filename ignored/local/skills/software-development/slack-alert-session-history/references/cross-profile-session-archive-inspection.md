# Cross-profile Hermes session archive inspection

Use when a user asks how a previous persona/session (for example `andrej`) reached an answer, or when `session_search` / the helper script does not find a Slack thread that is visible in another profile's archived sessions.

## Key lesson from 2026-05 Notifly NBT/ISMS thread

A Slack thread can be handled by a different Hermes profile, so the active profile's `session_search` may return no results even though the transcript exists under another profile:

- Active CSM profile sessions: `/home/ubuntu/.hermes/profiles/csm/sessions`
- Andrej profile sessions: `/home/ubuntu/.hermes/profiles/andrej/sessions`

When investigating "how did Andrej derive this answer?", search the target profile's archive directly.

## Safe workflow

1. Identify likely profile and keywords.
   - Profile examples: `andrej`, `csm`.
   - Keywords from the Slack thread: customer name, issue text, Linear ID, code terms, workflow phrase.
2. Search target profile session files under `~/.hermes/profiles/<profile>/sessions`.
3. Prefer metadata + snippets first; do not dump full session files into the answer.
4. Parse session JSON and extract:
   - session id, start/update time
   - user asks in chronological order
   - final assistant answers
   - tool outputs that provided evidence
5. Cross-check with repository/source files when the answer contains technical claims.
6. Summarize reasoning as evidence chain, not hidden chain-of-thought.

## Useful deterministic extractor pattern

Use a small script under `~/.hermes` or `execute_code` to avoid manually scrolling huge JSON files:

```python
import json, os, re, glob
base = '/home/ubuntu/.hermes/profiles/andrej/sessions'
keywords = ['엔비티', '염수민', '캠페인 업로드 파일', '감사로그', 'csv-segment', 'CLIX-183']
for path in sorted(glob.glob(base + '/session_*.json')):
    txt = open(path, encoding='utf-8').read()
    hits = [k for k in keywords if k in txt]
    if not hits:
        continue
    data = json.loads(txt)
    print(os.path.basename(path), data.get('session_start'), data.get('last_updated'), hits)
    for i, m in enumerate(data.get('messages', [])):
        content = m.get('content')
        if isinstance(content, list):
            text = ' '.join(c.get('text', '') if isinstance(c, dict) else str(c) for c in content)
        else:
            text = str(content)
        if any(k in text for k in hits):
            print(i, m.get('role'), re.sub(r'\s+', ' ', text)[:1000])
```

## What to report back

A good answer includes:

- Which sessions were relevant.
- What each session contributed.
- Which files/configs/logs were checked.
- Which claims are strong and which are caveated.
- Any customer-facing phrasing risk discovered.

Do **not** expose secrets, credentials, raw customer PII, or long raw session dumps. Use minimal snippets and summarize.
