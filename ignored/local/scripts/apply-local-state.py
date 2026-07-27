#!/usr/bin/env python3
"""Apply repo-managed local Hermes profile state.

This script intentionally manages only safe, explicit assets:
- config overlays
- non-lock profile memory Markdown files
- skill directory symlinks
- optional SOUL.md symlinks

It never copies .env, auth.json, sessions, logs, state DBs, or caches.
"""

from __future__ import annotations

import argparse
import copy
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

import yaml


LOCAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = LOCAL_ROOT.parents[1]
DEFAULT_HERMES_ROOT = Path(os.environ.get("HERMES_ROOT", Path.home() / ".hermes"))
SOUL_INCLUDE_RE = re.compile(
    r"<!--\s*hermes-include:\s*(?P<path>[^>]+?)\s*-->",
    flags=re.IGNORECASE,
)


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
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
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
    merged = deep_merge(copy.deepcopy(current), overlay)
    if merged == current:
        print(f"config ok: {profile}")
        return

    print(f"config update: {profile} <- {overlay_path.relative_to(REPO_ROOT)}")
    if dry_run:
        return
    backup = backup_path(config_path)
    shutil.copy2(config_path, backup)
    config_path.write_text(
        yaml.safe_dump(merged, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"  backup: {backup}")


def iter_memory_files(root: Path):
    memories = root / "memories"
    if not memories.exists():
        return
    for source in sorted(memories.iterdir()):
        if not source.is_file():
            continue
        if source.name.endswith(".lock") or source.suffix != ".md":
            continue
        yield source


def apply_memories(profile: str, dry_run: bool) -> None:
    source_root = LOCAL_ROOT / "profiles" / profile
    dest_root = profile_home(profile) / "memories"

    for source in iter_memory_files(source_root) or []:
        dest = dest_root / source.name
        if dest.exists() and dest.read_bytes() == source.read_bytes():
            print(f"memory ok: {profile}/{source.name}")
            continue

        print(f"memory update: {profile}/{source.name} <- {source.relative_to(REPO_ROOT)}")
        if dry_run:
            continue
        dest_root.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            backup = backup_path(dest)
            shutil.copy2(dest, backup)
            print(f"  backup: {backup}")
        shutil.copy2(source, dest)


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
    source_text = source.read_text(encoding="utf-8")

    def replace_include(match: re.Match[str]) -> str:
        requested = Path(os.path.expanduser(match.group("path").strip()))
        shared_root = LOCAL_ROOT / "shared"
        candidate = shared_root / requested.name
        if not candidate.exists():
            raise FileNotFoundError(
                f"SOUL include {requested} has no repo-managed source at {candidate}"
            )
        return candidate.read_text(encoding="utf-8").strip()

    rendered = SOUL_INCLUDE_RE.sub(replace_include, source_text)
    if rendered == source_text:
        ensure_symlink(dest, source, dry_run, replace_existing=True)
        return

    rendered_bytes = rendered.encode("utf-8")
    if dest.exists() and not dest.is_symlink() and dest.read_bytes() == rendered_bytes:
        print(f"soul ok: {profile}")
        return

    print(f"soul materialize: {profile} <- {source.relative_to(REPO_ROOT)}")
    if dry_run:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink():
        dest.unlink()
    elif dest.exists():
        backup = backup_path(dest)
        shutil.copy2(dest, backup)
        print(f"  backup: {backup}")
    dest.write_bytes(rendered_bytes)


def apply_profile_scripts(profile: str, dry_run: bool) -> None:
    source_root = LOCAL_ROOT / "profiles" / profile / "scripts"
    if not source_root.exists():
        return
    destination_root = profile_home(profile) / "scripts"
    for source in sorted(source_root.rglob("*")):
        if not source.is_file() or source.is_symlink():
            continue
        if "__pycache__" in source.parts or source.suffix == ".pyc":
            continue
        destination = destination_root / source.relative_to(source_root)
        if (
            destination.exists()
            and not destination.is_symlink()
            and destination.read_bytes() == source.read_bytes()
        ):
            print(f"script ok: {profile}/{source.relative_to(source_root)}")
            continue
        print(
            f"script update: {profile}/{source.relative_to(source_root)} "
            f"<- {source.relative_to(REPO_ROOT)}"
        )
        if dry_run:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink():
            destination.unlink()
        elif destination.exists():
            backup = backup_path(destination)
            shutil.copy2(destination, backup)
            print(f"  backup: {backup}")
        shutil.copy2(source, destination)


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
        if not (LOCAL_ROOT / "profiles" / profile).is_dir():
            print(f"skip {profile}: no repo-managed profile at ignored/local/profiles/{profile}")
            continue
        apply_overlay(profile, args.dry_run)
        apply_memories(profile, args.dry_run)
        apply_skill_links(profile, args.dry_run, args.replace_existing)
        apply_soul(profile, args.dry_run, args.link_soul)
        apply_profile_scripts(profile, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
