#!/usr/bin/env python3
"""Parse, dedupe, rank, and CONCEPT-CLUSTER ad-hoc niche scrape results.

Pairs with templates/scrape_adhoc_niche.py. Edit IN/OUT paths and the
CONCEPTS keyword list per niche, then run with the clix-growth venv python.

Outputs:
  - top-30 by views (likes*12 proxy when SERP only leaked likes)
  - concept-cluster rollup: (count, sum_views, recent<=120d count, top video)
  - recent band (<=120d) split — separates "currently replicable" from
    "legacy megahit archetype" per the all-time vs qdr:w fork.
"""
import json, re
from datetime import datetime, timezone

IN = '/home/ubuntu/.hermes/profiles/tarantino/work/CHANGE_ME/scrape/google_results.json'
OUT = '/home/ubuntu/.hermes/profiles/tarantino/work/CHANGE_ME/scrape/ranked.json'

with open(IN) as f:
    raw = json.load(f)


def parse_views(text: str) -> int:
    # Korean SERP leak: 조회수 2350만회 이상 / 조회수 41.3만회
    m = re.search(r'조회수\s*([0-9.,]+)\s*(만|천|억)?\s*회', text)
    if m:
        num = float(m.group(1).replace(',', ''))
        mult = {'만': 10000, '천': 1000, '억': 100000000, None: 1}[m.group(2)]
        return int(num * mult)
    m = re.search(r'([\d.,]+)\s*([KkMmBb])\+?\s*views', text)
    if m:
        return int(float(m.group(1).replace(',', '')) *
                   {'k': 1e3, 'm': 1e6, 'b': 1e9}[m.group(2).lower()])
    m = re.search(r'([\d,]+)\s*views', text, re.I)
    if m:
        return int(m.group(1).replace(',', ''))
    return 0


def parse_likes(text: str) -> int:
    m = re.search(r'([\d.,]+)\s*([KkMmBb])?\+?\s*[Ll]ikes', text)
    if m:
        num = float(m.group(1).replace(',', ''))
        mult = {'k': 1e3, 'm': 1e6, 'b': 1e9}.get((m.group(2) or '').lower(), 1)
        return int(num * mult)
    return 0


def tiktok_id_to_date(video_id: str) -> datetime:
    return datetime.fromtimestamp(int(video_id) >> 32, tz=timezone.utc)


VIDEO_RE = re.compile(r'https?://(?:www\.)?tiktok\.com/@([^/]+)/video/(\d+)')

by_url = {}
for entry in raw:
    q = entry['query'].replace('site:tiktok.com/@ ', '').strip()
    for item in entry['items']:
        url = item['url']
        snip = item.get('snippet', '')
        if url not in by_url:
            m = VIDEO_RE.match(url)
            handle = m.group(1) if m else ''
            vid = m.group(2) if m else ''
            try:
                created = tiktok_id_to_date(vid)
                age_days = (datetime.now(timezone.utc) - created).days
            except Exception:
                created, age_days = None, 9999
            by_url[url] = {
                'url': url, 'handle': handle, 'video_id': vid,
                'created_utc': created.isoformat() if created else None,
                'age_days': age_days, 'queries': [], 'snippets': [],
                'views': 0, 'likes': 0,
            }
        by_url[url]['queries'].append(q)
        by_url[url]['snippets'].append(snip)
        v = parse_views(snip)
        if v > by_url[url]['views']:
            by_url[url]['views'] = v
        lk = parse_likes(snip)
        if lk > by_url[url]['likes']:
            by_url[url]['likes'] = lk

videos = list(by_url.values())

# Concept clusters via snippet keyword matching (lowercased).
# EDIT PER NICHE. Example set from the 2026-06-11 date-niche run:
CONCEPTS = [
    ('date_ideas_list', ['date ideas', 'ideas for', 'list of date']),
    ('cheap_budget', ['cheap date', 'budget', 'free date', '$', 'broke']),
    ('first_date', ['first date']),
    ('outfit_grwm', ['outfit', 'grwm', 'get ready']),
    ('dating_app', ['hinge', 'tinder', 'bumble', 'dating app']),
    ('storytime', ['storytime', 'story time', 'worst', 'red flag']),
    ('pov_skit', ['pov']),
    ('app_product', ['app ', ' app', 'widget']),
]


def classify(v):
    text = ' '.join(v['snippets']).lower() + ' ' + ' '.join(v['queries']).lower()
    return [name for name, kws in CONCEPTS if any(k in text for k in kws)]


for v in videos:
    v['concepts'] = classify(v)

with_signal = [v for v in videos if v['views'] > 0 or v['likes'] > 100]
print(f"Total raw unique videos: {len(videos)}")
print(f"With measurable signal: {len(with_signal)}")

with_signal.sort(key=lambda v: -max(v['views'], v['likes'] * 12))

print("\n=== TOP 30 (views, likes*12 proxy) ===")
for i, v in enumerate(with_signal[:30], 1):
    snip = v['snippets'][0][:110].replace('|', ' ')
    print(f"{i:>3} v={v['views']:>9} l={v['likes']:>8} age={v['age_days']:>5}d "
          f"@{v['handle'][:24]:<24} {','.join(v['concepts'])[:40]:<40} {snip}")

print("\n=== CONCEPT CLUSTER ROLLUP ===")
rollup = []
for name, _ in CONCEPTS:
    members = [v for v in with_signal if name in v['concepts']]
    if not members:
        continue
    sv = sum(v['views'] for v in members)
    top = max(members, key=lambda v: max(v['views'], v['likes'] * 12))
    recent = [v for v in members if v['age_days'] <= 120]
    rollup.append({'concept': name, 'count': len(members), 'sum_views': sv,
                   'recent_120d': len(recent), 'top_url': top['url'],
                   'top_views': top['views'], 'top_likes': top['likes'],
                   'top_snip': top['snippets'][0][:150]})
rollup.sort(key=lambda r: -r['sum_views'])
for r in rollup:
    print(f"{r['concept']:<20} n={r['count']:>3} sum_views={r['sum_views']:>11,} "
          f"recent<=120d={r['recent_120d']:>2} top={r['top_views']:>9} {r['top_url']}")

recent_band = [v for v in with_signal if v['age_days'] <= 120]
recent_band.sort(key=lambda v: -max(v['views'], v['likes'] * 12))
print(f"\n=== RECENT BAND <=120d ({len(recent_band)}) ===")
for v in recent_band[:20]:
    snip = v['snippets'][0][:100].replace('|', ' ')
    print(f"  v={v['views']:>9} l={v['likes']:>7} age={v['age_days']:>4}d "
          f"@{v['handle'][:22]:<22} {snip}")

json.dump({'total_raw': len(videos), 'with_signal': len(with_signal),
           'top30': with_signal[:30], 'rollup': rollup,
           'recent_band': recent_band[:25]},
          open(OUT, 'w'), indent=2, ensure_ascii=False)
print(f"\nSaved: {OUT}")
