"""Regression tests for team-managed Slack extensions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import MessageEvent, MessageType
from gateway.run import GatewayRunner
from gateway.session import SessionSource, build_session_key
from plugins.platforms.slack.adapter import SlackAdapter


@pytest.fixture
def adapter(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    instance = SlackAdapter(
        PlatformConfig(enabled=True, token="xoxb-test", extra={})
    )
    instance._bot_user_id = "U_BOT"
    instance._team_bot_user_ids = {}
    instance._app = SimpleNamespace(client=MagicMock())
    instance.handle_message = AsyncMock()
    instance._resolve_user_name = AsyncMock(return_value="User One")
    instance._fetch_thread_context = AsyncMock(return_value="")
    instance._fetch_thread_parent_text = AsyncMock(return_value="")
    return instance


class TestThreadMute:
    def test_mute_state_persists(self, adapter):
        assert adapter.mute_thread("C1", "123.000") is True
        assert adapter.is_thread_muted("C1", "123.000")

        restored = SlackAdapter(
            PlatformConfig(enabled=True, token="xoxb-test", extra={})
        )
        assert restored.is_thread_muted("C1", "123.000")
        assert restored.unmute_thread("C1", "123.000") is True
        assert not restored.is_thread_muted("C1", "123.000")

    @pytest.mark.asyncio
    async def test_muted_thread_is_ignored_even_when_mentioned(self, adapter):
        adapter.mute_thread("C1", "123.000")
        event = {
            "channel": "C1",
            "channel_type": "channel",
            "user": "U1",
            "text": "<@U_BOT> investigate",
            "ts": "123.456",
            "thread_ts": "123.000",
        }

        await adapter._handle_slack_message(event)

        adapter.handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unmute_command_reaches_muted_thread(self, adapter):
        adapter.mute_thread("C1", "123.000")
        adapter._has_active_session_for_thread = MagicMock(return_value=True)
        event = {
            "channel": "C1",
            "channel_type": "channel",
            "user": "U1",
            "text": "<@U_BOT> !unmute",
            "ts": "123.456",
            "thread_ts": "123.000",
        }

        await adapter._handle_slack_message(event)

        adapter.handle_message.assert_awaited_once()
        message = adapter.handle_message.await_args.args[0]
        assert message.text == "/unmute"
        assert message.message_type == MessageType.COMMAND
        assert message.source.thread_id == "123.000"

    @pytest.mark.asyncio
    async def test_command_targeted_at_another_bot_is_ignored(self, adapter):
        adapter.mute_thread("C1", "123.000")
        adapter._has_active_session_for_thread = MagicMock(return_value=True)
        event = {
            "channel": "C1",
            "channel_type": "channel",
            "user": "U1",
            "text": "<@U_OTHER_BOT> !unmute",
            "ts": "123.456",
            "thread_ts": "123.000",
        }

        await adapter._handle_slack_message(event)

        adapter.handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_gateway_mute_and_unmute_commands(self, adapter):
        runner = object.__new__(GatewayRunner)
        runner.adapters = {Platform.SLACK: adapter}
        runner._running_agents = {}
        runner._session_key_for_source = lambda source: build_session_key(source)
        source = SessionSource(
            platform=Platform.SLACK,
            chat_id="C1",
            chat_type="group",
            user_id="U1",
            thread_id="123.000",
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

        assert "Muted" in await runner._handle_mute_command(mute_event)
        assert adapter.is_thread_muted("C1", "123.000")
        assert "Unmuted" in await runner._handle_unmute_command(unmute_event)
        assert not adapter.is_thread_muted("C1", "123.000")


class TestSlackTableDirective:
    @pytest.mark.asyncio
    async def test_send_renders_table_in_the_same_thread(
        self, adapter, monkeypatch
    ):
        monkeypatch.setenv("HERMES_PROFILE", "tarantino")
        adapter._app.client.chat_postMessage = AsyncMock(
            return_value={"ts": "ts_table"}
        )
        adapter.stop_typing = AsyncMock()
        content = (
            "**Scope**\n\n"
            "```slack-table\n"
            '{"headers":["file","location","managed"],'
            '"rows":[["a.py","repo","yes"],["b.py","repo","yes"]]}'
            "\n```"
        )

        await adapter.send(
            "C123456789",
            content,
            reply_to="1778626719.373509",
        )

        kwargs = adapter._app.client.chat_postMessage.call_args.kwargs
        assert kwargs["thread_ts"] == "1778626719.373509"
        assert "slack-table" not in kwargs["text"]
        assert kwargs["blocks"][0]["type"] == "table"

    @pytest.mark.asyncio
    async def test_table_directive_is_profile_gated(self, adapter, monkeypatch):
        monkeypatch.setenv("HERMES_PROFILE", "unknown-profile")
        adapter._app.client.chat_postMessage = AsyncMock(return_value={"ts": "ts1"})
        content = (
            "Visible\n\n"
            "```slack-table\n"
            '{"headers":["a","b","c"],'
            '"rows":[["1","2","3"],["4","5","6"]]}'
            "\n```"
        )

        await adapter.send("C123456789", content)

        kwargs = adapter._app.client.chat_postMessage.call_args.kwargs
        assert "blocks" not in kwargs
        assert "slack-table" in kwargs["text"]
