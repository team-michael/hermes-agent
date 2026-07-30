"""Cloudflare Workers AI provider profile."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from providers import register_provider
from providers.base import ProviderProfile, _profile_user_agent


_DEFAULT_BASE_URL = (
    "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"
)
_MODELS_SEARCH_URL = (
    "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/models/search"
)


def _env_value(name: str) -> str:
    try:
        from hermes_cli.config import get_env_value

        return (get_env_value(name) or "").strip()
    except Exception:
        return os.getenv(name, "").strip()


def _format_account_url(template: str) -> str:
    account_id = _env_value("CLOUDFLARE_ACCOUNT_ID") or _env_value(
        "CF_ACCOUNT_ID"
    )
    text = (template or "").strip()
    if account_id:
        text = text.replace("${CLOUDFLARE_ACCOUNT_ID}", account_id)
        text = text.replace("${CF_ACCOUNT_ID}", account_id)
        text = text.replace("{account_id}", account_id)
    return os.path.expandvars(text).rstrip("/")


def _normalize_reasoning_effort(
    reasoning_config: dict | None,
    *,
    model: str | None = None,
) -> str | None:
    if not isinstance(reasoning_config, dict):
        return None
    if reasoning_config.get("enabled") is False:
        return "none"

    effort = str(reasoning_config.get("effort") or "").strip().lower()
    aliases = {
        "off": "none",
        "disabled": "none",
        "minimal": "low",
        "min": "low",
        "x-high": "xhigh",
        "maximum": "max",
    }
    effort = aliases.get(effort, effort)

    model_name = str(model or "").strip().lower()
    if "moonshotai/kimi-" in model_name and effort in {"xhigh", "max"}:
        return "max"
    if effort == "max":
        return "xhigh"
    return effort or None


class CloudflareWorkersAIProfile(ProviderProfile):
    """Cloudflare Workers AI's OpenAI-compatible endpoint."""

    def build_api_kwargs_extras(
        self, *, reasoning_config: dict | None = None, **context: Any
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        effort = _normalize_reasoning_effort(
            reasoning_config,
            model=context.get("model"),
        )
        return ({}, {"reasoning_effort": effort}) if effort else ({}, {})

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        del base_url
        url = _format_account_url(_MODELS_SEARCH_URL)
        if "{account_id}" in url:
            return None

        params = urllib.parse.urlencode({"per_page": 1000})
        request = urllib.request.Request(f"{url}?{params}")
        token = api_key or _env_value("CLOUDFLARE_API_TOKEN")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", _profile_user_agent())

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode())
            result = data.get("result") if isinstance(data, dict) else data
            if isinstance(result, dict):
                result = result.get("result", [])
            models = [
                item.get("name") or item.get("id")
                for item in result or []
                if isinstance(item, dict)
            ]
            return sorted(
                {model for model in models if model and model.startswith("@cf/")}
            ) or None
        except Exception:
            return None


cloudflare = CloudflareWorkersAIProfile(
    name="cloudflare",
    aliases=("workers-ai", "cloudflare-ai", "cf", "cf-workers-ai"),
    display_name="Cloudflare Workers AI",
    description="Cloudflare Workers AI OpenAI-compatible endpoint",
    signup_url="https://developers.cloudflare.com/workers-ai/",
    env_vars=("CLOUDFLARE_API_TOKEN",),
    base_url=_format_account_url(_DEFAULT_BASE_URL),
    models_url=_format_account_url(_MODELS_SEARCH_URL),
    supports_health_check=False,
    fallback_models=(
        "@cf/zai-org/glm-5.2",
        "@cf/moonshotai/kimi-k2.6",
        "@cf/moonshotai/kimi-k2.7-code",
        "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    ),
)

register_provider(cloudflare)
