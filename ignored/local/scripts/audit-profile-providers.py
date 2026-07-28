#!/usr/bin/env python3
"""Verify that every configured profile provider resolves after an update."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from local_state import HERMES_ROOT


def _configured_providers(
    config: dict[str, Any],
) -> list[tuple[str, str, str]]:
    providers: list[tuple[str, str, str]] = []

    def add(path: str, value: Any) -> None:
        if not isinstance(value, dict):
            return
        provider = value.get("provider")
        if isinstance(provider, str) and provider.strip():
            model = value.get("model") or value.get("default") or ""
            providers.append(
                (path, provider.strip(), str(model).strip())
            )

    add("model", config.get("model"))
    fallback = config.get("fallback_model")
    if isinstance(fallback, dict):
        add("fallback_model", fallback)
    elif isinstance(fallback, list):
        for index, entry in enumerate(fallback):
            add(f"fallback_model[{index}]", entry)

    auxiliary = config.get("auxiliary")
    if isinstance(auxiliary, dict):
        for name, entry in auxiliary.items():
            add(f"auxiliary.{name}", entry)
    return providers


def _audit_one(profile_home: Path) -> list[str]:
    os.environ["HERMES_HOME"] = str(profile_home)
    config_path = profile_home / "config.yaml"
    if not config_path.exists():
        return [f"missing config: {config_path}"]
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return [f"config is not a mapping: {config_path}"]

    from hermes_cli.auth import PROVIDER_REGISTRY
    from hermes_cli.config import get_compatible_custom_providers
    from hermes_cli.providers import resolve_provider_full
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from providers import get_provider_profile

    user_providers = data.get("providers")
    if not isinstance(user_providers, dict):
        user_providers = {}
    custom_providers = get_compatible_custom_providers(data)

    issues: list[str] = []
    for path, raw_provider, model in _configured_providers(data):
        provider = raw_provider.lower()
        if provider in {"auto", "moa"}:
            continue
        resolved = resolve_provider_full(
            provider,
            user_providers,
            custom_providers,
        )
        plugin = get_provider_profile(provider)
        if (
            provider not in PROVIDER_REGISTRY
            and resolved is None
            and plugin is None
        ):
            issues.append(
                f"{path}.provider '{raw_provider}' is not recognised"
            )
            continue

        try:
            runtime = resolve_runtime_provider(
                requested=provider,
                target_model=model or None,
            )
        except Exception as exc:
            summary = str(exc).splitlines()[0] or type(exc).__name__
            issues.append(
                f"{path}.provider '{raw_provider}' runtime resolution failed: "
                f"{summary}"
            )
            continue

        base_url = str(runtime.get("base_url") or "")
        if any(
            marker in base_url
            for marker in (
                "{account_id}",
                "${CLOUDFLARE_ACCOUNT_ID}",
                "${CF_ACCOUNT_ID}",
            )
        ):
            issues.append(
                f"{path}.provider '{raw_provider}' has an unresolved "
                "account-scoped base URL"
            )
    return issues


def _profile_homes() -> list[Path]:
    profiles_root = HERMES_ROOT / "profiles"
    if not profiles_root.exists():
        return []
    return sorted(
        path for path in profiles_root.iterdir()
        if path.is_dir() and (path / "config.yaml").exists()
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-home", type=Path)
    args = parser.parse_args()

    if args.profile_home is not None:
        issues = _audit_one(args.profile_home.expanduser().resolve())
        for issue in issues:
            print(issue)
        return 1 if issues else 0

    failures: list[str] = []
    for profile_home in _profile_homes():
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--profile-home",
                str(profile_home),
            ],
            cwd=Path(__file__).resolve().parents[3],
            text=True,
            capture_output=True,
            env={**os.environ, "HERMES_HOME": str(profile_home)},
        )
        if result.returncode:
            detail = result.stdout.strip() or result.stderr.strip()
            failures.append(f"{profile_home.name}: {detail}")
        else:
            print(f"provider audit ok: {profile_home.name}")

    if failures:
        print("profile provider audit failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
