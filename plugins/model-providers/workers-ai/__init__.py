"""Cloudflare Workers AI provider profile."""

from typing import Any

from agent.moonshot_schema import is_moonshot_model
from providers import register_provider
from providers.base import ProviderProfile


class WorkersAIProfile(ProviderProfile):
    """Cloudflare Workers AI OpenAI-compatible API quirks."""

    def build_api_kwargs_extras(
        self,
        *,
        reasoning_config: dict | None = None,
        model: str | None = None,
        **context: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        extra_body: dict[str, Any] = {}

        if not is_moonshot_model(model):
            return extra_body, {}

        if reasoning_config and isinstance(reasoning_config, dict):
            effort = (reasoning_config.get("effort") or "").strip().lower()
            enabled = reasoning_config.get("enabled", True)
            if effort == "none" or enabled is False:
                extra_body["chat_template_kwargs"] = {"thinking": False}

        return extra_body, {}


workers_ai = WorkersAIProfile(
    name="workers-ai",
    aliases=("cloudflare-workers-ai", "cloudflare-ai"),
    env_vars=("CLOUDFLARE_API_TOKEN",),
    display_name="Cloudflare Workers AI",
    description="Cloudflare Workers AI OpenAI-compatible API",
    signup_url="https://developers.cloudflare.com/workers-ai/",
    base_url="https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/ai/v1",
    fallback_models=(
        "@cf/moonshotai/kimi-k2.6",
        "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    ),
)

register_provider(workers_ai)
