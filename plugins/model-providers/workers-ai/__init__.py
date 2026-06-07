"""Cloudflare Workers AI provider profile."""

from typing import Any

from providers import register_provider
from providers.base import ProviderProfile


_WORKERS_AI_REASONING_EFFORTS = {"none", "low", "medium", "high"}
_WORKERS_AI_REASONING_ALIASES = {
    "minimal": "low",
    "xhigh": "high",
    "max": "high",
}


def _normalize_reasoning_effort(reasoning_config: dict | None) -> str | None:
    if not reasoning_config or not isinstance(reasoning_config, dict):
        return None

    enabled = reasoning_config.get("enabled", True)
    raw_effort = (reasoning_config.get("effort") or "").strip().lower()

    if enabled is False or raw_effort == "none":
        return "none"
    if raw_effort in _WORKERS_AI_REASONING_EFFORTS:
        return raw_effort
    return _WORKERS_AI_REASONING_ALIASES.get(raw_effort)


class WorkersAIProfile(ProviderProfile):
    """Cloudflare Workers AI OpenAI-compatible API quirks."""

    def build_api_kwargs_extras(
        self,
        *,
        reasoning_config: dict | None = None,
        model: str | None = None,
        **context: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        top_level: dict[str, Any] = {}
        effort = _normalize_reasoning_effort(reasoning_config)
        if effort:
            top_level["reasoning_effort"] = effort
        return {}, top_level


workers_ai = WorkersAIProfile(
    name="workers-ai",
    aliases=("cloudflare-workers-ai", "cloudflare-ai"),
    # Keep this empty so hermes_cli.auth does not auto-register Workers AI as
    # a built-in API-key runtime provider. Existing profile configs define it
    # under `providers.workers-ai` with a user-specific account URL.
    env_vars=(),
    display_name="Cloudflare Workers AI",
    description="Cloudflare Workers AI OpenAI-compatible API",
    signup_url="https://developers.cloudflare.com/workers-ai/",
    base_url="",
    fallback_models=(
        "@cf/moonshotai/kimi-k2.6",
        "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    ),
)

register_provider(workers_ai)
