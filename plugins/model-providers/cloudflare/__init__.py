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
_CF_REASONING_FAMILIES = (
    "zai-org/glm-",
    "moonshotai/kimi-",
)


def _env_value(name: str) -> str:
    try:
        from hermes_cli.config import get_env_value

        return (get_env_value(name) or "").strip()
    except Exception:
        return os.getenv(name, "").strip()


def _account_id() -> str:
    return _env_value("CLOUDFLARE_ACCOUNT_ID") or _env_value("CF_ACCOUNT_ID")


def _format_account_url(template: str) -> str:
    account = _account_id()
    text = (template or "").strip()
    if account:
        text = text.replace("${CLOUDFLARE_ACCOUNT_ID}", account)
        text = text.replace("${CF_ACCOUNT_ID}", account)
        text = text.replace("{account_id}", account)
    return os.path.expandvars(text).rstrip("/")


def _normalize_cf_model(model: str | None) -> str:
    normalized = (model or "").strip().lower()
    if normalized.startswith("@cf/"):
        normalized = normalized[4:]
    return normalized


def _is_cf_reasoning_family(model: str | None) -> bool:
    normalized = _normalize_cf_model(model)
    return normalized.startswith(_CF_REASONING_FAMILIES)


def _normalize_reasoning_effort(reasoning_config: dict | None) -> str | None:
    """Return a Workers AI-safe reasoning_effort value.

    GLM accepts the full Hermes ladder, but Kimi currently accepts only
    none/low/medium/high.  Clamp Hermes' wider vocabulary to the shared
    Cloudflare Workers AI denominator so swapping GLM <-> Kimi does not turn a
    valid config into a 400.
    """
    if not isinstance(reasoning_config, dict):
        return None

    if reasoning_config.get("enabled") is False:
        return "none"

    effort = str(reasoning_config.get("effort") or "").strip().lower()
    if not effort:
        return None
    if effort in {"none", "off", "disabled"}:
        return "none"
    if effort in {"minimal", "min"}:
        return "low"
    if effort in {"low", "medium", "high"}:
        return effort
    if effort in {"xhigh", "x-high", "max", "maximum"}:
        return "high"
    return None


class CloudflareWorkersAIProfile(ProviderProfile):
    """Cloudflare Workers AI OpenAI-compatible profile.

    Cloudflare exposes several model-specific reasoning dialects.  The common
    denominator for GLM and Kimi on the OpenAI-compatible endpoint is the
    top-level ``reasoning_effort`` field.
    """

    def build_api_kwargs_extras(
        self, *, reasoning_config: dict | None = None, **context: Any
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        model = context.get("model")
        effort = _normalize_reasoning_effort(reasoning_config)
        if effort and _is_cf_reasoning_family(model):
            return {}, {"reasoning_effort": effort}
        return {}, {}

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        account = _account_id()
        if not account:
            return None

        url = _format_account_url(_MODELS_SEARCH_URL)
        params = urllib.parse.urlencode({"per_page": 1000})
        req = urllib.request.Request(f"{url}?{params}")
        token = api_key or _env_value("CLOUDFLARE_API_TOKEN")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", _profile_user_agent())

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            result = data.get("result") if isinstance(data, dict) else data
            items = result if isinstance(result, list) else result.get("result", []) if isinstance(result, dict) else []
            models: list[str] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("id")
                if isinstance(name, str) and name.startswith("@cf/"):
                    models.append(name)
            return sorted(set(models)) or None
        except Exception:
            return None


cloudflare = CloudflareWorkersAIProfile(
    name="cloudflare",
    aliases=("workers-ai", "cloudflare-ai", "cf", "cf-workers-ai"),
    display_name="Cloudflare Workers AI",
    description="Cloudflare Workers AI OpenAI-compatible endpoint",
    signup_url="https://developers.cloudflare.com/workers-ai/",
    env_vars=("CLOUDFLARE_API_TOKEN",),
    base_url=_DEFAULT_BASE_URL,
    models_url=_MODELS_SEARCH_URL,
    supports_health_check=False,
    fallback_models=(
        "@cf/zai-org/glm-5.2",
        "@cf/moonshotai/kimi-k2.6",
        "@cf/moonshotai/kimi-k2.7-code",
        "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    ),
)

register_provider(cloudflare)
