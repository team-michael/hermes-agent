"""Regression tests for the profile-local Cloudflare Workers AI adapter."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_PLUGIN_PATH = (
    Path(__file__).resolve().parents[3]
    / "ignored/local/plugins/model-providers/cloudflare/__init__.py"
)


@pytest.fixture(scope="module")
def cloudflare_profile():
    spec = importlib.util.spec_from_file_location(
        "test_local_cloudflare_provider", _PLUGIN_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.cloudflare


@pytest.mark.parametrize(
    "model",
    [
        "@cf/moonshotai/kimi-k2.6",
        "@cf/moonshotai/kimi-k2.7-code",
    ],
)
def test_kimi_max_is_forwarded_as_max(cloudflare_profile, model):
    extra_body, top_level = cloudflare_profile.build_api_kwargs_extras(
        model=model,
        reasoning_config={"enabled": True, "effort": "max"},
    )

    assert extra_body == {}
    assert top_level == {"reasoning_effort": "max"}


@pytest.mark.parametrize(
    "model",
    [
        "@cf/moonshotai/kimi-k2.6",
        "@cf/moonshotai/kimi-k2.7-code",
    ],
)
def test_kimi_xhigh_uses_provider_max_vocabulary(cloudflare_profile, model):
    _, top_level = cloudflare_profile.build_api_kwargs_extras(
        model=model,
        reasoning_config={"enabled": True, "effort": "xhigh"},
    )

    assert top_level == {"reasoning_effort": "max"}


def test_glm_xhigh_remains_xhigh(cloudflare_profile):
    _, top_level = cloudflare_profile.build_api_kwargs_extras(
        model="@cf/zai-org/glm-5.2",
        reasoning_config={"enabled": True, "effort": "xhigh"},
    )

    assert top_level == {"reasoning_effort": "xhigh"}


def test_glm_max_aliases_to_xhigh(cloudflare_profile):
    _, top_level = cloudflare_profile.build_api_kwargs_extras(
        model="@cf/zai-org/glm-5.2",
        reasoning_config={"enabled": True, "effort": "max"},
    )

    assert top_level == {"reasoning_effort": "xhigh"}


@pytest.mark.parametrize(
    "model",
    [
        "@cf/zai-org/glm-5.2",
        "@cf/moonshotai/kimi-k2.6",
        "@cf/moonshotai/kimi-k2.7-code",
    ],
)
def test_minimal_remains_low_for_supported_models(cloudflare_profile, model):
    _, top_level = cloudflare_profile.build_api_kwargs_extras(
        model=model,
        reasoning_config={"enabled": True, "effort": "minimal"},
    )

    assert top_level == {"reasoning_effort": "low"}
