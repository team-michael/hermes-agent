#!/usr/bin/env python3
"""Shared safety primitives for repo-managed Hermes local state."""

from __future__ import annotations

import copy
import fcntl
import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

import yaml


HERMES_ROOT = Path(os.environ.get("HERMES_ROOT", Path.home() / ".hermes"))
LOCK_PATH = HERMES_ROOT / "locks" / "hermes-main-maintenance.lock"
STATE_PREFIXES = ("ignored/local/", ".agents/skills/")
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
    ".pyc",
)
DENY_DIR_NAMES = {
    ".git",
    ".hub",
    "__pycache__",
    "cache",
    "checkpoints",
    "logs",
    "sandboxes",
    "sessions",
}


class LocalStateError(RuntimeError):
    """Raised when an operation would cross a local-state safety boundary."""


def ensure_under_hermes(path: Path) -> Path:
    root = HERMES_ROOT.expanduser().resolve()
    resolved = path.expanduser().resolve()
    if resolved != root and root not in resolved.parents:
        raise LocalStateError(f"refusing to manage path outside ~/.hermes: {resolved}")
    return resolved


def git(
    repo: Path,
    *args: str,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        text=True,
        capture_output=True,
        env=env,
    )


def git_output(repo: Path, *args: str) -> str:
    return git(repo, *args).stdout.strip()


@contextmanager
def maintenance_lock(timeout: float = 0) -> Iterator[None]:
    """Serialize update and daily-state jobs across all Hermes profiles."""
    ensure_under_hermes(LOCK_PATH)
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+", encoding="utf-8") as handle:
        deadline = time.monotonic() + max(timeout, 0)
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LocalStateError(
                        f"Hermes main maintenance is already running ({LOCK_PATH})"
                    )
                time.sleep(0.25)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def normalize_repo_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def is_state_path(path: str) -> bool:
    normalized = normalize_repo_path(path)
    return any(normalized.startswith(prefix) for prefix in STATE_PREFIXES)


def require_main(repo: Path) -> None:
    branch = git_output(repo, "branch", "--show-current")
    if branch != "main":
        raise LocalStateError(f"expected main branch, found {branch or '<detached>'}")


def staged_paths(repo: Path) -> list[str]:
    output = git_output(repo, "diff", "--cached", "--name-only", "--diff-filter=ACDMRTUXB")
    return [line for line in output.splitlines() if line]


def tracked_worktree_paths(repo: Path) -> list[str]:
    output = git_output(repo, "diff", "--name-only", "--diff-filter=ACDMRTUXB")
    return [line for line in output.splitlines() if line]


def untracked_paths(repo: Path) -> list[str]:
    output = git_output(repo, "ls-files", "--others", "--exclude-standard")
    return [line for line in output.splitlines() if line]


def require_no_staged_changes(repo: Path) -> None:
    paths = staged_paths(repo)
    if paths:
        formatted = "\n".join(f"  - {path}" for path in paths)
        raise LocalStateError(
            "refusing to absorb pre-existing staged changes:\n" + formatted
        )


def require_no_core_worktree_changes(repo: Path) -> None:
    paths = tracked_worktree_paths(repo) + untracked_paths(repo)
    core_paths = sorted({path for path in paths if not is_state_path(path)})
    if core_paths:
        formatted = "\n".join(f"  - {path}" for path in core_paths)
        raise LocalStateError(
            "core/source changes are present; local-state automation will not stage them:\n"
            + formatted
        )


def is_unsafe_local_path(path: Path, local_root: Path) -> bool:
    try:
        relative = path.relative_to(local_root)
    except ValueError:
        return True
    if any(part in DENY_DIR_NAMES for part in relative.parts):
        return True
    return path.name in DENY_FILE_NAMES or path.name.endswith(DENY_SUFFIXES)


def audit_unsafe_local_files(local_root: Path) -> list[str]:
    issues: list[str] = []
    if not local_root.exists():
        return issues
    for path in local_root.rglob("*"):
        if is_unsafe_local_path(path, local_root):
            issues.append(str(path))
    return issues


def copy_if_changed(source: Path, destination: Path, *, dry_run: bool) -> bool:
    ensure_under_hermes(source)
    ensure_under_hermes(destination)
    if destination.exists() and destination.is_file():
        if destination.read_bytes() == source.read_bytes():
            return False
    if not dry_run:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    print(f"state export: {source} -> {destination}")
    return True


def _project_overlay_values(template: Any, live: Any) -> Any:
    """Update only keys already curated in an existing config overlay."""
    if not isinstance(template, dict) or not isinstance(live, dict):
        return copy.deepcopy(live if live is not None else template)
    projected: dict[str, Any] = {}
    for key, template_value in template.items():
        if key not in live:
            projected[key] = copy.deepcopy(template_value)
            continue
        live_value = live[key]
        if isinstance(template_value, dict) and isinstance(live_value, dict):
            projected[key] = _project_overlay_values(template_value, live_value)
        else:
            projected[key] = copy.deepcopy(live_value)
    return projected


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise LocalStateError(f"{path} must contain a YAML mapping")
    return data


def _write_yaml_if_changed(path: Path, data: dict[str, Any], *, dry_run: bool) -> bool:
    if path.exists() and _load_yaml(path) == data:
        return False
    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(f"state export: config -> {path}")
    return True


def _iter_memory_files(memories: Path) -> Iterator[Path]:
    if not memories.exists():
        return
    for source in sorted(memories.iterdir()):
        if source.is_file() and source.suffix == ".md" and not source.name.endswith(".lock"):
            yield source


def _copy_real_skill_dirs(
    live_skills: Path,
    repo_skills: Path,
    *,
    local_root: Path,
    dry_run: bool,
) -> list[Path]:
    """Update skills already owned by local state, skipping installed bundles."""
    changed: list[Path] = []
    if not live_skills.exists():
        return changed

    for current, dir_names, file_names in os.walk(live_skills, followlinks=False):
        current_path = Path(current)
        dir_names[:] = [
            name
            for name in dir_names
            if name not in DENY_DIR_NAMES and not (current_path / name).is_symlink()
        ]
        if "SKILL.md" not in file_names:
            continue
        if current_path.is_symlink():
            continue
        relative = current_path.relative_to(live_skills)
        destination = repo_skills / relative
        if not destination.is_dir():
            continue
        resolved = current_path.resolve()
        if resolved == local_root or local_root in resolved.parents:
            continue

        for source in sorted(current_path.rglob("*")):
            if not source.is_file() or source.is_symlink():
                continue
            source_relative = source.relative_to(current_path)
            if any(part in DENY_DIR_NAMES for part in source_relative.parts):
                continue
            if source.name.endswith(DENY_SUFFIXES) or source.name in DENY_FILE_NAMES:
                continue
            target = destination / source_relative
            if copy_if_changed(source, target, dry_run=dry_run):
                changed.append(target)
    return changed


def export_live_profiles(
    repo: Path,
    *,
    hermes_root: Path | None = None,
    dry_run: bool = False,
) -> list[Path]:
    """Export safe profile state without copying credentials or runtime data."""
    root = ensure_under_hermes(hermes_root or HERMES_ROOT)
    local_root = repo / "ignored" / "local"
    local_profiles = local_root / "profiles"
    live_profiles = root / "profiles"
    changed: list[Path] = []
    if not live_profiles.exists():
        return changed

    for live_profile in sorted(path for path in live_profiles.iterdir() if path.is_dir()):
        name = live_profile.name
        if not name or name.startswith("."):
            continue
        destination = local_profiles / name

        live_soul = live_profile / "SOUL.md"
        repo_soul = destination / "SOUL.md"
        repo_soul_has_include = (
            repo_soul.exists()
            and "hermes-include:" in repo_soul.read_text(encoding="utf-8")
        )
        if (
            live_soul.exists()
            and not live_soul.is_symlink()
            and not repo_soul_has_include
            and copy_if_changed(live_soul, repo_soul, dry_run=dry_run)
        ):
            changed.append(repo_soul)

        live_config = live_profile / "config.yaml"
        repo_overlay = destination / "config.overlay.yaml"
        if live_config.exists():
            live_data = _load_yaml(live_config)
            if repo_overlay.exists():
                overlay = _load_yaml(repo_overlay)
                projected = _project_overlay_values(overlay, live_data)
            else:
                projected = live_data
            if _write_yaml_if_changed(repo_overlay, projected, dry_run=dry_run):
                changed.append(repo_overlay)

        for source in _iter_memory_files(live_profile / "memories"):
            target = destination / "memories" / source.name
            if copy_if_changed(source, target, dry_run=dry_run):
                changed.append(target)

        changed.extend(
            _copy_real_skill_dirs(
                live_profile / "skills",
                destination / "skills",
                local_root=local_root,
                dry_run=dry_run,
            )
        )
    return changed


def iter_state_files(repo: Path) -> Iterator[Path]:
    local_root = repo / "ignored" / "local"
    roots = (local_root, repo / ".agents" / "skills")
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            if root == local_root and is_unsafe_local_path(path, local_root):
                continue
            if any(part in DENY_DIR_NAMES for part in path.relative_to(root).parts):
                continue
            if path.name.endswith(DENY_SUFFIXES):
                continue
            yield path


def stage_existing_state_files(repo: Path) -> list[str]:
    """Stage existing safe files only; missing files are never staged as deletions."""
    unsafe = audit_unsafe_local_files(repo / "ignored" / "local")
    if unsafe:
        formatted = "\n".join(f"  - {path}" for path in unsafe)
        raise LocalStateError("unsafe runtime files found under ignored/local:\n" + formatted)

    files = [str(path.relative_to(repo)) for path in iter_state_files(repo)]
    for start in range(0, len(files), 200):
        git(repo, "add", "-f", "--", *files[start : start + 200])

    deleted = git_output(
        repo,
        "diff",
        "--name-only",
        "--diff-filter=D",
    ).splitlines()
    deleted.extend(
        git_output(
            repo,
            "diff",
            "--cached",
            "--name-only",
            "--diff-filter=D",
        ).splitlines()
    )
    deleted_state = sorted({path for path in deleted if path and is_state_path(path)})
    if deleted_state:
        formatted = "\n".join(f"  - {path}" for path in deleted_state)
        raise LocalStateError(
            "state deletions require explicit review and were not staged:\n" + formatted
        )

    staged = staged_paths(repo)
    core = [path for path in staged if not is_state_path(path)]
    if core:
        formatted = "\n".join(f"  - {path}" for path in core)
        raise LocalStateError("refusing to stage core/source paths:\n" + formatted)
    return staged


def load_core_patch_manifest(repo: Path) -> tuple[set[str], list[list[str]]]:
    path = repo / "ignored" / "local" / "core-patches.yaml"
    if not path.exists():
        return set(), []
    data = _load_yaml(path)
    paths = {
        normalize_repo_path(str(item))
        for item in data.get("paths", [])
        if str(item).strip()
    }
    commands: list[list[str]] = []
    for command in data.get("test_commands", []):
        if isinstance(command, list) and command:
            commands.append([str(part) for part in command])
    return paths, commands


def local_only_commits(repo: Path, upstream: str) -> list[str]:
    output = git_output(
        repo,
        "rev-list",
        "--reverse",
        "--right-only",
        "--cherry-pick",
        f"{upstream}...HEAD",
    )
    return [line for line in output.splitlines() if line]


def validate_local_commits(repo: Path, upstream: str) -> list[str]:
    """Reject local commits that carry undeclared Hermes core changes."""
    manifest_paths, _ = load_core_patch_manifest(repo)
    allowed_core = set(manifest_paths)
    commits = local_only_commits(repo, upstream)
    violations: list[str] = []
    for commit in commits:
        output = git_output(
            repo,
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "-r",
            commit,
        )
        for path in output.splitlines():
            normalized = normalize_repo_path(path)
            if is_state_path(normalized) or normalized in allowed_core:
                continue
            violations.append(f"{commit[:12]} {normalized}")

    if violations:
        formatted = "\n".join(f"  - {item}" for item in violations)
        raise LocalStateError(
            "local commits contain undeclared core/source changes:\n"
            + formatted
            + "\nDeclare reviewed core paths in ignored/local/core-patches.yaml."
        )
    return commits


def commit_staged_state(
    repo: Path,
    *,
    subject: str,
    author_name: str = "Hermes Local State",
    author_email: str = "team@greyboxhq.com",
) -> str | None:
    if git(repo, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return None
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": author_name,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_COMMITTER_NAME": author_name,
        "GIT_COMMITTER_EMAIL": author_email,
    }
    git(repo, "commit", "-m", subject, env=env)
    return git_output(repo, "rev-parse", "HEAD")


def run_checked(
    command: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> None:
    print("+", " ".join(command))
    subprocess.run(list(command), cwd=cwd, check=True, env=env)
