from __future__ import annotations

import ast
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .common import hermes_home


OBSERVABILITY_LOG_GROUP = "/aws/ec2/notifly-agent/observability"
KST = timezone(timedelta(hours=9))
PROFILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def is_hermes_service_health_alarm(alarm: Any) -> bool:
    return bool(
        isinstance(alarm, dict)
        and alarm.get("_alarm_type") == "MetricAlarm"
        and str(alarm.get("MetricName") or "") == "HermesServiceHealthy"
    )


def host_hermes_root(home: Optional[Path] = None) -> Path:
    """Resolve the host-wide Hermes root from a default or named profile home."""
    current = (home or hermes_home()).resolve()
    if current.parent.name == "profiles":
        return current.parent.parent
    return current


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_utc(value: Any) -> Optional[str]:
    parsed = _parse_datetime(value)
    return parsed.isoformat() if parsed else None


def _format_kst(value: Any) -> Optional[str]:
    parsed = _parse_datetime(value)
    return parsed.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST") if parsed else None


def _alarm_cluster(history: Any) -> tuple[Optional[datetime], Optional[datetime]]:
    if not isinstance(history, dict):
        return None, None
    latest = history.get("latest_alarm_transition") or {}
    latest_time = _parse_datetime(latest.get("timestamp"))
    if latest_time is None:
        return None, None

    alarm_times = [latest_time]
    for item in history.get("sample_items") or []:
        if not isinstance(item, dict) or item.get("new_state") != "ALARM":
            continue
        item_time = _parse_datetime(item.get("timestamp"))
        if item_time and 0 <= (latest_time - item_time).total_seconds() <= 10 * 60 + 1:
            alarm_times.append(item_time)
    return min(alarm_times), max(alarm_times)


def _dimension_value(alarm: Dict[str, Any], name: str) -> Optional[str]:
    for dimension in alarm.get("Dimensions") or []:
        if isinstance(dimension, dict) and dimension.get("Name") == name:
            value = dimension.get("Value")
            return str(value) if value else None
    return None


def _json_message(message: Any) -> Optional[Dict[str, Any]]:
    text = str(message or "").strip()
    if not text:
        return None
    candidates = [text]
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _collect_pressure_events(
    session: Any,
    *,
    start: datetime,
    end: datetime,
    instance_id: Optional[str],
) -> Dict[str, Any]:
    if session is None:
        return {"status": "error", "error": "missing aws session", "events": []}
    logs = session.client("logs")
    events: List[Dict[str, Any]] = []
    next_token = None
    previous_token = None
    try:
        for _ in range(2):
            kwargs: Dict[str, Any] = {
                "logGroupName": OBSERVABILITY_LOG_GROUP,
                "startTime": int(start.timestamp() * 1000),
                "endTime": int(end.timestamp() * 1000),
                "filterPattern": '{ $.signal = "profile_pressure" }',
                "limit": 100,
            }
            if next_token:
                kwargs["nextToken"] = next_token
            response = logs.filter_log_events(**kwargs)
            for raw in response.get("events") or []:
                parsed = _json_message(raw.get("message"))
                if not parsed or parsed.get("signal") != "profile_pressure":
                    continue
                if instance_id and parsed.get("instance_id") != instance_id:
                    continue
                parsed["log_event_timestamp"] = _iso_utc(
                    float(raw.get("timestamp")) / 1000
                    if raw.get("timestamp") is not None
                    else None
                )
                events.append(parsed)
            next_token = response.get("nextToken")
            if not next_token or next_token == previous_token:
                break
            previous_token = next_token
    except Exception as error:
        return {"status": "error", "error": str(error), "events": []}

    events.sort(key=lambda event: float(event.get("timestamp") or 0))
    return {"status": "ok", "events": events}


def _event_facts(event: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "timestamp": _iso_utc(event.get("timestamp")),
        "timestamp_kst": _format_kst(event.get("timestamp")),
        "profile": event.get("profile"),
        "state": event.get("state"),
        "reasons": event.get("reasons") or [],
        "read_mib_s": event.get("read_mib_s"),
        "cpu_percent": event.get("cpu_percent"),
        "memory_percent": event.get("memory_percent"),
        "session_id_short": event.get("session_id_short"),
        "source": event.get("source"),
        "tool_name": event.get("tool_name"),
    }


def pair_pressure_events(events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    incidents: List[Dict[str, Any]] = []
    pending: Dict[str, List[Dict[str, Any]]] = {}
    for event in sorted(events, key=lambda item: float(item.get("timestamp") or 0)):
        profile = str(event.get("profile") or "unknown")
        state = str(event.get("state") or "")
        if state == "open":
            incident = {
                "profile": profile,
                "open": _event_facts(event),
                "recovered": None,
                "duration_seconds": None,
            }
            incidents.append(incident)
            pending.setdefault(profile, []).append(incident)
        elif state == "recovered" and pending.get(profile):
            incident = pending[profile].pop(0)
            incident["recovered"] = _event_facts(event)
            opened = _parse_datetime(incident["open"].get("timestamp"))
            recovered = _parse_datetime(incident["recovered"].get("timestamp"))
            if opened and recovered:
                incident["duration_seconds"] = round(
                    max(0.0, (recovered - opened).total_seconds()), 3
                )
    return incidents


def _safe_task_excerpt(value: Any, limit: int = 320) -> Optional[str]:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return None
    if "[New message]" in text:
        text = text.rsplit("[New message]", 1)[-1].strip()
    text = re.sub(r"https?://\S+", "<url>", text)
    text = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|password|authorization)\b\s*[:=]\s*\S+",
        r"\1=<redacted>",
        text,
    )
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _call_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def summarize_execute_code(arguments: Any) -> Optional[Dict[str, Any]]:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return None
    if not isinstance(arguments, dict) or not isinstance(arguments.get("code"), str):
        return None
    code = arguments["code"]
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {"code_char_count": len(code)}

    literal_sizes: Dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if not isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                literal_sizes[target.id] = len(value.elts)

    summaries = []
    for loop in [node for node in ast.walk(tree) if isinstance(node, ast.For)]:
        if not isinstance(loop.iter, ast.Name) or loop.iter.id not in literal_sizes:
            continue
        operations = sorted({
            name
            for child in ast.walk(loop)
            if isinstance(child, ast.Call)
            for name in [_call_name(child.func)]
            if name in {"web_search", "web_extract", "read_file", "terminal"}
        })
        if not operations:
            continue
        summaries.append({
            "operations": operations,
            "batch_item_count": literal_sizes[loop.iter.id],
            "execution_mode": "sequential_loop",
        })
    if summaries:
        return max(summaries, key=lambda item: item["batch_item_count"])
    return {"code_char_count": len(code)}


def _tool_intervals(
    connection: sqlite3.Connection,
    session_id: str,
) -> tuple[List[Dict[str, Any]], Optional[str]]:
    rows = connection.execute(
        """
        SELECT role, content, tool_call_id, tool_calls, tool_name, timestamp
        FROM messages
        WHERE session_id = ? AND active = 1
        ORDER BY id
        """,
        (session_id,),
    ).fetchall()
    completed: Dict[str, float] = {}
    task_excerpt = None
    for row in rows:
        if row["role"] == "user" and task_excerpt is None:
            task_excerpt = _safe_task_excerpt(row["content"])
        if row["role"] == "tool" and row["tool_call_id"]:
            completed[str(row["tool_call_id"])] = float(row["timestamp"])

    intervals: List[Dict[str, Any]] = []
    for row in rows:
        if row["role"] != "assistant" or not row["tool_calls"]:
            continue
        try:
            calls = json.loads(row["tool_calls"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(calls, list):
            continue
        for call in calls:
            if not isinstance(call, dict):
                continue
            function = call.get("function")
            if not isinstance(function, dict) or not function.get("name"):
                continue
            call_id = str(call.get("id") or call.get("call_id") or "")
            interval = {
                "tool_call_id": call_id or None,
                "tool_name": str(function["name"]),
                "started_at": float(row["timestamp"]),
                "ended_at": completed.get(call_id),
                "arguments": function.get("arguments"),
            }
            if interval["tool_name"] == "execute_code":
                interval["execution_summary"] = summarize_execute_code(
                    interval.get("arguments")
                )
            intervals.append(interval)
    return intervals, task_excerpt


def _profile_db_path(root: Path, profile: str) -> Optional[Path]:
    if not PROFILE_NAME_PATTERN.fullmatch(profile):
        return None
    if profile == "default":
        return root / "state.db"
    return root / "profiles" / profile / "state.db"


def _session_link(profile: str, session_id: Any) -> Optional[str]:
    return f"@session:{profile}/{session_id}" if session_id else None


def resolve_pressure_session(
    root: Path,
    event: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    profile = str(event.get("profile") or "")
    prefix = str(event.get("session_id_short") or "")
    event_time = float(event.get("timestamp") or 0)
    event_tool = str(event.get("tool_name") or "")
    db_path = _profile_db_path(root, profile)
    if not prefix or db_path is None or not db_path.is_file():
        return None

    connection = None
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.25)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        candidates = connection.execute(
            """
            SELECT id, source, parent_session_id, started_at, ended_at, title
            FROM sessions
            WHERE id >= ? AND id < ?
            ORDER BY started_at DESC
            LIMIT 50
            """,
            (prefix, prefix + "\uffff"),
        ).fetchall()
        scored = []
        for candidate in candidates:
            intervals, task_excerpt = _tool_intervals(connection, str(candidate["id"]))
            active = [
                interval
                for interval in intervals
                if interval["started_at"] <= event_time
                and (
                    interval["ended_at"] is None
                    or event_time <= float(interval["ended_at"])
                )
            ]
            active_exact = [
                interval for interval in active if interval["tool_name"] == event_tool
            ]
            matching = [
                interval
                for interval in intervals
                if interval["tool_name"] == event_tool
            ]
            session_active = bool(
                float(candidate["started_at"] or 0) <= event_time
                and (
                    candidate["ended_at"] is None
                    or event_time <= float(candidate["ended_at"])
                )
            )
            selected_interval = active_exact[0] if active_exact else None
            score = 0
            if active_exact:
                score += 100
            elif active:
                score += 50
            if session_active:
                score += 30
            if str(candidate["source"] or "") == str(event.get("source") or ""):
                score += 20
            if matching:
                score += 10
            scored.append((
                score,
                candidate,
                selected_interval,
                task_excerpt,
                bool(active_exact),
                session_active,
            ))
        if not scored:
            return None
        scored.sort(
            key=lambda item: (item[0], float(item[1]["started_at"] or 0)), reverse=True
        )
        score, selected, tool_interval, task_excerpt, active_exact, session_active = (
            scored[0]
        )
        if len(scored) > 1 and not active_exact and not session_active:
            return None

        parent = None
        if selected["parent_session_id"]:
            parent = connection.execute(
                """
                SELECT id, source, title, started_at, ended_at
                FROM sessions WHERE id = ?
                """,
                (selected["parent_session_id"],),
            ).fetchone()

        tool_facts = None
        if tool_interval:
            tool_facts = {
                "tool_name": tool_interval.get("tool_name"),
                "interval_match": True,
                "started_at": _iso_utc(tool_interval.get("started_at")),
                "started_at_kst": _format_kst(tool_interval.get("started_at")),
                "ended_at": _iso_utc(tool_interval.get("ended_at")),
                "ended_at_kst": _format_kst(tool_interval.get("ended_at")),
                "execution_summary": tool_interval.get("execution_summary"),
            }
        elif event_tool:
            tool_facts = {
                "tool_name": event_tool,
                "interval_match": False,
                "started_at": None,
                "started_at_kst": None,
                "ended_at": None,
                "ended_at_kst": None,
                "execution_summary": None,
            }
        return {
            "session_id": selected["id"],
            "session_link": _session_link(profile, selected["id"]),
            "source": selected["source"],
            "title": selected["title"],
            "started_at_kst": _format_kst(selected["started_at"]),
            "ended_at_kst": _format_kst(selected["ended_at"]),
            "parent_session_id": selected["parent_session_id"],
            "parent_session_link": _session_link(
                profile, selected["parent_session_id"]
            ),
            "parent_title": parent["title"] if parent else None,
            "task_excerpt": task_excerpt,
            "tool": tool_facts,
            "attribution_confidence": (
                "active_tool_interval_match"
                if active_exact
                else "unique_session_prefix"
                if len(scored) == 1
                else "session_interval_match"
                if session_active
                else "unresolved"
            ),
            "attribution_note": (
                "Session/tool context is correlated with profile-level cgroup IO; "
                "the bytes are not accounted per process."
            ),
        }
    except (OSError, sqlite3.Error):
        return None
    finally:
        if connection is not None:
            connection.close()


def _is_breaching(value: float, threshold: Any, operator: Any) -> bool:
    try:
        threshold_value = float(threshold)
    except (TypeError, ValueError):
        return False
    return {
        "LessThanThreshold": value < threshold_value,
        "LessThanOrEqualToThreshold": value <= threshold_value,
        "GreaterThanThreshold": value > threshold_value,
        "GreaterThanOrEqualToThreshold": value >= threshold_value,
    }.get(str(operator or ""), False)


def _collect_alarm_trigger(
    session: Any,
    alarm: Dict[str, Any],
    history: Dict[str, Any],
    *,
    start: datetime,
    end: datetime,
) -> Dict[str, Any]:
    latest = history.get("latest_alarm_transition") or {}
    state_reason = str(latest.get("state_reason") or "")
    stat = str(alarm.get("Statistic") or "Minimum")
    if session is None or stat.startswith("p"):
        return {
            "classification": "unavailable",
            "state_reason": state_reason,
            "treat_missing_data": alarm.get("TreatMissingData"),
        }
    try:
        response = session.client("cloudwatch").get_metric_statistics(
            Namespace=alarm["Namespace"],
            MetricName=alarm["MetricName"],
            Dimensions=alarm.get("Dimensions") or [],
            StartTime=start,
            EndTime=end,
            Period=int(alarm.get("Period") or 60),
            Statistics=[stat],
        )
        points = sorted(
            response.get("Datapoints") or [], key=lambda item: item["Timestamp"]
        )
        values = [
            float(point[stat])
            for point in points
            if isinstance(point.get(stat), (int, float))
        ]
        breaching = [
            value
            for value in values
            if _is_breaching(
                value, alarm.get("Threshold"), alarm.get("ComparisonOperator")
            )
        ]
        missing_breach = bool(
            str(alarm.get("TreatMissingData") or "").lower() == "breaching"
            and "missing" in state_reason.lower()
            and not breaching
        )
        return {
            "classification": "missing_data_breach"
            if missing_breach
            else "metric_breach_or_mixed",
            "state_reason": state_reason,
            "treat_missing_data": alarm.get("TreatMissingData"),
            "observed_datapoint_count": len(values),
            "observed_breaching_count": len(breaching),
            "observed_min": min(values) if values else None,
            "observed_max": max(values) if values else None,
        }
    except Exception as error:
        return {
            "classification": "unavailable",
            "state_reason": state_reason,
            "treat_missing_data": alarm.get("TreatMissingData"),
            "error": str(error),
        }


def _build_report_facts(
    incidents: Sequence[Dict[str, Any]],
    alarm_anchor: Optional[datetime],
) -> Optional[Dict[str, Any]]:
    if not incidents:
        return None
    anchor_timestamp = alarm_anchor.timestamp() if alarm_anchor else float("inf")
    before_alarm = [
        incident
        for incident in incidents
        if (
            _parse_datetime((incident.get("open") or {}).get("timestamp"))
            or datetime.min.replace(tzinfo=timezone.utc)
        ).timestamp()
        <= anchor_timestamp
    ]
    primary = max(
        before_alarm or list(incidents),
        key=lambda incident: (
            _parse_datetime((incident.get("open") or {}).get("timestamp"))
            or datetime.min.replace(tzinfo=timezone.utc)
        ).timestamp(),
    )
    session_context = primary.get("session_context") or {}
    parent_id = session_context.get("parent_session_id") or session_context.get(
        "session_id"
    )
    parent_link = session_context.get("parent_session_link") or session_context.get(
        "session_link"
    )
    related = []
    for incident in incidents:
        if incident is primary:
            continue
        context = incident.get("session_context") or {}
        incident_parent = context.get("parent_session_id") or context.get("session_id")
        if parent_id and incident_parent != parent_id:
            continue
        related.append({
            "opened_at_kst": (incident.get("open") or {}).get("timestamp_kst"),
            "read_mib_s": (incident.get("open") or {}).get("read_mib_s"),
            "recovered_at_kst": (incident.get("recovered") or {}).get("timestamp_kst"),
        })
    return {
        "parent_session": parent_link,
        "parent_title": session_context.get("parent_title")
        or session_context.get("title"),
        "active_session": session_context.get("session_link"),
        "active_session_source": session_context.get("source"),
        "task_excerpt": session_context.get("task_excerpt"),
        "tool": session_context.get("tool"),
        "pressure_opened_at_kst": (primary.get("open") or {}).get("timestamp_kst"),
        "read_mib_s": (primary.get("open") or {}).get("read_mib_s"),
        "recovered_at_kst": (primary.get("recovered") or {}).get("timestamp_kst"),
        "attribution_confidence": session_context.get("attribution_confidence"),
        "attribution_note": session_context.get("attribution_note"),
        "related_same_parent_incidents": related,
    }


def collect_hermes_observability_context(
    session: Any,
    alarm: Any,
    history: Any,
    *,
    root: Optional[Path] = None,
) -> Dict[str, Any]:
    if not is_hermes_service_health_alarm(alarm):
        return {"status": "not_applicable"}

    cluster_start, cluster_end = _alarm_cluster(history)
    now = datetime.now(timezone.utc)
    if cluster_start is None:
        cluster_start = now
    if cluster_end is None:
        cluster_end = cluster_start
    query_start = cluster_start - timedelta(minutes=20)
    query_end = min(now, cluster_end + timedelta(minutes=20))
    if query_end <= query_start:
        query_end = query_start + timedelta(minutes=1)

    instance_id = _dimension_value(alarm, "InstanceId")
    event_result = _collect_pressure_events(
        session,
        start=query_start,
        end=query_end,
        instance_id=instance_id,
    )
    incidents = pair_pressure_events(event_result.get("events") or [])
    resolved_root = (root or host_hermes_root()).resolve()
    for incident in incidents:
        open_event = incident.get("open") or {}
        raw_event = next(
            (
                event
                for event in event_result.get("events") or []
                if event.get("state") == "open"
                and _iso_utc(event.get("timestamp")) == open_event.get("timestamp")
                and event.get("profile") == incident.get("profile")
            ),
            None,
        )
        if raw_event:
            incident["session_context"] = resolve_pressure_session(
                resolved_root, raw_event
            )

    trigger = _collect_alarm_trigger(
        session,
        alarm,
        history if isinstance(history, dict) else {},
        start=query_start,
        end=query_end,
    )
    return {
        "status": "collected" if event_result.get("status") == "ok" else "error",
        "error": event_result.get("error"),
        "log_group": OBSERVABILITY_LOG_GROUP,
        "instance_id": instance_id,
        "alarm_cluster_start_kst": _format_kst(cluster_start),
        "alarm_cluster_end_kst": _format_kst(cluster_end),
        "alarm_trigger": trigger,
        "pressure_incidents": incidents,
        "report_facts": _build_report_facts(incidents, cluster_start),
    }
