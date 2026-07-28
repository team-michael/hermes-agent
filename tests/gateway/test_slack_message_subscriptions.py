"""Regression tests for repo-managed Slack message subscriptions."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from gateway.config import Platform, PlatformConfig, load_gateway_config
from gateway.platforms.base import (
    MessageEvent,
    MessageType,
    ProcessingOutcome,
    _PROCESSING_STATUS_DIRECTIVE_RE,
)
from gateway.session import SessionSource
from plugins.platforms.slack.adapter import SlackAdapter


CHANNEL_ID = "C04KT7EH5RQ"
OTHER_CHANNEL_ID = "C07LCLRS79T"
TEAM_ID = "T_WORKSPACE"
BOT_ID = "B_AMAZON_Q"
USER_ID = "U_AMAZON_Q"
APP_ID = "A_AMAZON_Q"
MESSAGE_TS = "1710000000.000100"
TMP_ROOT = Path.home() / ".hermes/tmp/slack-subscription-tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _subscription(**overrides):
    value = {
        "name": "amazon-q",
        "channels": [CHANNEL_ID],
        "subtypes": ["bot_message"],
        "bot_names": ["Amazon Q Developer"],
        "reactions": True,
        "final_reaction": "processing_status",
    }
    value.update(overrides)
    return value


def _event(channel=CHANNEL_ID, *, bot_name="Amazon Q Developer"):
    return {
        "type": "message",
        "subtype": "bot_message",
        "channel": channel,
        "channel_type": "channel",
        "team": TEAM_ID,
        "ts": MESSAGE_TS,
        "bot_id": BOT_ID,
        "user": USER_ID,
        "app_id": APP_ID,
        "username": bot_name,
        "text": "ALARM: CloudWatch metric threshold breached",
    }


def _adapter(*, subscription=None, allow_bots="filtered", extra=None):
    config_extra = dict(extra or {})
    config_extra["allow_bots"] = allow_bots
    if subscription is not None:
        config_extra["message_subscriptions"] = [subscription]
    adapter = SlackAdapter(PlatformConfig(enabled=True, extra=config_extra))
    adapter._bot_user_id = "U_HERMES"
    adapter._team_bot_user_ids = {TEAM_ID: "U_HERMES"}
    adapter.handle_message = AsyncMock()
    return adapter


def test_config_bridges_message_subscriptions() -> None:
    with tempfile.TemporaryDirectory(dir=TMP_ROOT) as raw:
        home = Path(raw)
        (home / "config.yaml").write_text(
            "slack:\n"
            "  message_subscriptions:\n"
            "    - name: notifly-help\n"
            f"      channels: [{CHANNEL_ID}]\n"
            "      bot_names: [Notifly Help]\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"HERMES_HOME": str(home)}, clear=False):
            config = load_gateway_config()

        subscriptions = config.platforms[Platform.SLACK].extra[
            "message_subscriptions"
        ]
        assert subscriptions[0]["name"] == "notifly-help"
        assert subscriptions[0]["channels"] == [CHANNEL_ID]


def test_subscription_matches_bot_name_case_insensitively() -> None:
    adapter = _adapter(subscription=_subscription())
    assert (
        adapter._matching_slack_message_subscription(
            _event(bot_name="amazon q developer")
        )
        is not None
    )


def test_subscription_requires_channel_and_identity() -> None:
    adapter = _adapter(subscription=_subscription())
    assert adapter._matching_slack_message_subscription(_event()) is not None
    assert (
        adapter._matching_slack_message_subscription(_event(OTHER_CHANNEL_ID))
        is None
    )

    no_identity = _adapter(
        subscription={"channels": [CHANNEL_ID], "subtypes": ["bot_message"]}
    )
    assert no_identity._matching_slack_message_subscription(_event()) is None


def test_filtered_subscription_dispatches_without_mention() -> None:
    adapter = _adapter(
        subscription=_subscription(prompt="Investigate this alert."),
    )

    asyncio.run(adapter._handle_slack_message(_event()))

    adapter.handle_message.assert_awaited_once()
    message = adapter.handle_message.await_args.args[0]
    assert "[Slack subscription context]" in message.text
    assert message.channel_prompt == "Investigate this alert."
    assert message.source.thread_id == MESSAGE_TS
    assert message.source.is_bot is True
    marker = adapter._workspace_message_marker(TEAM_ID, MESSAGE_TS)
    assert marker in adapter._reacting_message_ids
    key = adapter._slack_reaction_key(TEAM_ID, CHANNEL_ID, MESSAGE_TS)
    assert adapter._subscription_reaction_configs[key]["name"] == "amazon-q"


def test_subscription_attaches_validated_execution_limits() -> None:
    adapter = _adapter(
        subscription=_subscription(
            execution={
                "max_iterations": 6,
                "max_tool_calls": 3,
                "terminal_timeout": 30,
                "max_tool_output_chars": 12000,
                "ignored": 999,
            }
        )
    )

    asyncio.run(adapter._handle_slack_message(_event()))

    message = adapter.handle_message.await_args.args[0]
    assert message.metadata["execution_limits"] == {
        "max_iterations": 6,
        "max_tool_calls": 3,
        "terminal_timeout": 30,
        "max_tool_output_chars": 12000,
    }


def test_subscription_ignores_invalid_execution_limits() -> None:
    adapter = _adapter(
        subscription=_subscription(
            execution={
                "max_iterations": 0,
                "max_tool_calls": "not-a-number",
                "terminal_timeout": -1,
            }
        )
    )

    asyncio.run(adapter._handle_slack_message(_event()))

    message = adapter.handle_message.await_args.args[0]
    assert "execution_limits" not in message.metadata


def test_gateway_bounds_untrusted_event_execution_limits() -> None:
    from gateway.run import _normalize_event_execution_limits

    assert _normalize_event_execution_limits(
        {
            "max_iterations": 9999,
            "max_tool_calls": 3,
            "terminal_timeout": "30",
            "max_tool_output_chars": 12000,
            "ignored": 1,
        }
    ) == {
        "max_iterations": 500,
        "max_tool_calls": 3,
        "terminal_timeout": 30,
        "max_tool_output_chars": 12000,
    }
    assert _normalize_event_execution_limits(
        {
            "max_iterations": 0,
            "max_tool_calls": "bad",
        }
    ) == {}


def test_gateway_execution_limit_scope_restores_cached_agent() -> None:
    from agent.tool_guardrails import (
        ToolCallGuardrailConfig,
        ToolCallGuardrailController,
    )
    from gateway.run import _scoped_gateway_execution_limits
    from tools.terminal_tool import resolve_task_overrides

    controller = ToolCallGuardrailController(ToolCallGuardrailConfig())
    agent = SimpleNamespace(
        max_iterations=6,
        _tool_guardrails=controller,
    )
    original_config = controller.config
    task_id = "bounded-slack-alert"

    with _scoped_gateway_execution_limits(
        agent,
        task_id=task_id,
        limits={
            "max_tool_calls": 3,
            "terminal_timeout": 30,
            "max_tool_output_chars": 12000,
        },
        configured_max_iterations=300,
    ):
        assert controller.config.loop_caps.max_total_tools == 3
        assert resolve_task_overrides(task_id) == {
            "max_timeout": 30,
            "max_output_chars": 12000,
        }

    assert controller.config is original_config
    assert agent.max_iterations == 300
    assert resolve_task_overrides(task_id) == {}


def test_filtered_subscription_rejects_nonmatching_bot() -> None:
    adapter = _adapter(subscription=_subscription())

    asyncio.run(
        adapter._handle_slack_message(_event(bot_name="Unrelated Integration"))
    )

    adapter.handle_message.assert_not_awaited()


def test_free_response_channel_still_routes_all_bots() -> None:
    adapter = _adapter(
        allow_bots="all",
        extra={
            "free_response_channels": CHANNEL_ID,
            "channel_skill_bindings": [
                {"id": CHANNEL_ID, "skills": ["check"]},
            ],
        },
    )

    asyncio.run(adapter._handle_slack_message(_event()))

    adapter.handle_message.assert_awaited_once()
    message = adapter.handle_message.await_args.args[0]
    assert message.auto_skill == ["check"]


def test_processing_status_selects_warning_reaction() -> None:
    adapter = _adapter(subscription=_subscription())
    adapter._reactions_enabled = MagicMock(return_value=True)
    adapter._remove_reaction = AsyncMock(return_value=True)
    adapter._add_reaction = AsyncMock(return_value=True)
    marker = adapter._workspace_message_marker(TEAM_ID, MESSAGE_TS)
    adapter._reacting_message_ids.add(marker)
    key = adapter._slack_reaction_key(TEAM_ID, CHANNEL_ID, MESSAGE_TS)
    adapter._subscription_reaction_configs[key] = _subscription()
    event = MessageEvent(text="alert", message_id=MESSAGE_TS)
    event.source = adapter.build_source(
        chat_id=CHANNEL_ID,
        chat_type="group",
        scope_id=TEAM_ID,
    )
    event._hermes_response_text = (
        "지속 오류라 수정이 필요합니다. "
        "[[hermes:processing_status=needs_fix]]"
    )

    asyncio.run(
        adapter.on_processing_complete(event, ProcessingOutcome.SUCCESS)
    )

    adapter._remove_reaction.assert_awaited_once_with(
        CHANNEL_ID, MESSAGE_TS, "eyes", TEAM_ID
    )
    adapter._add_reaction.assert_awaited_once_with(
        CHANNEL_ID, MESSAGE_TS, "warning", TEAM_ID
    )


def test_processing_status_directive_is_hidden_from_response() -> None:
    response = (
        "Investigation complete.\n"
        "[[hermes:processing_status=no_action]]"
    )
    assert (
        _PROCESSING_STATUS_DIRECTIVE_RE.sub("", response).strip()
        == "Investigation complete."
    )


def test_filtered_bot_is_authorized_after_adapter_verification() -> None:
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.pairing_store = SimpleNamespace(
        is_approved=lambda *_args, **_kwargs: False
    )
    source = SessionSource(
        platform=Platform.SLACK,
        chat_id=CHANNEL_ID,
        chat_type="group",
        user_id=None,
        user_name="",
        is_bot=True,
    )
    with patch.dict(
        os.environ,
        {
            "SLACK_ALLOW_BOTS": "filtered",
            "SLACK_ALLOWED_USERS": "",
            "SLACK_ALLOW_ALL_USERS": "",
            "GATEWAY_ALLOWED_USERS": "",
            "GATEWAY_ALLOW_ALL_USERS": "",
        },
        clear=False,
    ):
        assert runner._is_user_authorized(source) is True


def test_dm_thread_command_keeps_command_text_and_dm_session_type() -> None:
    adapter = _adapter(allow_bots="none")
    adapter._has_active_session_for_thread = MagicMock(return_value=False)
    adapter._fetch_thread_context = AsyncMock(
        return_value="[Thread context - prior messages]\n"
    )
    adapter._collect_thread_root_images = AsyncMock(return_value=([], []))
    adapter._fetch_thread_parent_text = AsyncMock(return_value="Earlier message")
    event = {
        "type": "message",
        "channel": "D_DIRECT",
        "channel_type": "im",
        "team": TEAM_ID,
        "ts": "1710000001.000200",
        "thread_ts": "1710000000.000100",
        "user": "U_HUMAN",
        "client_msg_id": "client-message",
        "text": "!mute",
    }

    asyncio.run(adapter._handle_slack_message(event))

    adapter.handle_message.assert_awaited_once()
    message = adapter.handle_message.await_args.args[0]
    assert message.message_type == MessageType.COMMAND
    assert message.text == "/mute"
    assert message.channel_context == "[Thread context - prior messages]\n"
    assert any(
        call.kwargs.get("chat_type") == "dm"
        for call in adapter._has_active_session_for_thread.call_args_list
    )


def test_thread_mute_state_is_workspace_scoped_and_persistent() -> None:
    with tempfile.TemporaryDirectory(dir=TMP_ROOT) as raw:
        state_path = Path(raw) / "slack_muted_threads.json"
        adapter = _adapter(allow_bots="none")
        adapter._muted_threads_path = state_path
        adapter._muted_threads = set()

        assert adapter.mute_thread(
            CHANNEL_ID,
            MESSAGE_TS,
            team_id=TEAM_ID,
        )
        assert adapter.is_thread_muted(
            CHANNEL_ID,
            MESSAGE_TS,
            team_id=TEAM_ID,
        )
        assert not adapter.is_thread_muted(
            CHANNEL_ID,
            MESSAGE_TS,
            team_id="T_OTHER",
        )

        restored = _adapter(allow_bots="none")
        restored._muted_threads_path = state_path
        restored._muted_threads = restored._load_muted_threads()
        assert restored.is_thread_muted(
            CHANNEL_ID,
            MESSAGE_TS,
            team_id=TEAM_ID,
        )
        assert restored.unmute_thread(
            CHANNEL_ID,
            MESSAGE_TS,
            team_id=TEAM_ID,
        )
        assert not restored.is_thread_muted(
            CHANNEL_ID,
            MESSAGE_TS,
            team_id=TEAM_ID,
        )


def test_muted_thread_ignores_messages_but_allows_unmute() -> None:
    with tempfile.TemporaryDirectory(dir=TMP_ROOT) as raw:
        adapter = _adapter(allow_bots="none")
        adapter._muted_threads_path = Path(raw) / "slack_muted_threads.json"
        adapter._muted_threads = set()
        adapter.mute_thread(
            "D_DIRECT",
            MESSAGE_TS,
            team_id=TEAM_ID,
        )

        regular = {
            "type": "message",
            "channel": "D_DIRECT",
            "channel_type": "im",
            "team": TEAM_ID,
            "ts": "1710000001.000200",
            "thread_ts": MESSAGE_TS,
            "user": "U_HUMAN",
            "client_msg_id": "client-message-1",
            "text": "Are you still there?",
        }
        asyncio.run(adapter._handle_slack_message(regular))
        adapter.handle_message.assert_not_awaited()

        adapter._has_active_session_for_thread = MagicMock(return_value=True)
        unmute = {
            **regular,
            "ts": "1710000002.000300",
            "client_msg_id": "client-message-2",
            "text": "!unmute",
        }
        asyncio.run(adapter._handle_slack_message(unmute))

        adapter.handle_message.assert_awaited_once()
        message = adapter.handle_message.await_args.args[0]
        assert message.message_type == MessageType.COMMAND
        assert message.text == "/unmute"


def test_gateway_mute_and_unmute_commands() -> None:
    from gateway.run import GatewayRunner

    with tempfile.TemporaryDirectory(dir=TMP_ROOT) as raw:
        adapter = _adapter(allow_bots="none")
        adapter._muted_threads_path = Path(raw) / "slack_muted_threads.json"
        adapter._muted_threads = set()
        runner = object.__new__(GatewayRunner)
        runner.adapters = {Platform.SLACK: adapter}
        runner._running_agents = {}
        runner._session_key_for_source = lambda _source: "session-key"
        source = SessionSource(
            platform=Platform.SLACK,
            chat_id=CHANNEL_ID,
            chat_type="group",
            user_id="U_HUMAN",
            thread_id=MESSAGE_TS,
            scope_id=TEAM_ID,
        )
        mute_event = MessageEvent(
            text="/mute",
            message_type=MessageType.COMMAND,
            source=source,
            raw_message={},
        )
        unmute_event = MessageEvent(
            text="/unmute",
            message_type=MessageType.COMMAND,
            source=source,
            raw_message={},
        )

        assert "Muted" in asyncio.run(runner._handle_mute_command(mute_event))
        assert adapter.is_thread_muted(
            CHANNEL_ID,
            MESSAGE_TS,
            team_id=TEAM_ID,
        )
        assert "Unmuted" in asyncio.run(
            runner._handle_unmute_command(unmute_event)
        )
        assert not adapter.is_thread_muted(
            CHANNEL_ID,
            MESSAGE_TS,
            team_id=TEAM_ID,
        )


if __name__ == "__main__":
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"{len(tests)} Slack subscription tests passed")
