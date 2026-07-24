"""Cloudflare Workers AI capacity errors should retry before fallback."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from run_agent import AIAgent


class CloudflareCapacityError(Exception):
    status_code = 429

    def __init__(self):
        super().__init__(
            'HTTP 429: {"errors":[{"message":"Capacity temporarily exceeded",'
            '"code":3040}]}'
        )
        self.response = SimpleNamespace(headers={})
        self.body = {
            "errors": [
                {"message": "Capacity temporarily exceeded", "code": 3040}
            ]
        }


def _response(content):
    message = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    return SimpleNamespace(choices=[choice], model="test-model", usage=None)


def _agent():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "terminal",
                "description": "run command",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    with (
        patch("run_agent.get_tool_definitions", return_value=tools),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI", return_value=MagicMock()),
    ):
        agent = AIAgent(
            api_key="cloudflare-key",
            base_url="https://api.cloudflare.com/client/v4/accounts/test/ai/v1",
            provider="cloudflare",
            model="@cf/moonshotai/kimi-k2.6",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            fallback_model=[
                {
                    "provider": "bedrock",
                    "model": "us.anthropic.claude-sonnet-5",
                }
            ],
        )
    agent.client = MagicMock()
    agent._api_max_retries = 3
    return agent


def _fallback_client():
    client = MagicMock()
    client.api_key = "bedrock-key"
    client.base_url = "https://bedrock-runtime.us-east-1.amazonaws.com"
    client._custom_headers = None
    client.default_headers = None
    return client


def _run(agent, api_call):
    with (
        patch.object(agent, "_interruptible_api_call", side_effect=api_call),
        patch.object(agent, "_persist_session"),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
        patch("run_agent.OpenAI", return_value=MagicMock()),
        patch("agent.agent_runtime_helpers.time.sleep"),
        patch(
            "agent.auxiliary_client.resolve_provider_client",
            return_value=(_fallback_client(), "us.anthropic.claude-sonnet-5"),
        ) as resolve_fallback,
        patch(
            "hermes_cli.model_normalize.normalize_model_for_provider",
            side_effect=lambda model, provider: model,
        ),
        patch("agent.model_metadata.get_model_context_length", return_value=262144),
    ):
        result = agent.run_conversation("hello")
    return result, resolve_fallback


def test_cloudflare_3040_retries_primary_before_fallback():
    agent = _agent()
    calls = []
    primary_attempts = 0

    def api_call(_kwargs):
        nonlocal primary_attempts
        calls.append(agent.provider)
        if agent.provider == "cloudflare":
            primary_attempts += 1
            if primary_attempts < 3:
                raise CloudflareCapacityError()
        return _response("Recovered on Cloudflare")

    result, resolve_fallback = _run(agent, api_call)

    assert result["completed"] is True
    assert result["final_response"] == "Recovered on Cloudflare"
    assert calls == ["cloudflare", "cloudflare", "cloudflare"]
    resolve_fallback.assert_not_called()


def test_cloudflare_3040_falls_back_after_retry_exhaustion():
    agent = _agent()
    calls = []

    def api_call(_kwargs):
        calls.append(agent.provider)
        if agent.provider == "cloudflare":
            raise CloudflareCapacityError()
        return _response("Recovered via Bedrock")

    result, resolve_fallback = _run(agent, api_call)

    assert result["completed"] is True
    assert result["final_response"] == "Recovered via Bedrock"
    assert calls == ["cloudflare", "cloudflare", "cloudflare", "bedrock"]
    resolve_fallback.assert_called_once()
