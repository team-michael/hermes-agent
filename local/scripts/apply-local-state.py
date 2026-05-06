#!/usr/bin/env python3
"""Apply repo-managed local Hermes profile state.

This script intentionally manages only safe, explicit assets:
- config overlays
- skill directory symlinks
- optional SOUL.md symlinks

It never copies .env, auth.json, sessions, logs, state DBs, or caches.
"""

from __future__ import annotations

import argparse
import os
import shutil
import time
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_ROOT = REPO_ROOT / "local"
DEFAULT_HERMES_ROOT = Path(os.environ.get("HERMES_ROOT", Path.home() / ".hermes"))


def profile_home(name: str) -> Path:
    if name == "default":
        return DEFAULT_HERMES_ROOT
    return DEFAULT_HERMES_ROOT / "profiles" / name


def timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def backup_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.bak-local-{timestamp()}")


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def apply_overlay(profile: str, dry_run: bool) -> None:
    overlay_path = LOCAL_ROOT / "profiles" / profile / "config.overlay.yaml"
    if not overlay_path.exists():
        return

    home = profile_home(profile)
    config_path = home / "config.yaml"
    if not config_path.exists():
        print(f"skip {profile}: missing {config_path}")
        return

    current = load_yaml(config_path)
    overlay = load_yaml(overlay_path)
    merged = deep_merge(dict(current), overlay)
    if merged == current:
        print(f"config ok: {profile}")
        return

    print(f"config update: {profile} <- {overlay_path.relative_to(REPO_ROOT)}")
    if dry_run:
        return
    backup = backup_path(config_path)
    shutil.copy2(config_path, backup)
    config_path.write_text(yaml.safe_dump(merged, sort_keys=False, allow_unicode=True))
    print(f"  backup: {backup}")


def iter_skill_dirs(root: Path):
    if not root.exists():
        return
    for skill_md in sorted(root.rglob("SKILL.md")):
        if any(part in {".git", ".github", ".hub", "__pycache__"} for part in skill_md.parts):
            continue
        yield skill_md.parent


def rel_skill_dir(skill_dir: Path, root: Path) -> Path:
    return skill_dir.relative_to(root)


def ensure_symlink(link: Path, target: Path, dry_run: bool, replace_existing: bool) -> None:
    target = target.resolve()
    if link.is_symlink():
        current = link.resolve()
        if current == target:
            print(f"link ok: {link} -> {target}")
            return
        print(f"link update: {link} -> {target} (was {current})")
        if not dry_run:
            link.unlink()
            link.symlink_to(target, target_is_directory=True)
        return

    if link.exists():
        if not replace_existing:
            print(f"conflict: {link} exists and is not a symlink")
            return
        backup = Path(str(link) + f".bak-local-{timestamp()}")
        print(f"replace: {link} -> {target}")
        if not dry_run:
            shutil.move(str(link), str(backup))
            link.symlink_to(target, target_is_directory=True)
            print(f"  backup: {backup}")
        return

    print(f"link create: {link} -> {target}")
    if not dry_run:
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target, target_is_directory=True)


def apply_skill_links(profile: str, dry_run: bool, replace_existing: bool) -> None:
    home = profile_home(profile)
    skills_home = home / "skills"

    if profile == "default":
        roots = [LOCAL_ROOT / "skills"]
    else:
        roots = [
            LOCAL_ROOT / "profiles" / profile / "skills",
            LOCAL_ROOT / "skills",
        ]

    for root in roots:
        for skill_dir in iter_skill_dirs(root) or []:
            rel = rel_skill_dir(skill_dir, root)
            ensure_symlink(skills_home / rel, skill_dir, dry_run, replace_existing)


def apply_soul(profile: str, dry_run: bool, link_soul: bool) -> None:
    if not link_soul:
        return
    source = LOCAL_ROOT / "profiles" / profile / "SOUL.md"
    if not source.exists():
        return
    dest = profile_home(profile) / "SOUL.md"
    ensure_symlink(dest, source, dry_run, replace_existing=True)


def discover_profiles() -> list[str]:
    profiles_root = LOCAL_ROOT / "profiles"
    names = []
    for child in sorted(profiles_root.iterdir()):
        if child.is_dir():
            names.append(child.name)
    return names


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace-existing", action="store_true")
    parser.add_argument("--link-soul", action="store_true")
    parser.add_argument("profiles", nargs="*", help="default, boris, hashimoto, ...")
    args = parser.parse_args()

    profiles = args.profiles or discover_profiles()
    for profile in profiles:
        apply_overlay(profile, args.dry_run)
        apply_skill_links(profile, args.dry_run, args.replace_existing)
        apply_soul(profile, args.dry_run, args.link_soul)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
