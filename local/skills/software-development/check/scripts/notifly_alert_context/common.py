import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:
    import boto3  # type: ignore
except Exception:
    boto3 = None

from .config import *


GLOBAL_HERMES_ENV = Path.home() / '.hermes' / '.env'

def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)

def hermes_home() -> Path:
    return Path(os.environ.get('HERMES_HOME') or (Path.home() / '.hermes'))

def load_env_files() -> None:
    """Load profile env first, then fill gaps from the global Hermes env."""
    seen = set()
    for path in (hermes_home() / '.env', GLOBAL_HERMES_ENV):
        resolved = str(path.expanduser())
        if resolved in seen:
            continue
        seen.add(resolved)
        load_env_file(path.expanduser())

def read_text_arg(args: argparse.Namespace) -> str:
    if args.text:
        return args.text
    if args.text_file:
        return Path(args.text_file).read_text()
    if args.stdin:
        return sys.stdin.read()
    raise SystemExit('Provide --text, --text-file, or --stdin')

def unique(seq: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for item in seq:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
