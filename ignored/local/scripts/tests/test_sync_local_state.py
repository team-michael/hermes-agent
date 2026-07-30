from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


SYNC_SCRIPT = Path(__file__).resolve().parents[1] / "sync-local-state.py"


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
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


def test_sync_commits_state_without_absorbing_unstaged_core_changes(tmp_path: Path) -> None:
    hermes_root = tmp_path / ".hermes"
    repo = hermes_root / "hermes-agent"
    remote = hermes_root / "remote.git"
    repo.mkdir(parents=True)

    run(["git", "init", "--bare", str(remote)])
    run(["git", "init", "-b", "main"], cwd=repo)
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.com")

    core = repo / "core.py"
    state = repo / "ignored/local/profiles/test/memories/MEMORY.md"
    state.parent.mkdir(parents=True)
    core.write_text("committed core\n", encoding="utf-8")
    state.write_text("old memory\n", encoding="utf-8")
    git(repo, "add", "core.py", "ignored/local/profiles/test/memories/MEMORY.md")
    git(repo, "commit", "-m", "initial")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-u", "origin", "main")

    live_memory = hermes_root / "profiles/test/memories/MEMORY.md"
    live_memory.parent.mkdir(parents=True)
    live_memory.write_text("new memory\n", encoding="utf-8")
    core.write_text("uncommitted core work\n", encoding="utf-8")

    env = {**os.environ, "HERMES_ROOT": str(hermes_root)}
    result = subprocess.run(
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

    assert result.returncode == 0, result.stderr
    assert core.read_text(encoding="utf-8") == "uncommitted core work\n"
    assert git(repo, "show", "HEAD:core.py") == "committed core"
    assert git(repo, "show", "HEAD:ignored/local/profiles/test/memories/MEMORY.md") == "new memory"
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "origin/main")
    assert git(repo, "status", "--short", "--", "core.py") == "M core.py"
