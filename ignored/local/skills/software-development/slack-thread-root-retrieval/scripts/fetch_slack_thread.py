#!/usr/bin/env python3
"""Fetch a Slack thread with SLACK_BOT_TOKEN and write raw + summary JSON.

Usage:
  python scripts/fetch_slack_thread.py C1234567890 1712345678.123456

The script loads SLACK_BOT_TOKEN from the active environment, then from
/home/ubuntu/.hermes/profiles/andrej/.env if needed. It never prints the token.
Outputs are written under ~/.hermes/profiles/andrej/slack_api_cache/.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ENV_PATH = Path('/home/ubuntu/.hermes/profiles/andrej/.env')
OUT_DIR = Path('/home/ubuntu/.hermes/profiles/andrej/slack_api_cache')


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(errors='ignore').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def slack_api(method: str, params: dict) -> dict:
    token = os.environ.get('SLACK_BOT_TOKEN')
    if not token:
        raise SystemExit('SLACK_BOT_TOKEN not found in env or profile .env')
    url = f'https://slack.com/api/{method}?{urllib.parse.urlencode(params)}'
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))


def collect_text_parts(message: dict) -> str:
    parts = []
    if message.get('text'):
        parts.append(message['text'])
    for attachment in message.get('attachments') or []:
        for key in ('pretext', 'title', 'text', 'fallback'):
            if attachment.get(key):
                parts.append(str(attachment[key]))
        for field in attachment.get('fields') or []:
            title = field.get('title') or ''
            value = field.get('value') or ''
            if title or value:
                parts.append(f'{title}: {value}'.strip(': '))
    for block in message.get('blocks') or []:
        def walk(value):
            if isinstance(value, dict):
                if value.get('type') == 'text' and value.get('text'):
                    parts.append(value['text'])
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(block)
    seen = set()
    compact = []
    for part in parts:
        text = ' '.join(str(part).split())
        if text and text not in seen:
            seen.add(text)
            compact.append(text)
    return '\n'.join(compact)


def main() -> int:
    if len(sys.argv) != 3:
        print('usage: fetch_slack_thread.py CHANNEL THREAD_TS', file=sys.stderr)
        return 2
    channel, thread_ts = sys.argv[1], sys.argv[2]
    load_env(ENV_PATH)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    messages = []
    cursor = ''
    while True:
        params = {'channel': channel, 'ts': thread_ts, 'limit': 200, 'inclusive': 'true'}
        if cursor:
            params['cursor'] = cursor
        data = slack_api('conversations.replies', params)
        if not data.get('ok'):
            print(json.dumps({
                'ok': False,
                'error': data.get('error'),
                'needed': data.get('needed'),
                'provided': data.get('provided'),
            }, ensure_ascii=False, indent=2))
            return 1
        messages.extend(data.get('messages') or [])
        cursor = (data.get('response_metadata') or {}).get('next_cursor') or ''
        if not cursor:
            break
        time.sleep(0.2)

    stem = f'thread_{channel}_{thread_ts.replace(".", "_")}'
    raw_path = OUT_DIR / f'{stem}.json'
    summary_path = OUT_DIR / f'{stem}_summary.json'
    raw_path.write_text(json.dumps({
        'ok': True,
        'channel': channel,
        'thread_ts': thread_ts,
        'messages': messages,
    }, ensure_ascii=False, indent=2))

    summary = []
    for index, message in enumerate(messages):
        text = collect_text_parts(message)
        if len(text) > 2500:
            text = text[:2500] + ' …[truncated]'
        summary.append({
            'i': index,
            'ts': message.get('ts'),
            'user_or_bot': message.get('user') or message.get('bot_id') or message.get('username') or message.get('subtype') or 'unknown',
            'subtype': message.get('subtype'),
            'reply_count': message.get('reply_count'),
            'text': text,
        })
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({
        'ok': True,
        'message_count': len(messages),
        'raw_path': str(raw_path),
        'summary_path': str(summary_path),
        'summary': summary,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
