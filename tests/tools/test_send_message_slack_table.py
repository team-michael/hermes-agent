"""Tests for the profile-gated Slack Block Kit `table` block path in send_message.

The feature is opt-in via the `SLACK_TABLE_ENABLED_PROFILES` allow-list. Tests
exercise:
  - schema gating (parameter visible only on tarantino)
  - validator (min/max shapes, type/shape errors, instructive messages)
  - block builder (raw_text cells, column_settings passthrough, header row prepended)
  - rasterizer (plain-text grid for session mirror)
  - runtime gate (programmatic slack_table is dropped on non-allow-listed profile)
"""
import importlib
import json
import os
import sys

import pytest


@pytest.fixture
def fresh_module(monkeypatch):
    """Reload tools.send_message_tool with a controlled HERMES_PROFILE.

    The schema is built at import time, so each profile flavor needs its own
    fresh module. We yield a callable so each test can pick its profile.
    """
    sys.path.insert(0, "/home/ubuntu/.hermes/hermes-agent")

    def _load(profile: str | None):
        if profile is None:
            monkeypatch.delenv("HERMES_PROFILE", raising=False)
            monkeypatch.delenv("HERMES_PROFILE_NAME", raising=False)
        else:
            monkeypatch.setenv("HERMES_PROFILE", profile)
        if "tools.send_message_tool" in sys.modules:
            return importlib.reload(sys.modules["tools.send_message_tool"])
        return importlib.import_module("tools.send_message_tool")

    return _load


# ---------------------------------------------------------------------------
# Schema gating
# ---------------------------------------------------------------------------

def test_schema_includes_slack_table_for_tarantino(fresh_module):
    m = fresh_module("tarantino")
    props = m.SEND_MESSAGE_SCHEMA["parameters"]["properties"]
    assert "slack_table" in props
    table_schema = props["slack_table"]
    assert table_schema["type"] == "object"
    assert "headers" in table_schema["required"]
    assert "rows" in table_schema["required"]


@pytest.mark.parametrize("profile", ["andrej", "boris", "csm", "hashimoto", "sdr", None])
def test_schema_omits_slack_table_for_other_profiles(fresh_module, profile):
    m = fresh_module(profile)
    props = m.SEND_MESSAGE_SCHEMA["parameters"]["properties"]
    assert "slack_table" not in props


def test_is_slack_table_enabled_predicate(fresh_module):
    m_t = fresh_module("tarantino")
    assert m_t._is_slack_table_enabled_for_current_profile() is True

    m_b = fresh_module("boris")
    assert m_b._is_slack_table_enabled_for_current_profile() is False


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

@pytest.fixture
def m(fresh_module):
    return fresh_module("tarantino")


def test_validator_accepts_minimum_3x3(m):
    ok, err = m._validate_slack_table({
        "headers": ["a", "b", "c"],
        "rows": [["1", "2", "3"], ["4", "5", "6"]],
    })
    assert ok, err
    assert err == ""


def test_validator_rejects_2_columns_with_bullet_alternative(m):
    ok, err = m._validate_slack_table({
        "headers": ["k", "v"],
        "rows": [["1", "a"], ["2", "b"]],
    })
    assert not ok
    assert "3 columns" in err
    assert "bullet list" in err
    # Instructive: shows the alternative inline
    assert "**Key" in err


def test_validator_rejects_too_few_rows(m):
    ok, err = m._validate_slack_table({
        "headers": ["a", "b", "c"],
        "rows": [["1", "2", "3"]],  # only 1 body row
    })
    assert not ok
    assert "2 data rows" in err
    assert "bullet" in err


def test_validator_rejects_too_many_columns(m):
    ok, err = m._validate_slack_table({
        "headers": ["c"] * 21,
        "rows": [["x"] * 21, ["y"] * 21],
    })
    assert not ok
    assert "20" in err


def test_validator_rejects_too_many_rows(m):
    ok, err = m._validate_slack_table({
        "headers": ["a", "b", "c"],
        "rows": [["x", "y", "z"]] * 100,  # +1 header = 101 total
    })
    assert not ok
    assert "100" in err


def test_validator_rejects_row_length_mismatch(m):
    ok, err = m._validate_slack_table({
        "headers": ["a", "b", "c"],
        "rows": [["1", "2", "3"], ["4", "5"]],
    })
    assert not ok
    assert "rows[1]" in err
    assert "2 cells" in err


def test_validator_rejects_non_string_cells(m):
    ok, err = m._validate_slack_table({
        "headers": ["a", "b", "c"],
        "rows": [["1", "2", "3"], ["4", 5, "6"]],
    })
    assert not ok
    assert "rows[1][1]" in err


def test_validator_rejects_invalid_align(m):
    ok, err = m._validate_slack_table({
        "headers": ["a", "b", "c"],
        "rows": [["1", "2", "3"], ["4", "5", "6"]],
        "column_settings": [None, {"align": "middle"}, None],
    })
    assert not ok
    assert "align" in err
    assert "left" in err and "center" in err and "right" in err


def test_validator_accepts_null_column_settings_entries(m):
    ok, err = m._validate_slack_table({
        "headers": ["a", "b", "c"],
        "rows": [["1", "2", "3"], ["4", "5", "6"]],
        "column_settings": [None, None, {"align": "right"}],
    })
    assert ok, err


def test_validator_rejects_bad_top_level_type(m):
    ok, err = m._validate_slack_table("not a dict")  # type: ignore
    assert not ok
    assert "object" in err


# ---------------------------------------------------------------------------
# Block builder
# ---------------------------------------------------------------------------

def test_build_block_prepends_header_row_as_raw_text(m):
    table = {
        "headers": ["A", "B", "C"],
        "rows": [["1", "2", "3"], ["4", "5", "6"]],
    }
    block = m._build_slack_table_block(table)
    assert block["type"] == "table"
    assert len(block["rows"]) == 3  # header + 2 body
    assert block["rows"][0] == [
        {"type": "raw_text", "text": "A"},
        {"type": "raw_text", "text": "B"},
        {"type": "raw_text", "text": "C"},
    ]
    assert block["rows"][2][2] == {"type": "raw_text", "text": "6"}
    assert "column_settings" not in block


def test_build_block_passes_through_column_settings_with_null_default(m):
    table = {
        "headers": ["A", "B", "C"],
        "rows": [["1", "2", "3"], ["4", "5", "6"]],
        "column_settings": [{"is_wrapped": True}, None, {"align": "right"}],
    }
    block = m._build_slack_table_block(table)
    cs = block["column_settings"]
    assert cs[0] == {"is_wrapped": True}
    assert cs[1] == {}  # null → default {}
    assert cs[2] == {"align": "right"}


def test_build_block_serializes_to_clean_json(m):
    """Smoke test: the block payload must round-trip JSON without surprises."""
    table = {
        "headers": ["기능", "장면", "ICP"],
        "rows": [
            ["Zai", "이상적 자아", "Bitmoji"],
            ["Hangout", "황당 모험", "storytime"],
        ],
    }
    block = m._build_slack_table_block(table)
    serialized = json.dumps(block, ensure_ascii=False)
    assert "\"type\": \"table\"" in serialized
    assert "Zai" in serialized
    assert "황당 모험" in serialized


# ---------------------------------------------------------------------------
# Rasterizer (mirror)
# ---------------------------------------------------------------------------

def test_rasterize_aligns_columns(m):
    out = m._rasterize_slack_table_for_mirror({
        "headers": ["F", "Scene", "Angle"],
        "rows": [
            ["Zai", "identity", "play"],
            ["Hangout", "adventure", "share"],
        ],
    })
    lines = out.split("\n")
    assert len(lines) == 4  # header + separator + 2 rows
    # Separator is a dashed line aligned to widest cell per column
    assert "---" in lines[1]
    # Every body line uses " | " separator
    assert lines[2].count("|") == 2
    # Widths align: column 1 width = max("F","Zai","Hangout") = 7
    assert "Hangout" in lines[3]
    assert "F      " in lines[0]  # padded header


def test_rasterize_handles_korean_unicode(m):
    out = m._rasterize_slack_table_for_mirror({
        "headers": ["기능", "장면", "각도"],
        "rows": [["Zai", "몰입", "Identity"], ["AI", "모험", "Fake"]],
    })
    # Korean codepoints survive
    assert "기능" in out
    assert "몰입" in out
    assert "Identity" in out


# ---------------------------------------------------------------------------
# Runtime gate inside _handle_send (programmatic invocation)
# ---------------------------------------------------------------------------

def test_runtime_gate_drops_slack_table_on_disabled_profile(fresh_module, monkeypatch):
    """A caller on boris that programmatically passes slack_table should be
    silently downgraded to the text path — not fail with a schema error and
    not actually post a Block Kit table.
    """
    m_b = fresh_module("boris")

    # Patch the underlying senders so we can detect which path was taken.
    captured = {"text_called": False, "blocks_called": False}

    async def _fake_send_to_platform(*a, **kw):
        captured["text_called"] = True
        return {"success": True, "platform": "slack", "chat_id": a[2], "message_id": "ts1"}

    async def _fake_send_slack_with_blocks(*a, **kw):
        captured["blocks_called"] = True
        return {"success": True, "mode": "blocks"}

    monkeypatch.setattr(m_b, "_send_to_platform", _fake_send_to_platform)
    monkeypatch.setattr(m_b, "_send_slack_with_blocks", _fake_send_slack_with_blocks)

    # Stub the gateway config + duplicate-skip + mirror so _handle_send runs
    # to completion without touching the network.
    class _StubPConfig:
        enabled = True
        token = "xoxb-test"
        extra = {}

    class _StubGatewayConfig:
        platforms = {}
        def get_home_channel(self, p):
            return None

    from gateway.config import Platform as _Platform
    stub = _StubGatewayConfig()
    stub.platforms = {_Platform.SLACK: _StubPConfig()}
    monkeypatch.setattr("gateway.config.load_gateway_config", lambda: stub)
    monkeypatch.setattr(m_b, "_maybe_skip_cron_duplicate_send", lambda *a, **kw: None)

    result_str = m_b._handle_send({
        "target": "slack:C0123456789",
        "message": "fallback summary",
        "slack_table": {
            "headers": ["a", "b", "c"],
            "rows": [["1", "2", "3"], ["4", "5", "6"]],
        },
    })
    result = json.loads(result_str)
    assert result.get("success") is True
    # Critical: blocks path NOT taken on a non-allow-listed profile
    assert captured["blocks_called"] is False
    assert captured["text_called"] is True


def test_runtime_gate_uses_blocks_path_on_enabled_profile(fresh_module, monkeypatch):
    m_t = fresh_module("tarantino")
    captured = {"text_called": False, "blocks_called": False, "blocks_arg": None}

    async def _fake_send_to_platform(*a, **kw):
        captured["text_called"] = True
        return {"success": True}

    async def _fake_send_slack_with_blocks(token, chat_id, message, blocks, thread_id=None):
        captured["blocks_called"] = True
        captured["blocks_arg"] = blocks
        return {"success": True, "mode": "blocks"}

    monkeypatch.setattr(m_t, "_send_to_platform", _fake_send_to_platform)
    monkeypatch.setattr(m_t, "_send_slack_with_blocks", _fake_send_slack_with_blocks)

    class _StubPConfig:
        enabled = True
        token = "xoxb-test"
        extra = {}

    class _StubGatewayConfig:
        platforms = {}
        def get_home_channel(self, p):
            return None

    from gateway.config import Platform as _Platform
    stub = _StubGatewayConfig()
    stub.platforms = {_Platform.SLACK: _StubPConfig()}
    monkeypatch.setattr("gateway.config.load_gateway_config", lambda: stub)
    monkeypatch.setattr(m_t, "_maybe_skip_cron_duplicate_send", lambda *a, **kw: None)
    # Suppress mirror side-effects
    monkeypatch.setattr("gateway.mirror.mirror_to_session", lambda *a, **kw: False)

    result_str = m_t._handle_send({
        "target": "slack:C0123456789",
        "message": "fallback summary",
        "slack_table": {
            "headers": ["a", "b", "c"],
            "rows": [["1", "2", "3"], ["4", "5", "6"]],
        },
    })
    result = json.loads(result_str)
    assert result.get("success") is True
    assert result.get("mode") == "blocks"
    assert captured["blocks_called"] is True
    assert captured["text_called"] is False
    # First argument is a list with one table block
    assert isinstance(captured["blocks_arg"], list)
    assert captured["blocks_arg"][0]["type"] == "table"


def test_runtime_gate_returns_validator_error_on_bad_table(fresh_module, monkeypatch):
    m_t = fresh_module("tarantino")

    class _StubPConfig:
        enabled = True
        token = "xoxb-test"
        extra = {}

    class _StubGatewayConfig:
        platforms = {}
        def get_home_channel(self, p):
            return None

    from gateway.config import Platform as _Platform
    stub = _StubGatewayConfig()
    stub.platforms = {_Platform.SLACK: _StubPConfig()}
    monkeypatch.setattr("gateway.config.load_gateway_config", lambda: stub)
    monkeypatch.setattr(m_t, "_maybe_skip_cron_duplicate_send", lambda *a, **kw: None)

    result_str = m_t._handle_send({
        "target": "slack:C0123456789",
        "message": "fallback",
        "slack_table": {"headers": ["a", "b"], "rows": [["1", "2"], ["3", "4"]]},  # 2 cols → reject
    })
    result = json.loads(result_str)
    assert "error" in result
    assert "3 columns" in result["error"]
    assert "bullet" in result["error"]


def test_parse_slack_thread_target(fresh_module):
    m_t = fresh_module("tarantino")
    chat_id, thread_id, explicit = m_t._parse_target_ref(
        "slack", "C0123456789:1778626719.373509"
    )
    assert explicit is True
    assert chat_id == "C0123456789"
    assert thread_id == "1778626719.373509"


def test_runtime_gate_passes_thread_id_to_blocks_sender(fresh_module, monkeypatch):
    m_t = fresh_module("tarantino")
    captured = {}

    async def _fake_send_slack_with_blocks(token, chat_id, message, blocks, thread_id=None):
        captured["chat_id"] = chat_id
        captured["thread_id"] = thread_id
        captured["blocks"] = blocks
        return {
            "success": True,
            "platform": "slack",
            "chat_id": chat_id,
            "message_id": "reply_ts",
            "mode": "blocks",
            "thread_id": thread_id,
        }

    monkeypatch.setattr(m_t, "_send_slack_with_blocks", _fake_send_slack_with_blocks)

    class _StubPConfig:
        enabled = True
        token = "xoxb-test"
        extra = {}

    class _StubGatewayConfig:
        platforms = {}
        def get_home_channel(self, p):
            return None

    from gateway.config import Platform as _Platform
    stub = _StubGatewayConfig()
    stub.platforms = {_Platform.SLACK: _StubPConfig()}
    monkeypatch.setattr("gateway.config.load_gateway_config", lambda: stub)
    monkeypatch.setattr(m_t, "_maybe_skip_cron_duplicate_send", lambda *a, **kw: None)
    monkeypatch.setattr("gateway.mirror.mirror_to_session", lambda *a, **kw: False)

    result_str = m_t._handle_send({
        "target": "slack:C0123456789:1778626719.373509",
        "message": "fallback summary",
        "slack_table": {
            "headers": ["a", "b", "c"],
            "rows": [["1", "2", "3"], ["4", "5", "6"]],
        },
    })
    result = json.loads(result_str)
    assert result.get("success") is True
    assert result.get("thread_id") == "1778626719.373509"
    assert captured["chat_id"] == "C0123456789"
    assert captured["thread_id"] == "1778626719.373509"
    assert captured["blocks"][0]["type"] == "table"


# ---------------------------------------------------------------------------
# Auto thread inheritance from session env
# ---------------------------------------------------------------------------

def test_auto_inherits_thread_from_session_env(fresh_module, monkeypatch):
    """When the gateway exposes HERMES_SESSION_THREAD_ID and we're posting to
    the same chat_id, the thread should be inherited automatically — even
    without a `:thread_ts` suffix on `target`.
    """
    m_t = fresh_module("tarantino")

    captured = {"chat_id": None, "thread_id": None, "blocks": None}

    async def _fake(token, chat_id, message, blocks, thread_id=None):
        captured["chat_id"] = chat_id
        captured["thread_id"] = thread_id
        captured["blocks"] = blocks
        return {
            "success": True, "platform": "slack", "chat_id": chat_id,
            "message_id": "ts9", "mode": "blocks",
            **({"thread_id": thread_id} if thread_id else {}),
        }

    monkeypatch.setattr(m_t, "_send_slack_with_blocks", _fake)

    class _StubPConfig:
        enabled = True
        token = "xoxb-test"
        extra = {}

    class _StubGatewayConfig:
        platforms = {}
        def get_home_channel(self, p):
            return None

    from gateway.config import Platform as _Platform
    stub = _StubGatewayConfig()
    stub.platforms = {_Platform.SLACK: _StubPConfig()}
    monkeypatch.setattr("gateway.config.load_gateway_config", lambda: stub)
    monkeypatch.setattr(m_t, "_maybe_skip_cron_duplicate_send", lambda *a, **kw: None)
    monkeypatch.setattr("gateway.mirror.mirror_to_session", lambda *a, **kw: False)

    # Pretend we're inside a Slack thread
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "slack")
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", "C0123456789")
    monkeypatch.setenv("HERMES_SESSION_THREAD_ID", "1778610929.846749")

    result_str = m_t._handle_send({
        "target": "slack:C0123456789",  # NO :thread_ts
        "message": "fallback summary",
        "slack_table": {
            "headers": ["a", "b", "c"],
            "rows": [["1", "2", "3"], ["4", "5", "6"]],
        },
    })
    result = json.loads(result_str)
    assert result.get("success") is True
    # Inherited from session, not from target
    assert captured["thread_id"] == "1778610929.846749"
    assert captured["chat_id"] == "C0123456789"


def test_explicit_thread_overrides_session_inherit(fresh_module, monkeypatch):
    m_t = fresh_module("tarantino")
    captured = {"thread_id": None}

    async def _fake(token, chat_id, message, blocks, thread_id=None):
        captured["thread_id"] = thread_id
        return {"success": True, "platform": "slack", "chat_id": chat_id, "message_id": "ts1", "mode": "blocks", "thread_id": thread_id}

    monkeypatch.setattr(m_t, "_send_slack_with_blocks", _fake)

    class _PC:
        enabled = True; token = "xoxb-test"; extra = {}
    class _GC:
        platforms = {}
        def get_home_channel(self, p): return None
    from gateway.config import Platform as _Platform
    stub = _GC(); stub.platforms = {_Platform.SLACK: _PC()}
    monkeypatch.setattr("gateway.config.load_gateway_config", lambda: stub)
    monkeypatch.setattr(m_t, "_maybe_skip_cron_duplicate_send", lambda *a, **kw: None)
    monkeypatch.setattr("gateway.mirror.mirror_to_session", lambda *a, **kw: False)

    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "slack")
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", "C0123456789")
    monkeypatch.setenv("HERMES_SESSION_THREAD_ID", "1778610929.846749")

    # Explicit pin to a different thread
    m_t._handle_send({
        "target": "slack:C0123456789:1700000000.000000",
        "message": "x",
        "slack_table": {"headers": ["a","b","c"], "rows": [["1","2","3"],["4","5","6"]]},
    })
    assert captured["thread_id"] == "1700000000.000000"


def test_no_inherit_when_chat_id_differs(fresh_module, monkeypatch):
    """If the target chat_id is different from the session chat, do NOT
    inherit the session thread (cross-channel posts must escape)."""
    m_t = fresh_module("tarantino")
    captured = {"thread_id": "sentinel"}

    async def _fake(token, chat_id, message, blocks, thread_id=None):
        captured["thread_id"] = thread_id
        return {"success": True, "platform": "slack", "chat_id": chat_id, "message_id": "ts1", "mode": "blocks"}

    monkeypatch.setattr(m_t, "_send_slack_with_blocks", _fake)

    class _PC:
        enabled = True; token = "xoxb-test"; extra = {}
    class _GC:
        platforms = {}
        def get_home_channel(self, p): return None
    from gateway.config import Platform as _Platform
    stub = _GC(); stub.platforms = {_Platform.SLACK: _PC()}
    monkeypatch.setattr("gateway.config.load_gateway_config", lambda: stub)
    monkeypatch.setattr(m_t, "_maybe_skip_cron_duplicate_send", lambda *a, **kw: None)
    monkeypatch.setattr("gateway.mirror.mirror_to_session", lambda *a, **kw: False)

    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "slack")
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", "C_SOURCE")
    monkeypatch.setenv("HERMES_SESSION_THREAD_ID", "1778610929.846749")

    m_t._handle_send({
        "target": "slack:C9999999999",
        "message": "x",
        "slack_table": {"headers": ["a","b","c"], "rows": [["1","2","3"],["4","5","6"]]},
    })
    assert captured["thread_id"] is None
