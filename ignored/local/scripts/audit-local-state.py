#!/usr/bin/env python3
"""Audit repo-managed local Hermes state for drift and unsafe files."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from local_state import HERMES_ROOT, audit_unsafe_local_files


LOCAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = LOCAL_ROOT.parents[1]
DEFAULT_HERMES_ROOT = HERMES_ROOT
SOUL_INCLUDE_RE = re.compile(
    r"<!--\s*hermes-include:\s*(?P<path>[^>]+?)\s*-->",
    flags=re.IGNORECASE,
)

def profile_home(name: str) -> Path:
    if name == "default":
        return DEFAULT_HERMES_ROOT
    return DEFAULT_HERMES_ROOT / "profiles" / name


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def iter_skill_dirs(root: Path):
    if not root.exists():
        return
    for skill_md in sorted(root.rglob("SKILL.md")):
        if "__pycache__" in skill_md.parts:
            continue
        yield skill_md.parent


def audit_unsafe_files() -> list[str]:
    return [
        "unsafe runtime file under local: "
        + str(Path(path).relative_to(REPO_ROOT))
        for path in audit_unsafe_local_files(LOCAL_ROOT)
    ]


def audit_profile_config(profile: str) -> list[str]:
    issues: list[str] = []
    overlay_path = LOCAL_ROOT / "profiles" / profile / "config.overlay.yaml"
    if not overlay_path.exists():
        return issues
    live_path = profile_home(profile) / "config.yaml"
    overlay = load_yaml(overlay_path)
    live = load_yaml(live_path)

    def compare(expected: Any, actual: Any, key_path: str) -> None:
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                issues.append(
                    f"{profile}: config {key_path or '<root>'} is "
                    f"{type(actual).__name__}, expected mapping"
                )
                return
            for key, value in expected.items():
                child_path = f"{key_path}.{key}" if key_path else str(key)
                if key not in actual:
                    issues.append(f"{profile}: missing config key {child_path}")
                    continue
                compare(value, actual[key], child_path)
            return
        if expected != actual:
            issues.append(
                f"{profile}: config drift at {key_path}: "
                f"{actual!r}, expected {expected!r}"
            )

    compare(overlay, live, "")
    return issues


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


def audit_profile_memories(profile: str) -> list[str]:
    issues: list[str] = []
    repo_profile = LOCAL_ROOT / "profiles" / profile
    live_memories = profile_home(profile) / "memories"
    for source in iter_memory_files(repo_profile) or []:
        live = live_memories / source.name
        if not live.exists():
            issues.append(f"{profile}: missing memory file {live}")
            continue
        if live.read_bytes() != source.read_bytes():
            issues.append(f"{profile}: memory drift in {live}")
    return issues


def audit_skill_links(profile: str) -> list[str]:
    issues: list[str] = []
    home = profile_home(profile)
    roots = [LOCAL_ROOT / "skills"] if profile == "default" else [
        LOCAL_ROOT / "profiles" / profile / "skills",
        LOCAL_ROOT / "skills",
    ]
    for root in roots:
        for skill_dir in iter_skill_dirs(root) or []:
            rel = skill_dir.relative_to(root)
            link = home / "skills" / rel
            if not link.is_symlink():
                issues.append(f"{profile}: {link} is not a symlink")
                continue
            if link.resolve() != skill_dir.resolve():
                issues.append(f"{profile}: {link} points to {link.resolve()}, expected {skill_dir.resolve()}")
    return issues


def render_repo_soul(source: Path) -> str:
    source_text = source.read_text(encoding="utf-8")

    def replace_include(match: re.Match[str]) -> str:
        requested = Path(os.path.expanduser(match.group("path").strip()))
        candidate = LOCAL_ROOT / "shared" / requested.name
        if not candidate.exists():
            raise FileNotFoundError(
                f"SOUL include {requested} has no repo-managed source at {candidate}"
            )
        return candidate.read_text(encoding="utf-8").strip()

    return SOUL_INCLUDE_RE.sub(replace_include, source_text)


def audit_soul(profile: str) -> list[str]:
    issues: list[str] = []
    source = LOCAL_ROOT / "profiles" / profile / "SOUL.md"
    if not source.exists():
        return issues
    live = profile_home(profile) / "SOUL.md"
    if not live.exists():
        return [f"{profile}: missing SOUL.md at {live}"]

    source_text = source.read_text(encoding="utf-8")
    if SOUL_INCLUDE_RE.search(source_text):
        expected = render_repo_soul(source).encode("utf-8")
        if live.read_bytes() != expected:
            issues.append(f"{profile}: materialized SOUL.md drift in {live}")
        return issues

    if not live.is_symlink():
        issues.append(f"{profile}: {live} is not a symlink")
    elif live.resolve() != source.resolve():
        issues.append(
            f"{profile}: {live} points to {live.resolve()}, expected {source.resolve()}"
        )
    return issues


def audit_profile_scripts(profile: str) -> list[str]:
    issues: list[str] = []
    source_root = LOCAL_ROOT / "profiles" / profile / "scripts"
    if not source_root.exists():
        return issues
    destination_root = profile_home(profile) / "scripts"
    for source in sorted(source_root.rglob("*")):
        if not source.is_file() or source.is_symlink():
            continue
        if "__pycache__" in source.parts or source.suffix == ".pyc":
            continue
        destination = destination_root / source.relative_to(source_root)
        if not destination.exists():
            issues.append(f"{profile}: missing managed script {destination}")
        elif destination.read_bytes() != source.read_bytes():
            issues.append(f"{profile}: managed script drift in {destination}")
    return issues


def main() -> int:
    profiles_root = LOCAL_ROOT / "profiles"
    profiles = sorted(p.name for p in profiles_root.iterdir() if p.is_dir())
    issues = []
    issues.extend(audit_unsafe_files())
    for profile in profiles:
        issues.extend(audit_profile_config(profile))
        issues.extend(audit_profile_memories(profile))
        issues.extend(audit_skill_links(profile))
        issues.extend(audit_soul(profile))
        issues.extend(audit_profile_scripts(profile))

    if issues:
        print("local state audit failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("local state audit ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
