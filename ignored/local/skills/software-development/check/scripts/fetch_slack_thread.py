#!/usr/bin/env python3
"""Fetch a Slack thread/message from a permalink and emit compact JSON.

Usage:
    python fetch_slack_thread.py '<permalink>'

Expects SLACK_BOT_TOKEN in the environment.
"""
import json
import os
import re
import sys
import urllib.request
from urllib.parse import urlencode


def parse_permalink(url: str) -> tuple[str | None, str | None]:
    # https://<workspace>.slack.com/archives/<channel>/p<ts> or .../p<ts>?thread_ts=<ts>&cid=<channel>
    m = re.search(r"/archives/([A-Z0-9]+)/p(\d+)\b", url)
    if not m:
        return None, None
    channel, ts_str = m.group(1), m.group(2)
    # Slack timestamps include a decimal point before the last 6 digits
    ts = f"{ts_str[:-6]}.{ts_str[-6:]}"
    return channel, ts


def slack_api(method: str, params: dict[str, str]) -> dict:
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN not set")
    query = urlencode(params)
    url = f"https://slack.com/api/{method}?{query}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: fetch_slack_thread.py '<slack permalink>'", file=sys.stderr)
        return 2

    url = sys.argv[1]
    channel, ts = parse_permalink(url)
    if not channel or not ts:
        print(json.dumps({"ok": False, "error": "failed_to_parse_permalink"}))
        return 1

    query = urllib.parse.urlparse(url).query
    qs = urllib.parse.parse_qs(query)
    thread_ts = qs.get("thread_ts", [ts])[0]

    result = slack_api("conversations.replies", {"channel": channel, "ts": thread_ts, "limit": "20"})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
