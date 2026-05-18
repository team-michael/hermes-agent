#!/usr/bin/env python3
"""Parse google_results.json -> dedupe -> tag with semantic clusters -> rank.

Used as stage 2 of the Clix pilot format-research pipeline (after
scrape_google_loop.py). Outputs ranked.json with top_by_views + multi_query
slices ready for DOM verification.

Edit:
  - IN / OUT paths per run
  - CLUSTERS dict: match the semantic-family clusters your query list used

Usage:
    python3 parse_rank_clusters.py
"""
import json, re
from datetime import datetime, timezone

IN = '/home/ubuntu/.hermes/profiles/tarantino/work/<app>/scrape/google_results.json'
OUT = '/home/ubuntu/.hermes/profiles/tarantino/work/<app>/scrape/ranked.json'

# Edit per run — group your queries into named semantic clusters so
# `videos[].clusters` counts how many distinct angles each URL matched.
# Examples for a Zaispace-style social-app research run:
CLUSTERS = {
    'friendship_pain': ['"making friends in college"', '"lonely in college"',
                        '"hard to make friends"', '"college friend group"'],
    'storytime': ['"how I made friends"', '"met my best friend"'],
    'ai_social_cat': ['"AI companion app"', '"Character AI app"',
                      '"AI friend app"', '"Replika app"'],
    'anxiety_wedge': ['"social anxiety app"', '"introvert college"', '"texting anxiety"'],
}


def parse_views(text: str) -> int:
    """Korean SERP leak: 조회수 2350만회 이상 / 조회수 41.3만회"""
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
        k = (m.group(2) or '').lower()
        mult = {'k': 1e3, 'm': 1e6, 'b': 1e9}.get(k, 1) if k else 1
        return int(num * mult)
    return 0


def tiktok_id_to_date(video_id: str) -> datetime:
    return datetime.fromtimestamp(int(video_id) >> 32, tz=timezone.utc)


VIDEO_RE = re.compile(r'https?://(?:www\.)?tiktok\.com/@([^/]+)/video/(\d+)')


def main():
    with open(IN) as f:
        raw = json.load(f)

    by_url = {}
    for entry in raw:
        q = entry['query']
        q_short = q.replace('site:tiktok.com/@ ', '').strip()
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
                    'age_days': age_days,
                    'queries': [], 'snippets': [],
                    'views': 0, 'likes': 0,
                }
            by_url[url]['queries'].append(q_short)
            by_url[url]['snippets'].append(snip)
            v = parse_views(snip)
            if v > by_url[url]['views']:
                by_url[url]['views'] = v
            lk = parse_likes(snip)
            if lk > by_url[url]['likes']:
                by_url[url]['likes'] = lk

    def classify(qs):
        clusters = set()
        for cluster, patterns in CLUSTERS.items():
            for q in qs:
                if any(p in q for p in patterns):
                    clusters.add(cluster)
                    break
        return list(clusters)

    videos = list(by_url.values())
    for v in videos:
        v['clusters'] = classify(v['queries'])
        v['cluster_count'] = len(v['clusters'])
        v['query_count'] = len(v['queries'])

    with_signal = [v for v in videos if v['views'] > 0 or v['likes'] > 100]
    print(f"Total raw unique: {len(videos)}  |  with signal: {len(with_signal)}")

    with_signal.sort(key=lambda v: (-v['views'], -v['query_count'], -v['likes']))

    multi = [v for v in with_signal if v['query_count'] >= 2]
    multi.sort(key=lambda v: (-v['query_count'], -v['views']))

    out = {
        'total_raw': len(videos),
        'with_signal': len(with_signal),
        'top25_by_views': with_signal[:25],
        'multi_query': multi[:20],
    }
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"Saved: {OUT}")

    print(f"\n{'rank':>4} {'views':>9} {'likes':>8} {'age':>5} {'q':>3} {'cls':<22} {'handle':<28}")
    for i, v in enumerate(with_signal[:15], 1):
        cls = ','.join(v['clusters'])[:20]
        print(f"{i:>4} {v['views']:>9} {v['likes']:>8} {v['age_days']:>5} {v['query_count']:>3} {cls:<22} @{v['handle'][:26]}")


if __name__ == "__main__":
    main()
