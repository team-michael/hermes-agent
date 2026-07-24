"""Tests for Cloudflare Workers AI model-specific reasoning wiring."""

from __future__ import annotations

import pytest


@pytest.fixture
def cloudflare_profile():
    import model_tools  # noqa: F401
    import providers

    profile = providers.get_provider_profile("cloudflare")
    assert profile is not None, "cloudflare provider profile must be registered"
    return profile


@pytest.mark.parametrize(
    ("reasoning_config", "expected_effort"),
    [
        ({"enabled": False}, None),
        ({"enabled": True, "effort": "low"}, "low"),
        ({"enabled": True, "effort": "medium"}, "medium"),
        ({"enabled": True, "effort": "high"}, "high"),
    ],
)
def test_nemotron_receives_reasoning_effort(
    cloudflare_profile, reasoning_config, expected_effort
):
    extra_body, top_level = cloudflare_profile.build_api_kwargs_extras(
        model="@cf/nvidia/nemotron-3-120b-a12b",
        reasoning_config=reasoning_config,
    )

    assert extra_body == {}
    expected = {"reasoning_effort": expected_effort} if expected_effort else {}
    assert top_level == expected


def test_kimi_disabled_still_sends_none(cloudflare_profile):
    extra_body, top_level = cloudflare_profile.build_api_kwargs_extras(
        model="@cf/moonshotai/kimi-k2.6",
        reasoning_config={"enabled": False},
    )

    assert extra_body == {}
    assert top_level == {"reasoning_effort": "none"}
