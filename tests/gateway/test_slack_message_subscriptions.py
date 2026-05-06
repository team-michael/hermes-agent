"""Tests for Slack message subscriptions."""

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import MessageEvent, ProcessingOutcome


def _ensure_slack_mock():
    if "slack_bolt" in sys.modules and hasattr(sys.modules["slack_bolt"], "__file__"):
        return

    slack_bolt = MagicMock()
    slack_bolt.async_app.AsyncApp = MagicMock
    slack_bolt.adapter.socket_mode.async_handler.AsyncSocketModeHandler = MagicMock

    slack_sdk = MagicMock()
    slack_sdk.web.async_client.AsyncWebClient = MagicMock

    for name, mod in [
        ("slack_bolt", slack_bolt),
        ("slack_bolt.async_app", slack_bolt.async_app),
        ("slack_bolt.adapter", slack_bolt.adapter),
        ("slack_bolt.adapter.socket_mode", slack_bolt.adapter.socket_mode),
        ("slack_bolt.adapter.socket_mode.async_handler", slack_bolt.adapter.socket_mode.async_handler),
        ("slack_sdk", slack_sdk),
        ("slack_sdk.web", slack_sdk.web),
        ("slack_sdk.web.async_client", slack_sdk.web.async_client),
    ]:
        sys.modules.setdefault(name, mod)


_ensure_slack_mock()

import gateway.platforms.slack as _slack_mod

_slack_mod.SLACK_AVAILABLE = True

from gateway.platforms.slack import SlackAdapter  # noqa: E402


CHANNEL_ID = "C04KT7EH5RQ"
OTHER_CHANNEL_ID = "C07LCLRS79T"
BOT_ID = "B04KVM217J8"
USER_ID = "U04KQ8Z6BM3"
APP_ID = "A6L22LZNH"


def _make_adapter(subscription=None):
    extra = {}
    if subscription is not None:
        extra["message_subscriptions"] = [subscription]

    adapter = object.__new__(SlackAdapter)
    adapter.platform = Platform.SLACK
    adapter.config = PlatformConfig(enabled=True, extra=extra)
    adapter._bot_user_id = "U_HASHIMOTO"
    adapter._team_bot_user_ids = {}
    adapter._reacting_message_ids = set()
    adapter._subscription_reaction_configs = {}
    return adapter


def _make_real_adapter(subscription):
    adapter = SlackAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "allow_bots": "filtered",
                "message_subscriptions": [subscription],
            },
        )
    )
    adapter._bot_user_id = "U_HASHIMOTO"
    adapter.handle_message = AsyncMock()
    return adapter


def _make_free_response_adapter(extra):
    adapter = SlackAdapter(PlatformConfig(enabled=True, extra=extra))
    adapter._bot_user_id = "U_HASHIMOTO"
    adapter.handle_message = AsyncMock()
    return adapter


def _amazon_q_event(channel=CHANNEL_ID, *, bot_id=BOT_ID, user_id=USER_ID, app_id=APP_ID):
    return {
        "type": "message",
        "subtype": "bot_message",
        "channel": channel,
        "ts": "1710000000.000100",
        "bot_id": bot_id,
        "user": user_id,
        "app_id": app_id,
        "username": "Amazon Q Developer",
        "text": "ALARM: CloudWatch metric threshold breached",
    }


def test_message_subscription_matches_exact_bot_identity():
    adapter = _make_adapter(
        {
            "channels": [CHANNEL_ID, OTHER_CHANNEL_ID],
            "bot_ids": [BOT_ID],
            "user_ids": [USER_ID],
            "app_ids": [APP_ID],
            "bot_names": ["Amazon Q Developer"],
        }
    )

    assert adapter._matching_slack_message_subscription(_amazon_q_event()) is not None


def test_message_subscription_treats_bot_id_as_bot_message_subtype():
    adapter = _make_adapter(
        {
            "channels": [CHANNEL_ID],
            "subtypes": ["bot_message"],
            "bot_ids": [BOT_ID],
            "user_ids": [USER_ID],
            "app_ids": [APP_ID],
        }
    )
    event = _amazon_q_event()
    event.pop("subtype")

    assert adapter._matching_slack_message_subscription(event) is not None


def test_message_subscription_rejects_wrong_channel():
    adapter = _make_adapter(
        {
            "channels": [OTHER_CHANNEL_ID],
            "bot_id": BOT_ID,
            "user_id": USER_ID,
            "app_id": APP_ID,
        }
    )

    assert adapter._matching_slack_message_subscription(_amazon_q_event()) is None


def test_message_subscription_rejects_wrong_app_id():
    adapter = _make_adapter(
        {
            "channels": [CHANNEL_ID],
            "bot_id": BOT_ID,
            "user_id": USER_ID,
            "app_id": "A_DIFFERENT_APP",
        }
    )

    assert adapter._matching_slack_message_subscription(_amazon_q_event()) is None


def test_message_subscription_requires_identity_filter():
    adapter = _make_adapter({"channels": [CHANNEL_ID]})

    assert adapter._matching_slack_message_subscription(_amazon_q_event()) is None


def test_message_subscription_bypasses_mention_by_default():
    adapter = _make_adapter()

    assert adapter._slack_subscription_bypasses_mention({"channels": [CHANNEL_ID]}) is True
    assert adapter._slack_subscription_bypasses_mention({"bypass_mention": False}) is False


@pytest.mark.asyncio
async def test_filtered_subscription_message_bypasses_mention_and_dispatches():
    adapter = _make_real_adapter(
        {
            "name": "amazon-q",
            "channels": [CHANNEL_ID],
            "bot_ids": [BOT_ID],
            "user_ids": [USER_ID],
            "app_ids": [APP_ID],
            "prompt": "Investigate this CloudWatch alert.",
            "final_reaction": "resolved_marker",
        }
    )

    await adapter._handle_slack_message(_amazon_q_event())

    adapter.handle_message.assert_awaited_once()
    msg_event = adapter.handle_message.await_args.args[0]
    assert "[Slack subscription context]" in msg_event.text
    assert f"bot_id: {BOT_ID}" in msg_event.text
    assert msg_event.channel_prompt == "Investigate this CloudWatch alert."
    assert "1710000000.000100" in adapter._reacting_message_ids
    assert adapter._subscription_reaction_configs[f"{CHANNEL_ID}:1710000000.000100"]["name"] == "amazon-q"


@pytest.mark.asyncio
async def test_free_response_channel_can_process_bot_message_with_auto_skill():
    adapter = _make_free_response_adapter(
        {
            "allow_bots": "all",
            "free_response_channels": CHANNEL_ID,
            "channel_prompts": {
                CHANNEL_ID: "Monitoring alert received. Use the check skill.",
            },
            "channel_skill_bindings": [
                {"id": CHANNEL_ID, "skills": ["check"]},
            ],
        }
    )

    await adapter._handle_slack_message(_amazon_q_event())

    adapter.handle_message.assert_awaited_once()
    msg_event = adapter.handle_message.await_args.args[0]
    assert msg_event.source.chat_id == CHANNEL_ID
    assert msg_event.source.thread_id == "1710000000.000100"
    assert msg_event.channel_prompt == "Monitoring alert received. Use the check skill."
    assert msg_event.auto_skill == ["check"]


@pytest.mark.asyncio
async def test_allow_bots_all_still_ignores_known_own_bot_message_ts():
    adapter = _make_free_response_adapter(
        {
            "allow_bots": "all",
            "free_response_channels": CHANNEL_ID,
            "channel_skill_bindings": [
                {"id": CHANNEL_ID, "skills": ["check"]},
            ],
        }
    )
    adapter._bot_message_ts.add("1710000000.000100")

    await adapter._handle_slack_message(_amazon_q_event())

    adapter.handle_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_filtered_nonmatching_bot_message_is_ignored():
    adapter = _make_real_adapter(
        {
            "channels": [CHANNEL_ID],
            "bot_id": BOT_ID,
            "user_id": USER_ID,
            "app_id": APP_ID,
        }
    )

    await adapter._handle_slack_message(_amazon_q_event(app_id="A_DIFFERENT_APP"))

    adapter.handle_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolved_marker_adds_success_reaction(monkeypatch):
    monkeypatch.delenv("SLACK_SUCCESS_REACTION", raising=False)
    adapter = _make_adapter()
    adapter._reactions_enabled = MagicMock(return_value=True)
    adapter._remove_reaction = AsyncMock(return_value=True)
    adapter._add_reaction = AsyncMock(return_value=True)
    adapter._reacting_message_ids.add("1710000000.000100")
    adapter._subscription_reaction_configs[f"{CHANNEL_ID}:1710000000.000100"] = {
        "final_reaction": "resolved_marker"
    }
    event = MessageEvent(text="alert", message_id="1710000000.000100")
    event.source = adapter.build_source(chat_id=CHANNEL_ID, chat_type="group")
    event._hermes_response_text = "일시적인 spike입니다. [[hermes:processing_status=no_action]]"

    await adapter.on_processing_complete(event, ProcessingOutcome.SUCCESS)

    adapter._remove_reaction.assert_awaited_once_with(CHANNEL_ID, "1710000000.000100", "eyes")
    adapter._add_reaction.assert_awaited_once_with(CHANNEL_ID, "1710000000.000100", "white_check_mark")


@pytest.mark.asyncio
async def test_resolved_marker_uses_success_reaction_env_override(monkeypatch):
    monkeypatch.setenv("SLACK_SUCCESS_REACTION", "smiley_cat")
    adapter = _make_adapter()
    adapter._reactions_enabled = MagicMock(return_value=True)
    adapter._remove_reaction = AsyncMock(return_value=True)
    adapter._add_reaction = AsyncMock(return_value=True)
    adapter._reacting_message_ids.add("1710000000.000100")
    adapter._subscription_reaction_configs[f"{CHANNEL_ID}:1710000000.000100"] = {
        "final_reaction": "resolved_marker"
    }
    event = MessageEvent(text="alert", message_id="1710000000.000100")
    event.source = adapter.build_source(chat_id=CHANNEL_ID, chat_type="group")
    event._hermes_response_text = "일시적인 spike입니다. [[hermes:processing_status=no_action]]"

    await adapter.on_processing_complete(event, ProcessingOutcome.SUCCESS)

    adapter._remove_reaction.assert_awaited_once_with(CHANNEL_ID, "1710000000.000100", "eyes")
    adapter._add_reaction.assert_awaited_once_with(CHANNEL_ID, "1710000000.000100", "smiley_cat")


@pytest.mark.asyncio
async def test_nonresolved_marker_omits_success_reaction():
    adapter = _make_adapter()
    adapter._reactions_enabled = MagicMock(return_value=True)
    adapter._remove_reaction = AsyncMock(return_value=True)
    adapter._add_reaction = AsyncMock(return_value=True)
    adapter._reacting_message_ids.add("1710000000.000100")
    adapter._subscription_reaction_configs[f"{CHANNEL_ID}:1710000000.000100"] = {
        "final_reaction": "resolved_marker"
    }
    event = MessageEvent(text="alert", message_id="1710000000.000100")
    event.source = adapter.build_source(chat_id=CHANNEL_ID, chat_type="group")
    event._hermes_response_text = "지속 오류라 수정이 필요합니다. [[hermes:processing_status=needs_fix]]"

    await adapter.on_processing_complete(event, ProcessingOutcome.SUCCESS)

    adapter._remove_reaction.assert_awaited_once_with(CHANNEL_ID, "1710000000.000100", "eyes")
    adapter._add_reaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_processing_status_policy_adds_needs_fix_reaction():
    adapter = _make_adapter()
    adapter._reactions_enabled = MagicMock(return_value=True)
    adapter._remove_reaction = AsyncMock(return_value=True)
    adapter._add_reaction = AsyncMock(return_value=True)
    adapter._reacting_message_ids.add("1710000000.000100")
    adapter._subscription_reaction_configs[f"{CHANNEL_ID}:1710000000.000100"] = {
        "final_reaction": "processing_status"
    }
    event = MessageEvent(text="alert", message_id="1710000000.000100")
    event.source = adapter.build_source(chat_id=CHANNEL_ID, chat_type="group")
    event._hermes_response_text = "지속 오류라 수정이 필요합니다. [[hermes:processing_status=needs_fix]]"

    await adapter.on_processing_complete(event, ProcessingOutcome.SUCCESS)

    adapter._remove_reaction.assert_awaited_once_with(CHANNEL_ID, "1710000000.000100", "eyes")
    adapter._add_reaction.assert_awaited_once_with(CHANNEL_ID, "1710000000.000100", "warning")


@pytest.mark.asyncio
async def test_processing_status_policy_adds_urgent_reaction():
    adapter = _make_adapter()
    adapter._reactions_enabled = MagicMock(return_value=True)
    adapter._remove_reaction = AsyncMock(return_value=True)
    adapter._add_reaction = AsyncMock(return_value=True)
    adapter._reacting_message_ids.add("1710000000.000100")
    adapter._subscription_reaction_configs[f"{CHANNEL_ID}:1710000000.000100"] = {
        "final_reaction": "processing_status"
    }
    event = MessageEvent(text="alert", message_id="1710000000.000100")
    event.source = adapter.build_source(chat_id=CHANNEL_ID, chat_type="group")
    event._hermes_response_text = "@engineers 즉시 확인 필요. [[hermes:processing_status=urgent]]"

    await adapter.on_processing_complete(event, ProcessingOutcome.SUCCESS)

    adapter._remove_reaction.assert_awaited_once_with(CHANNEL_ID, "1710000000.000100", "eyes")
    adapter._add_reaction.assert_awaited_once_with(CHANNEL_ID, "1710000000.000100", "rotating_light")
