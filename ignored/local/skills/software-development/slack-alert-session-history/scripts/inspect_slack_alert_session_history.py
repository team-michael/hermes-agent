#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

HERMES_HOME = Path.home() / '.hermes'
SESSIONS_DIR = HERMES_HOME / 'sessions'
SESSIONS_INDEX = SESSIONS_DIR / 'sessions.json'
DEFAULT_KEYWORDS = [
    'alert', '알람', 'cloudwatch', 'amazon q', 'cpu', 'writer', 'reader',
    'query', '쿼리', 'latency', 'error', 'rds', 'database', 'db', '원인', 'burst'
]


def normalize_ws(text: str) -> str:
    return re.sub(r'\s+', ' ', text or '').strip()


def message_text(message: Dict[str, Any]) -> str:
    content = message.get('content')
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            ptype = part.get('type')
            if ptype == 'text':
                parts.append(part.get('text', ''))
            elif ptype == 'tool_result':
                parts.append('[tool_result]')
            elif ptype == 'image_url':
                parts.append('[image_url]')
        return '\n'.join(parts)
    return ''


def load_sessions_index() -> Dict[str, Any]:
    return json.loads(SESSIONS_INDEX.read_text())


def session_file(session_id: str) -> Path:
    return SESSIONS_DIR / f'session_{session_id}.json'


def derive_thread_ts(session_key: str, origin: Dict[str, Any]) -> str:
    return str(origin.get('thread_ts') or origin.get('thread_id') or session_key.rsplit(':', 1)[-1])


def find_sessions(index: Dict[str, Any], channel_id: Optional[str], thread_ts: Optional[str], session_id: Optional[str]) -> List[Dict[str, Any]]:
    rows = []
    for session_key, meta in index.items():
        if not isinstance(meta, dict):
            continue
        origin = meta.get('origin') or {}
        if session_id and meta.get('session_id') != session_id:
            continue
        if channel_id and origin.get('chat_id') != channel_id:
            continue
        resolved_thread_ts = derive_thread_ts(session_key, origin)
        if thread_ts and resolved_thread_ts != thread_ts:
            continue
        rows.append({
            'session_key': session_key,
            'session_id': meta.get('session_id'),
            'created_at': meta.get('created_at'),
            'updated_at': meta.get('updated_at'),
            'channel_id': origin.get('chat_id'),
            'thread_ts': resolved_thread_ts,
            'user_id': origin.get('user_id'),
        })
    rows.sort(key=lambda row: (row.get('created_at') or '', row.get('session_id') or ''))
    return rows


def extract_thread_context(text: str) -> Optional[str]:
    m = re.search(
        r'\[Thread context — prior messages in this thread \(not yet in conversation history\):\]\s*(.*?)\s*\[End of thread context\]',
        text,
        flags=re.S,
    )
    return m.group(1).strip() if m else None


def strip_leading_speaker_prefix(text: str) -> str:
    return re.sub(r'^\[[^\]]+\]\s*', '', text).strip()


def extract_first_user_ask(text: str) -> str:
    stripped = strip_leading_speaker_prefix(text)
    stripped = re.sub(
        r'^\[Thread context — prior messages in this thread \(not yet in conversation history\):\]\s*.*?\s*\[End of thread context\]\s*',
        '',
        stripped,
        flags=re.S,
    )
    return stripped.strip()


def build_default_keywords(thread_context: Optional[str], query: Optional[str]) -> List[str]:
    if query:
        return [query.lower()]
    keywords = list(DEFAULT_KEYWORDS)
    if thread_context:
        ctx = thread_context.lower()
        for extra in ['cpuutilization', 'freeablememory', 'databaseconnections', 'deadlocks', 'replicalag']:
            if extra in ctx and extra not in keywords:
                keywords.append(extra)
    return keywords


def find_assistant_snippets(messages: List[Dict[str, Any]], keywords: List[str]) -> List[Dict[str, Any]]:
    matches = []
    for idx, message in enumerate(messages):
        if message.get('role') != 'assistant':
            continue
        text = normalize_ws(message_text(message))
        if not text:
            continue
        low = text.lower()
        if keywords and any(keyword in low for keyword in keywords):
            matches.append({'idx': idx, 'text': text})
    if matches:
        return matches[:5]

    fallback = []
    for idx, message in enumerate(messages):
        if message.get('role') != 'assistant':
            continue
        text = normalize_ws(message_text(message))
        if len(text) >= 60:
            fallback.append({'idx': idx, 'text': text})
    return fallback[:3]


def find_query_matches(messages: List[Dict[str, Any]], query: Optional[str]) -> List[Dict[str, Any]]:
    if not query:
        return []
    low_query = query.lower()
    out = []
    for idx, message in enumerate(messages):
        text = normalize_ws(message_text(message))
        if not text:
            continue
        if low_query in text.lower():
            out.append({'idx': idx, 'role': message.get('role'), 'text': text})
    return out[:12]


def first_user_message(messages: List[Dict[str, Any]]) -> str:
    for message in messages:
        if message.get('role') == 'user':
            return message_text(message)
    return ''


def print_session_list(rows: List[Dict[str, Any]]) -> None:
    print(f'# Matching sessions: {len(rows)}')
    for row in rows:
        sid = row.get('session_id') or '<missing>'
        sf = session_file(sid)
        snippet = ''
        if sf.exists():
            try:
                data = json.loads(sf.read_text())
                snippet = normalize_ws(extract_first_user_ask(first_user_message(data.get('messages', []))))[:140]
            except Exception:
                snippet = ''
        print(f"- {row.get('created_at')} | session_id={sid} | thread_ts={row.get('thread_ts')} | user_id={row.get('user_id')} | {snippet}")


def inspect_session(row: Dict[str, Any], query: Optional[str]) -> None:
    sid = row['session_id']
    path = session_file(sid)
    if not path.exists():
        raise SystemExit(f'Session file not found: {path}')

    data = json.loads(path.read_text())
    messages = data.get('messages', [])
    first_user = first_user_message(messages)
    thread_context = extract_thread_context(first_user)
    first_ask = extract_first_user_ask(first_user)
    keywords = build_default_keywords(thread_context, query)
    findings = find_assistant_snippets(messages, keywords)
    query_matches = find_query_matches(messages, query)

    print('# Session metadata')
    print(f"session_id: {sid}")
    print(f"channel_id: {row.get('channel_id')}")
    print(f"thread_ts: {row.get('thread_ts')}")
    print(f"created_at: {row.get('created_at')}")
    print(f"updated_at: {row.get('updated_at')}")
    print(f"message_count: {data.get('message_count', len(messages))}")
    print()

    print('# Injected thread context')
    if thread_context:
        print(thread_context)
    else:
        print('(No injected [Thread context ...] block found in the first user message)')
    print()

    print('# First user ask')
    print(first_ask or '(empty)')
    print()

    print('# Assistant findings')
    if findings:
        for item in findings:
            print(f"[assistant#{item['idx']}] {item['text'][:1600]}")
            print()
    else:
        print('(No assistant findings matched)')
        print()

    if query:
        print(f'# Query matches: {query}')
        if query_matches:
            for item in query_matches:
                print(f"[{item['role']}#{item['idx']}] {item['text'][:1000]}")
                print()
        else:
            print('(No transcript snippets matched the query)')
            print()


def main() -> None:
    parser = argparse.ArgumentParser(description='Inspect Hermes Slack session history for alert details and thread context.')
    parser.add_argument('--channel-id', help='Slack channel ID, e.g. C04KT7EH5RQ')
    parser.add_argument('--thread-ts', help='Slack thread ts/root ts, e.g. 1776764135.019959')
    parser.add_argument('--session-id', help='Hermes session_id, e.g. 20260421_095149_7e990f80')
    parser.add_argument('--query', help='Optional keyword to filter findings')
    args = parser.parse_args()

    if not args.session_id and not args.channel_id:
        parser.error('Provide --session-id or --channel-id')

    index = load_sessions_index()
    rows = find_sessions(index, args.channel_id, args.thread_ts, args.session_id)
    if not rows:
        raise SystemExit('No matching sessions found.')

    if len(rows) > 1 and not args.session_id and not args.thread_ts:
        print_session_list(rows)
        print('\nTip: rerun with --thread-ts or --session-id to inspect one session in detail.')
        return

    row = rows[0]
    inspect_session(row, args.query)


if __name__ == '__main__':
    main()
