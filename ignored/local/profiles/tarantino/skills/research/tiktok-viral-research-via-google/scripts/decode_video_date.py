#!/usr/bin/env python3
"""Decode TikTok video IDs to their creation timestamps.

TikTok video IDs are Snowflake-like: the top 32 bits encode Unix-seconds
since epoch of video creation. This is more reliable than SERP snippet
dates (often missing or rounded) or relative-text DOM elements ("3 weeks
ago") that themselves need parsing.

Usage:
    # single ID
    python decode_video_date.py 7505077544610221319

    # pipe a list of URLs or IDs, one per line
    cat urls.txt | python decode_video_date.py

    # enrich a JSON file in place (expects records with a 'url' key)
    python decode_video_date.py --enrich records.json

Verified 2026-05-07 on 52 diverse videos — every ID decoded to a
plausible creation date matching the TikTok page's own display.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone, date
from pathlib import Path

VIDEO_ID_RE = re.compile(r"/video/(\d+)")


def tiktok_id_to_datetime(video_id: str | int) -> datetime:
    """Return a UTC datetime for a TikTok video ID."""
    return datetime.fromtimestamp(int(video_id) >> 32, tz=timezone.utc)


def age_days(video_id: str | int, today: date | None = None) -> int:
    d = tiktok_id_to_datetime(video_id).date()
    t = today or date.today()
    return (t - d).days


def extract_id(s: str) -> str | None:
    m = VIDEO_ID_RE.search(s)
    if m:
        return m.group(1)
    s = s.strip()
    return s if s.isdigit() else None


def enrich_json(path: Path) -> None:
    records = json.loads(path.read_text())
    if not isinstance(records, list):
        raise SystemExit(f"Expected top-level list in {path}, got {type(records).__name__}")
    today = date.today()
    for r in records:
        url = r.get("url") or r.get("resolved_url") or ""
        vid = extract_id(url)
        if not vid:
            continue
        dt = tiktok_id_to_datetime(vid)
        r["created_at"] = dt.isoformat()
        r["age_days"] = (today - dt.date()).days
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2))
    print(f"Enriched {len(records)} records in {path}")


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "--enrich":
        if len(args) != 2:
            raise SystemExit("Usage: decode_video_date.py --enrich <records.json>")
        enrich_json(Path(args[1]))
        return

    if args:
        inputs = args
    else:
        inputs = [ln for ln in sys.stdin.read().splitlines() if ln.strip()]

    today = date.today()
    for raw in inputs:
        vid = extract_id(raw)
        if not vid:
            print(f"# skip (no video id): {raw}")
            continue
        dt = tiktok_id_to_datetime(vid)
        age = (today - dt.date()).days
        print(f"{vid}\t{dt.isoformat()}\tage={age}d")


if __name__ == "__main__":
    main()
