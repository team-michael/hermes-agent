# Channel Term-Frequency / Customer Wording Analysis

Use this when the user asks which wording customers use more often in a Slack channel, e.g. “전역 발송 제한 vs 피로도 중 어떤 표현이 더 많이 나오나?”

## Best source hierarchy

1. Prefer an existing curated per-channel export/dataset if present.
   - For Notifly CS, check paths like:
     - `~/.hermes/profiles/csm/datasets/*/manifest.json`
     - `raw/slack_threads_<CHANNEL_ID>_*.jsonl`
     - `raw/slack_history_<CHANNEL_ID>_*.jsonl`
   - The manifest often contains the exact covered range, thread count, and source paths.
2. If no curated dataset exists, use recovery exports:
   - `~/.hermes/profiles/*/recovery/slack_threads_*.jsonl`
   - `~/.hermes/recovery/*/slack_threads_*.json`
3. Use Hermes session archives only as a fallback, because they represent what Hermes saw, not canonical channel history.

## Counting rules

- Count at the **thread/root-question level** for customer wording questions, not assistant replies.
- Separately report:
  - exact phrase hits, e.g. `전역 발송 제한`
  - near-synonym hits, e.g. `글로벌 발송 제한`, `전체 발송 제한`
  - broader semantic hits, e.g. `야간 발송금지 시간`, `발송제한량`
- Keep “customer wording” separate from “internal answer text.” Assistant replies often contain system terms that customers did not say.
- Prefer unique thread counts over raw occurrence counts unless the user explicitly asks for occurrence frequency.

## Minimal analysis pattern

For JSONL thread exports, parse each line as one thread:

```python
import json, re
from pathlib import Path

thread_path = Path('~/.hermes/profiles/csm/datasets/.../raw/slack_threads_C06SYCB7WJW_last_1y.jsonl').expanduser()
patterns = {
    'global_exact': re.compile(r'전역\s*발송\s*제한|전역발송제한'),
    'global_synonym': re.compile(r'(?:전역|글로벌|전체)\s*발송\s*제한|global\s+(?:send(?:ing)?\s+)?limit', re.I),
    'global_broad': re.compile(r'(?:전역|글로벌|전체)\s*(?:발송|메시지|메세지)?\s*(?:제한|금지)|발송\s*금지\s*시간|발송\s*제한\s*(?:량|시간|설정|유저|목록|리스트)?', re.I),
    'fatigue': re.compile(r'피로도\s*(?:관리|조절|제한)?|fatigue|frequency\s*cap(?:ping)?', re.I),
}

def collect_text(obj):
    parts = []
    def rec(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == 'text' and isinstance(v, str):
                    parts.append(v)
                elif k in ('fallback', 'title') and isinstance(v, str):
                    parts.append(v)
                else:
                    rec(v)
        elif isinstance(x, list):
            for y in x:
                rec(y)
    rec(obj)
    out, seen = [], set()
    for p in parts:
        if p and p not in seen:
            out.append(p); seen.add(p)
    return '\n'.join(out)

threads = [json.loads(line) for line in thread_path.read_text().splitlines() if line.strip()]
for name, rx in patterns.items():
    hits = []
    for t in threads:
        root = (t.get('messages') or [{}])[0]
        text = collect_text(root)
        if rx.search(text):
            hits.append(t['root_ts'])
    print(name, len(set(hits)))
```

## Reporting shape

Give a compact answer:

- source/range/thread count
- table of exact/synonym/broad counts
- 2–4 representative snippets
- conclusion in product-language terms
- caveat: “local/export-visible Slack data,” not guaranteed full Slack workspace unless the export says so

Example conclusion style:

> 고객들은 ‘전역 발송 제한’이라는 정확한 표현은 거의 쓰지 않고, ‘피로도 관리/조절’ 쪽 표현을 더 자연스럽게 씁니다. ‘야간 발송금지 시간’ 같은 넓은 발송 제한 표현까지 포함하면 전역 계열도 나오지만, 고객 언어로는 피로도가 더 강합니다.
