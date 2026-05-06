#!/usr/bin/env python3
"""Update Hermes while preserving the local patch branch and profile state."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence


DEFAULT_REPO = Path.home() / ".hermes" / "hermes-agent"
DEFAULT_WORKTREE_ROOT = Path.home() / ".hermes" / "worktrees"
DEFAULT_PATCH_BRANCH = "local/hermes-patches"
DEFAULT_PATCH_REMOTE = "team-michael"
DEFAULT_UPSTREAM = "origin/main"


class Runner:
    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run

    def run(
        self,
        cmd: Sequence[str | os.PathLike[str]],
        cwd: Path,
        *,
        check: bool = True,
        capture: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        printable = " ".join(str(part) for part in cmd)
        print(f"+ ({cwd}) {printable}")
        if self.dry_run:
            return subprocess.CompletedProcess([str(part) for part in cmd], 0, "", "")
        return subprocess.run(
            [str(part) for part in cmd],
            cwd=str(cwd),
            check=check,
            text=True,
            capture_output=capture,
        )

    def output(self, cmd: Sequence[str | os.PathLike[str]], cwd: Path) -> str:
        printable = " ".join(str(part) for part in cmd)
        print(f"+ ({cwd}) {printable}")
        return subprocess.run(
            [str(part) for part in cmd],
            cwd=str(cwd),
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()


def fail(message: str) -> None:
    raise SystemExit(message)


def ensure_under_hermes(path: Path) -> None:
    hermes_root = (Path.home() / ".hermes").resolve()
    resolved = path.resolve()
    if resolved != hermes_root and hermes_root not in resolved.parents:
        fail(f"Refusing to manage path outside ~/.hermes: {resolved}")


def git(runner: Runner, repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return runner.run(["git", *args], repo, check=check)


def git_output(runner: Runner, repo: Path, *args: str) -> str:
    return runner.output(["git", *args], repo)


def require_clean_main(runner: Runner, repo: Path) -> None:
    branch = git_output(runner, repo, "branch", "--show-current")
    if branch != "main":
        fail(f"Expected primary checkout to be on main, found {branch!r}")
    status = git_output(runner, repo, "status", "--porcelain")
    if status:
        fail("Primary checkout is not clean; commit, stash, or remove unrelated changes first.")


def find_hermes(repo: Path) -> str:
    for candidate in (repo / ".venv" / "bin" / "hermes", repo / "venv" / "bin" / "hermes"):
        if candidate.exists():
            return str(candidate)
    found = shutil.which("hermes")
    if found:
        return found
    fail("Could not find hermes executable in .venv, venv, or PATH.")


def branch_exists(runner: Runner, repo: Path, branch: str) -> bool:
    if runner.dry_run:
        return True
    result = runner.run(["git", "rev-parse", "--verify", "--quiet", branch], repo, check=False)
    return result.returncode == 0


def ensure_patch_branch(runner: Runner, repo: Path, branch: str, remote: str) -> None:
    if branch_exists(runner, repo, branch):
        return
    remote_ref = f"{remote}/{branch}"
    git(runner, repo, "branch", "--track", branch, remote_ref)


def sync_patch_branch_from_remote(runner: Runner, repo: Path, branch: str, remote: str) -> None:
    remote_ref = f"{remote}/{branch}"
    if not branch_exists(runner, repo, branch):
        ensure_patch_branch(runner, repo, branch, remote)
        return
    counts = git_output(runner, repo, "rev-list", "--left-right", "--count", f"{branch}...{remote_ref}")
    left, right = (int(part) for part in counts.split())
    if left and right:
        fail(f"{branch} and {remote_ref} have diverged; inspect before updating.")
    if right:
        git(runner, repo, "branch", "-f", branch, remote_ref)


def make_worktree(runner: Runner, repo: Path, root: Path, branch: str) -> Path:
    ensure_under_hermes(root)
    worktree = root / f"update-hermes-{int(time.time())}"
    if not runner.dry_run:
        root.mkdir(parents=True, exist_ok=True)
    git(runner, repo, "worktree", "add", str(worktree), branch)
    return worktree


def remove_worktree(runner: Runner, repo: Path, worktree: Path) -> None:
    ensure_under_hermes(worktree)
    git(runner, repo, "worktree", "remove", str(worktree))


def iter_profile_memory_files(memories_dir: Path):
    if not memories_dir.exists():
        return
    for source in sorted(memories_dir.iterdir()):
        if not source.is_file():
            continue
        if source.name.endswith(".lock") or source.suffix != ".md":
            continue
        yield source


def copy_if_changed(source: Path, dest: Path, dry_run: bool) -> bool:
    ensure_under_hermes(source)
    ensure_under_hermes(dest)
    if dest.exists() and dest.read_bytes() == source.read_bytes():
        return False
    print(f"memory sync: {source} -> {dest}")
    if not dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    return True


def sync_profile_memories_to_patch_worktree(runner: Runner, worktree: Path) -> None:
    """Copy live profile memories into ignored/local and commit changes.

    Only Markdown memory files are managed. Runtime lock files are deliberately
    excluded.
    """
    local_profiles = worktree / "ignored" / "local" / "profiles"
    if not local_profiles.exists():
        return

    changed: list[Path] = []
    live_profiles_root = Path.home() / ".hermes" / "profiles"
    for profile_dir in sorted(path for path in local_profiles.iterdir() if path.is_dir()):
        live_memories = live_profiles_root / profile_dir.name / "memories"
        repo_memories = profile_dir / "memories"
        for source in iter_profile_memory_files(live_memories) or []:
            dest = repo_memories / source.name
            if copy_if_changed(source, dest, runner.dry_run):
                changed.append(dest)

    if not changed:
        print("profile memories ok: no changes to commit")
        return
    if runner.dry_run:
        print("dry-run: skipping profile memory commit")
        return

    rel_paths = [str(path.relative_to(worktree)) for path in changed]
    git(runner, worktree, "add", "-f", *rel_paths)
    diff = git(runner, worktree, "diff", "--cached", "--quiet", check=False)
    if diff.returncode == 0:
        print("profile memories ok: copied files match committed state")
        return
    git(runner, worktree, "commit", "-m", "chore(profiles): sync profile memories")


def rebase_patch_branch(
    runner: Runner,
    repo: Path,
    worktree: Path,
    upstream: str,
    remote: str,
    branch: str,
    push: bool,
) -> None:
    try:
        git(runner, worktree, "rebase", upstream)
    except subprocess.CalledProcessError as exc:
        print()
        print("Patch branch rebase stopped with conflicts.")
        print(f"Resolve conflicts in: {worktree}")
        print("Prefer origin/main for upstream Hermes changes, keep only local-only ignored/local assets.")
        print("After resolving, run `git rebase --continue` there, then rerun this script with --skip-update.")
        raise SystemExit(exc.returncode) from exc

    sync_profile_memories_to_patch_worktree(runner, worktree)

    if push:
        git(runner, worktree, "push", "--force-with-lease", remote, f"{branch}:{branch}")
    else:
        print("Skipping push because --no-push was set.")


def materialize_local_state(runner: Runner, repo: Path, branch: str) -> None:
    git(runner, repo, "restore", f"--source={branch}", "--worktree", "--", "ignored/local")


def link_file(target: Path, source: Path, *, dry_run: bool = False) -> None:
    ensure_under_hermes(target)
    ensure_under_hermes(source)
    if not source.exists():
        return
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() and target.resolve() == source.resolve():
        print(f"shared link ok: {target} -> {source}")
        return
    if target.exists() or target.is_symlink():
        backup = target.with_name(f"{target.name}.bak-local-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}")
        if target.is_symlink():
            if dry_run:
                print(f"would unlink shared symlink: {target}")
            else:
                target.unlink()
        else:
            if dry_run:
                print(f"would backup shared file: {target} -> {backup}")
            else:
                shutil.move(str(target), str(backup))
            print(f"shared backup: {backup}")
    if not dry_run:
        target.symlink_to(source)
    print(f"shared link: {target} -> {source}")


def sync_local_state(runner: Runner, repo: Path) -> None:
    apply_script = repo / "ignored" / "local" / "scripts" / "apply-local-state.py"
    audit_script = repo / "ignored" / "local" / "scripts" / "audit-local-state.py"
    if not apply_script.exists():
        fail(f"Missing local state apply script: {apply_script}")
    runner.run(["python3", apply_script, "--replace-existing", "--link-soul"], repo)

    local_root = repo / "ignored" / "local"
    hermes_root = Path.home() / ".hermes"
    link_file(
        hermes_root / "shared" / "terminal-command-discipline.md",
        local_root / "shared" / "terminal-command-discipline.md",
        dry_run=runner.dry_run,
    )
    link_file(
        hermes_root / "bin" / "hermes-github-api",
        local_root / "shared" / "bin" / "hermes-github-api",
        dry_run=runner.dry_run,
    )

    if not audit_script.exists():
        fail(f"Missing local state audit script: {audit_script}")
    runner.run(["python3", audit_script], repo)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--patch-branch", default=DEFAULT_PATCH_BRANCH)
    parser.add_argument("--patch-remote", default=DEFAULT_PATCH_REMOTE)
    parser.add_argument("--upstream", default=DEFAULT_UPSTREAM)
    parser.add_argument("--worktree-root", type=Path, default=DEFAULT_WORKTREE_ROOT)
    parser.add_argument("--skip-update", action="store_true", help="Skip `hermes update`; useful after resolving rebase conflicts.")
    parser.add_argument("--no-push", action="store_true", help="Do not push the patch branch.")
    parser.add_argument("--keep-worktree", action="store_true", help="Leave the temporary patch worktree after success.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo.expanduser().resolve()
    ensure_under_hermes(repo)
    ensure_under_hermes(args.worktree_root.expanduser())

    runner = Runner(dry_run=args.dry_run)
    require_clean_main(runner, repo)

    git(runner, repo, "fetch", "origin", "main")
    git(
        runner,
        repo,
        "fetch",
        args.patch_remote,
        f"{args.patch_branch}:refs/remotes/{args.patch_remote}/{args.patch_branch}",
    )
    sync_patch_branch_from_remote(runner, repo, args.patch_branch, args.patch_remote)

    if not args.skip_update:
        hermes = find_hermes(repo)
        runner.run([hermes, "update"], repo)
        require_clean_main(runner, repo)
        git(runner, repo, "fetch", "origin", "main")
    else:
        print("Skipping hermes update because --skip-update was set.")

    worktree = make_worktree(runner, repo, args.worktree_root.expanduser(), args.patch_branch)
    completed = False
    try:
        rebase_patch_branch(
            runner,
            repo,
            worktree,
            args.upstream,
            args.patch_remote,
            args.patch_branch,
            push=not args.no_push,
        )
        completed = True
    finally:
        if completed and not args.keep_worktree:
            remove_worktree(runner, repo, worktree)

    materialize_local_state(runner, repo, args.patch_branch)
    sync_local_state(runner, repo)
    require_clean_main(runner, repo)
    print("update-hermes completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
