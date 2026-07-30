from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


SCRIPTS_ROOT = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from notifly_alert_context.assessment import compact_output  # noqa: E402
from notifly_alert_context.cli import resolve_alert_input  # noqa: E402


EXACT_ALARM_NAME = "/aws/ecs/notifly-services-prod/web-console/sentry alert"


def _write_session_message(home: Path, *, session_key: str, content: str) -> None:
    db = sqlite3.connect(home / "state.db")
    db.executescript(
        """
        CREATE TABLE sessions (id TEXT PRIMARY KEY, session_key TEXT);
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            role TEXT,
            content TEXT,
            active INTEGER
        );
        """
    )
    db.execute(
        "INSERT INTO sessions(id, session_key) VALUES (?, ?)",
        ("session-1", session_key),
    )
    db.execute(
        "INSERT INTO messages(session_id, role, content, active) VALUES (?, ?, ?, 1)",
        ("session-1", "user", content),
    )
    db.commit()
    db.close()


def test_resolve_alert_input_corrects_shortened_alarm_from_current_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_key = "agent:main:slack:group:workspace:channel:thread"
    original = (
        "[IMPORTANT: check skill]\n\n"
        "[Slack subscription context]\n"
        "channel_id: C04KT7EH5RQ\n"
        "message_ts: 1785375068.207329\n\n"
        f"📎 🚨 CloudWatch Alarm | {EXACT_ALARM_NAME} | ap-northeast-2 | Acc"
    )
    _write_session_message(tmp_path, session_key=session_key, content=original)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SESSION_KEY", session_key)

    text, alarm_name, integrity = resolve_alert_input(
        "sentry alert",
        "sentry alert",
    )

    assert text.startswith("[Slack subscription context]")
    assert alarm_name == EXACT_ALARM_NAME
    assert integrity == {
        "source": "hermes_session",
        "corrected": True,
        "supplied_alarm_name": "sentry alert",
        "resolved_alarm_name": EXACT_ALARM_NAME,
    }


def test_compact_output_keeps_input_correction_evidence() -> None:
    integrity = {
        "source": "hermes_session",
        "corrected": True,
        "supplied_alarm_name": "sentry alert",
        "resolved_alarm_name": EXACT_ALARM_NAME,
    }

    result = compact_output(
        {
            "input_integrity": integrity,
            "helper_assessment": {
                "can_answer_root_cause": False,
                "next_action": "run_only_listed_followups_then_finalize",
                "missing_required_context": [],
                "required_followups": [],
            },
        }
    )

    assert result["input_integrity"] == integrity
