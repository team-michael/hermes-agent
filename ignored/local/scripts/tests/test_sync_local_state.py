from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


SYNC_SCRIPT = Path(__file__).resolve().parents[1] / "sync-local-state.py"
STATE_MEMORY = "ignored/local/profiles/test/memories/MEMORY.md"
STATE_USER = "ignored/local/profiles/test/memories/USER.md"


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )


def git(repo: Path, *args: str) -> str:
    return run(["git", *args], cwd=repo).stdout.strip()


def initialize_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    hermes_root = tmp_path / ".hermes"
    repo = hermes_root / "hermes-agent"
    remote = hermes_root / "remote.git"
    repo.mkdir(parents=True)

    run(["git", "init", "--bare", str(remote)])
    run(["git", "init", "-b", "main"], cwd=repo)
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.com")

    core = repo / "core.py"
    state = repo / STATE_MEMORY
    state.parent.mkdir(parents=True)
    core.write_text("committed core\n", encoding="utf-8")
    state.write_text("old memory\n", encoding="utf-8")
    git(repo, "add", "core.py", STATE_MEMORY)
    git(repo, "commit", "-m", "initial")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-u", "origin", "main")
    return hermes_root, repo, remote


def run_sync(hermes_root: Path, repo: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HERMES_ROOT": str(hermes_root)}
    return subprocess.run(
        [
            sys.executable,
            str(SYNC_SCRIPT),
            "--repo",
            str(repo),
            "--remote",
            "origin",
            "--branch",
            "main",
        ],
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )


def test_sync_commits_state_without_absorbing_unstaged_core_changes(
    tmp_path: Path,
) -> None:
    hermes_root, repo, _ = initialize_repo(tmp_path)
    core = repo / "core.py"
    live_memory = hermes_root / "profiles/test/memories/MEMORY.md"
    live_memory.parent.mkdir(parents=True)
    live_memory.write_text("new memory\n", encoding="utf-8")
    core.write_text("uncommitted core work\n", encoding="utf-8")

    result = run_sync(hermes_root, repo)

    assert result.returncode == 0, result.stderr
    assert core.read_text(encoding="utf-8") == "uncommitted core work\n"
    assert git(repo, "show", "HEAD:core.py") == "committed core"
    assert git(repo, "show", f"HEAD:{STATE_MEMORY}") == "new memory"
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "origin/main")
    assert git(repo, "status", "--short", "--", "core.py") == "M core.py"


def test_sync_accepts_pre_staged_state_changes(tmp_path: Path) -> None:
    hermes_root, repo, _ = initialize_repo(tmp_path)
    soul = repo / "ignored/local/profiles/steve/SOUL.md"
    soul.parent.mkdir(parents=True)
    soul.write_text("# Steve\n", encoding="utf-8")
    git(repo, "add", "-f", "ignored/local/profiles/steve/SOUL.md")

    result = run_sync(hermes_root, repo)

    assert result.returncode == 0, result.stderr
    assert git(repo, "show", "HEAD:ignored/local/profiles/steve/SOUL.md") == "# Steve"
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "origin/main")
    assert git(repo, "diff", "--cached", "--name-only") == ""


def test_sync_refuses_pre_staged_core_changes(tmp_path: Path) -> None:
    hermes_root, repo, _ = initialize_repo(tmp_path)
    core = repo / "core.py"
    core.write_text("staged core work\n", encoding="utf-8")
    git(repo, "add", "core.py")
    remote_before = git(repo, "rev-parse", "origin/main")

    result = run_sync(hermes_root, repo)

    assert result.returncode == 2
    assert "pre-existing staged core/source changes" in result.stderr
    assert "core.py" in result.stderr
    assert git(repo, "rev-parse", "origin/main") == remote_before


def test_sync_leaves_unstaged_state_deletions_for_review(tmp_path: Path) -> None:
    hermes_root, repo, _ = initialize_repo(tmp_path)
    (repo / STATE_MEMORY).unlink()
    user = repo / STATE_USER
    user.write_text("new user memory\n", encoding="utf-8")

    result = run_sync(hermes_root, repo)

    assert result.returncode == 0, result.stderr
    assert git(repo, "show", f"HEAD:{STATE_MEMORY}") == "old memory"
    assert git(repo, "show", f"HEAD:{STATE_USER}") == "new user memory"
    assert git(repo, "status", "--short", "--", STATE_MEMORY) == f"D {STATE_MEMORY}"
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "origin/main")


def test_sync_refuses_pre_staged_state_deletions(tmp_path: Path) -> None:
    hermes_root, repo, _ = initialize_repo(tmp_path)
    (repo / STATE_MEMORY).unlink()
    git(repo, "add", "-u", "--", STATE_MEMORY)
    remote_before = git(repo, "rev-parse", "origin/main")

    result = run_sync(hermes_root, repo)

    assert result.returncode == 2
    assert "state deletions require explicit review" in result.stderr
    assert STATE_MEMORY in result.stderr
    assert git(repo, "rev-parse", "origin/main") == remote_before
