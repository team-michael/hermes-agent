#!/usr/bin/env python3
"""Audit repo-managed local Hermes state for drift and unsafe files."""

from __future__ import annotations

import os
from pathlib import Path

import yaml


LOCAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = LOCAL_ROOT.parents[1]
DEFAULT_HERMES_ROOT = Path(os.environ.get("HERMES_ROOT", Path.home() / ".hermes"))

DENY_FILE_NAMES = {
    ".env",
    "auth.json",
    "auth.lock",
    "gateway.pid",
    "gateway.lock",
    "gateway_state.json",
    "processes.json",
    "channel_directory.json",
}
DENY_SUFFIXES = (
    ".db",
    ".db-shm",
    ".db-wal",
    ".jsonl",
    ".pid",
    ".lock",
)
DENY_DIR_NAMES = {
    "logs",
    "sessions",
    "cache",
    "checkpoints",
    "sandboxes",
    "__pycache__",
}


def profile_home(name: str) -> Path:
    if name == "default":
        return DEFAULT_HERMES_ROOT
    return DEFAULT_HERMES_ROOT / "profiles" / name


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return data if isinstance(data, dict) else {}


def iter_skill_dirs(root: Path):
    if not root.exists():
        return
    for skill_md in sorted(root.rglob("SKILL.md")):
        if "__pycache__" in skill_md.parts:
            continue
        yield skill_md.parent


def audit_unsafe_files() -> list[str]:
    issues: list[str] = []
    for path in LOCAL_ROOT.rglob("*"):
        rel = path.relative_to(REPO_ROOT)
        if any(part in DENY_DIR_NAMES for part in path.parts):
            issues.append(f"unsafe runtime dir/file under local: {rel}")
            continue
        if path.is_file():
            if path.name in DENY_FILE_NAMES or path.name.endswith(DENY_SUFFIXES):
                issues.append(f"unsafe runtime file under local: {rel}")
    return issues


def audit_profile_config(profile: str) -> list[str]:
    issues: list[str] = []
    overlay_path = LOCAL_ROOT / "profiles" / profile / "config.overlay.yaml"
    if not overlay_path.exists():
        return issues
    live_path = profile_home(profile) / "config.yaml"
    overlay = load_yaml(overlay_path)
    live = load_yaml(live_path)
    expected_dirs = ((overlay.get("skills") or {}).get("external_dirs") or [])
    live_dirs = ((live.get("skills") or {}).get("external_dirs") or [])
    for expected in expected_dirs:
        if expected not in live_dirs:
            issues.append(f"{profile}: missing skills.external_dirs entry {expected}")
    expected_branch = (overlay.get("update") or {}).get("local_patch_branch")
    live_branch = (live.get("update") or {}).get("local_patch_branch")
    if expected_branch and live_branch != expected_branch:
        issues.append(f"{profile}: update.local_patch_branch is {live_branch!r}, expected {expected_branch!r}")
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


def main() -> int:
    profiles_root = LOCAL_ROOT / "profiles"
    profiles = sorted(p.name for p in profiles_root.iterdir() if p.is_dir())
    issues = []
    issues.extend(audit_unsafe_files())
    for profile in profiles:
        issues.extend(audit_profile_config(profile))
        issues.extend(audit_profile_memories(profile))
        issues.extend(audit_skill_links(profile))

    if issues:
        print("local state audit failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("local state audit ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
