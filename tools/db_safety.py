"""Safety boundaries for database work launched by the local terminal.

PostgreSQL session limits are injected through libpq's PGOPTIONS, so they
apply to psql, psycopg, and other libpq clients without application changes.
Static checks reject the two query shapes that caused the production incident:
materializing an unbounded cursor with fetchall() and dynamically UNIONing all
tenant tables.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path


DEFAULT_STATEMENT_TIMEOUT_MS = 120_000
DEFAULT_MAX_RESULT_ROWS = 100_000
DEFAULT_MAX_RESULT_BYTES = 128 * 1024 * 1024
_MAX_INSPECTED_FILE_BYTES = 2 * 1024 * 1024

_DB_MARKERS = re.compile(
    r"(?:psycopg|asyncpg|sqlalchemy|\bpsql\b|postgres(?:ql)?|pg8000|"
    r"information_schema|database_url|pghost|postgres_host|"
    r"scorecards_|campaign_statistics_|user_journey_statistics_)",
    re.IGNORECASE,
)
_FETCHALL = re.compile(r"\.\s*fetchall\s*\(", re.IGNORECASE)
_FETCHMANY = re.compile(r"\.\s*fetchmany\s*\(", re.IGNORECASE)
_UNION = re.compile(r"\bunion(?:\s+all)?\b", re.IGNORECASE)
_TENANT_ENUMERATION = re.compile(
    r"(?:information_schema\s*\.\s*tables|"
    r"for\s+\w+\s+in\s+(?:tables|tenant|projects?)|"
    r"(?:tables|tenant_tables|project_tables)\s*=)",
    re.IGNORECASE,
)
_DYNAMIC_UNION = re.compile(
    r"(?:['\"]\s+union(?:\s+all)?\s+['\"]\s*\.\s*join|"
    r"\.\s*join\s*\([^)]*union(?:\s+all)?|"
    r"union(?:\s+all)?[^\n]{0,160}(?:format\s*\(|f['\"]))",
    re.IGNORECASE,
)
_FILE_TOKEN = re.compile(r"(?P<path>(?:~|/|\.?\.?/)?[^\s'\";|&<>]+\.(?:py|sql|sh))")
_PSQL_SELECT = re.compile(r"\bpsql\b[\s\S]*\bselect\b", re.IGNORECASE)
_SQL_LIMIT = re.compile(r"\blimit\s+(?P<count>\d+)\b", re.IGNORECASE)
_SINGLE_VALUE_AGGREGATE = re.compile(
    r"\bselect\s+(?:(?:count|sum|avg|min|max)\s*\(|exists\s*\()",
    re.IGNORECASE,
)


def _bounded_int(value: object, default: int, *, minimum: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


def apply_postgres_safety_env(env: dict[str, str]) -> None:
    """Inject read-only PostgreSQL defaults and query/result budgets."""
    timeout_ms = _bounded_int(
        env.get("TERMINAL_DB_STATEMENT_TIMEOUT_MS"),
        DEFAULT_STATEMENT_TIMEOUT_MS,
        minimum=1_000,
    )
    max_rows = _bounded_int(
        env.get("TERMINAL_DB_MAX_RESULT_ROWS"),
        DEFAULT_MAX_RESULT_ROWS,
        minimum=1,
    )
    max_bytes = _bounded_int(
        env.get("TERMINAL_DB_MAX_RESULT_BYTES"),
        DEFAULT_MAX_RESULT_BYTES,
        minimum=1_024,
    )

    # Options appended last take precedence over an earlier duplicate in
    # PGOPTIONS.  They are session defaults, so deliberate write workflows can
    # still be performed outside an agent gateway by an operator.
    safety_options = (
        f"-c statement_timeout={timeout_ms} "
        "-c lock_timeout=10000 "
        f"-c idle_in_transaction_session_timeout={timeout_ms} "
        "-c default_transaction_read_only=on"
    )
    previous = str(env.get("_HERMES_DB_PGOPTIONS_APPLIED", "")).strip()
    existing = str(env.get("PGOPTIONS", "")).strip()
    if previous:
        existing = existing.replace(previous, "").strip()
    env["PGOPTIONS"] = f"{existing} {safety_options}".strip()
    env["_HERMES_DB_PGOPTIONS_APPLIED"] = safety_options
    env["HERMES_DB_MAX_RESULT_ROWS"] = str(max_rows)
    env["HERMES_DB_MAX_RESULT_BYTES"] = str(max_bytes)


def _candidate_files(command: str, cwd: str | None) -> list[Path]:
    """Resolve script/query files directly referenced by a shell command."""
    candidates: list[Path] = []
    seen: set[Path] = set()
    base = Path(cwd or os.getcwd()).expanduser()

    # shlex catches quoted paths; the regex catches simple shell fragments that
    # shlex cannot parse because the command is intentionally incomplete.
    tokens: list[str]
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = []
    raw_paths = [token for token in tokens if token.endswith((".py", ".sql", ".sh"))]
    raw_paths.extend(match.group("path") for match in _FILE_TOKEN.finditer(command))

    for raw in raw_paths:
        path = Path(os.path.expandvars(raw)).expanduser()
        if not path.is_absolute():
            path = base / path
        try:
            path = path.resolve()
        except OSError:
            continue
        if path in seen or not path.is_file():
            continue
        try:
            if path.stat().st_size > _MAX_INSPECTED_FILE_BYTES:
                continue
        except OSError:
            continue
        seen.add(path)
        candidates.append(path)
    return candidates


def validate_local_db_command(command: str, cwd: str | None = None) -> str | None:
    """Return a hard-block reason for unsafe production-style DB access."""
    inspected = [command]
    for path in _candidate_files(command, cwd):
        try:
            inspected.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    text = "\n".join(inspected)

    if not _DB_MARKERS.search(text):
        return None
    if _FETCHALL.search(text):
        return (
            "Blocked database query: fetchall() may materialize an unbounded "
            "production result. Use a server-side cursor with fetchmany(), stop "
            "at HERMES_DB_MAX_RESULT_ROWS or HERMES_DB_MAX_RESULT_BYTES, and "
            "aggregate/filter in SQL before fetching."
        )
    if _FETCHMANY.search(text) and not all(
        marker in text
        for marker in ("HERMES_DB_MAX_RESULT_ROWS", "HERMES_DB_MAX_RESULT_BYTES")
    ):
        return (
            "Blocked database query: fetchmany() loops must enforce both "
            "HERMES_DB_MAX_RESULT_ROWS and HERMES_DB_MAX_RESULT_BYTES while "
            "streaming results."
        )
    if _UNION.search(text) and (
        _DYNAMIC_UNION.search(text) or _TENANT_ENUMERATION.search(text)
    ):
        return (
            "Blocked database query: dynamically UNIONing tenant tables can scan "
            "the full production fleet. Scope explicit tenants and time ranges, "
            "query bounded batches, or use an analytics replica/warehouse."
        )
    if _PSQL_SELECT.search(text) and not _SINGLE_VALUE_AGGREGATE.search(text):
        limits = [int(match.group("count")) for match in _SQL_LIMIT.finditer(text)]
        max_rows = _bounded_int(
            os.getenv("TERMINAL_DB_MAX_RESULT_ROWS"),
            DEFAULT_MAX_RESULT_ROWS,
            minimum=1,
        )
        if not limits or max(limits) > max_rows:
            return (
                "Blocked database query: direct psql SELECT output must include "
                "an explicit numeric LIMIT no greater than "
                f"HERMES_DB_MAX_RESULT_ROWS ({max_rows}). Use SQL aggregation "
                "for larger result sets."
            )
    return None
