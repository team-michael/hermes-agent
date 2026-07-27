from __future__ import annotations

import importlib.util
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[4]
MODULE_PATH = REPO_ROOT / "ignored" / "local" / "scripts" / "local_state.py"
SPEC = importlib.util.spec_from_file_location("hermes_local_state", MODULE_PATH)
assert SPEC and SPEC.loader
local_state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(local_state)

TMP_ROOT = Path.home() / ".hermes" / "tmp" / "update-hermes-tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def init_repo(path: Path) -> None:
    run_git(path, "init", "-b", "main")
    run_git(path, "config", "user.name", "Test")
    run_git(path, "config", "user.email", "test@example.com")
    (path / "README.md").write_text("base\n", encoding="utf-8")
    run_git(path, "add", "README.md")
    run_git(path, "commit", "-m", "base")
    run_git(path, "update-ref", "refs/remotes/origin/main", "HEAD")


def test_state_path_allowlist_keeps_dot_agents_prefix() -> None:
    assert local_state.is_state_path("ignored/local/profiles/a/SOUL.md")
    assert local_state.is_state_path(".agents/skills/update-hermes/SKILL.md")
    assert not local_state.is_state_path("agent/conversation_loop.py")


def test_transient_files_are_skipped_but_secrets_stop_staging() -> None:
    with tempfile.TemporaryDirectory(dir=TMP_ROOT) as raw:
        repo = Path(raw)
        init_repo(repo)
        local_root = repo / "ignored/local"
        cache = local_root / "scripts/__pycache__/helper.pyc"
        lock = local_root / "profiles/demo/memories/MEMORY.md.lock"
        secret = local_root / "profiles/demo/.env"
        cache.parent.mkdir(parents=True)
        lock.parent.mkdir(parents=True)
        cache.write_bytes(b"cache")
        lock.write_text("", encoding="utf-8")

        assert local_state.audit_unsafe_local_files(local_root) == []
        assert local_state.stage_existing_state_files(repo) == []

        secret.write_text("SECRET=value\n", encoding="utf-8")
        with pytest.raises(local_state.LocalStateError, match="unsafe runtime files"):
            local_state.stage_existing_state_files(repo)


def test_export_updates_only_curated_overlay_keys() -> None:
    with tempfile.TemporaryDirectory(dir=TMP_ROOT) as raw:
        root = Path(raw)
        repo = root / "repo"
        live_root = root / "live"
        overlay = repo / "ignored/local/profiles/demo/config.overlay.yaml"
        live_config = live_root / "profiles/demo/config.yaml"
        overlay.parent.mkdir(parents=True)
        live_config.parent.mkdir(parents=True)
        overlay.write_text(
            yaml.safe_dump({"model": {"default": "old"}, "agent": {"max_turns": 10}}),
            encoding="utf-8",
        )
        live_config.write_text(
            yaml.safe_dump(
                {
                    "model": {"default": "new", "provider": "custom"},
                    "agent": {"max_turns": 20, "untracked_default": True},
                }
            ),
            encoding="utf-8",
        )
        (live_config.parent / ".env").write_text("SECRET=value\n", encoding="utf-8")

        local_state.export_live_profiles(repo, hermes_root=live_root)

        exported = yaml.safe_load(overlay.read_text(encoding="utf-8"))
        assert exported == {"model": {"default": "new"}, "agent": {"max_turns": 20}}
        assert not (repo / "ignored/local/profiles/demo/.env").exists()


def test_staging_refuses_implicit_state_deletion() -> None:
    with tempfile.TemporaryDirectory(dir=TMP_ROOT) as raw:
        repo = Path(raw)
        init_repo(repo)
        state_file = repo / "ignored/local/shared/policy.md"
        state_file.parent.mkdir(parents=True)
        state_file.write_text("policy\n", encoding="utf-8")
        run_git(repo, "add", "-f", str(state_file.relative_to(repo)))
        run_git(repo, "commit", "-m", "state")
        state_file.unlink()

        with pytest.raises(local_state.LocalStateError, match="deletions"):
            local_state.stage_existing_state_files(repo)

        assert run_git(repo, "diff", "--cached", "--name-only") == ""


def test_core_commit_requires_manifest_declaration() -> None:
    with tempfile.TemporaryDirectory(dir=TMP_ROOT) as raw:
        repo = Path(raw)
        init_repo(repo)
        core_file = repo / "agent/example.py"
        core_file.parent.mkdir(parents=True)
        core_file.write_text("value = 1\n", encoding="utf-8")
        run_git(repo, "add", "agent/example.py")
        run_git(repo, "commit", "-m", "local core patch")

        with pytest.raises(local_state.LocalStateError, match="undeclared"):
            local_state.validate_local_commits(repo, "origin/main")

        manifest = repo / "ignored/local/core-patches.yaml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            yaml.safe_dump({"version": 1, "paths": ["agent/example.py"]}),
            encoding="utf-8",
        )
        run_git(repo, "add", "-f", str(manifest.relative_to(repo)))
        run_git(repo, "commit", "-m", "declare core patch")

        commits = local_state.validate_local_commits(repo, "origin/main")
        assert len(commits) == 2


def test_daily_script_has_no_history_rewrite_commands() -> None:
    script = (
        REPO_ROOT
        / "ignored/local/profiles/andrej/scripts/hermes_agent_daily_commit_push.sh"
    ).read_text(encoding="utf-8")
    assert "git add -A" not in script
    assert "git reset" not in script
    assert "force-with-lease" not in script
    assert "sync-local-state.py" in script
