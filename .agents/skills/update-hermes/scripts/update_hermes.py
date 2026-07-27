#!/usr/bin/env python3
"""Update Hermes while preserving reviewed local state and core patches."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_REPO = Path.home() / ".hermes" / "hermes-agent"
DEFAULT_PATCH_REMOTE = "team-michael"
DEFAULT_UPSTREAM = "origin/main"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--patch-remote", default=DEFAULT_PATCH_REMOTE)
    parser.add_argument("--upstream", default=DEFAULT_UPSTREAM)
    parser.add_argument(
        "--skip-update",
        action="store_true",
        help="Skip the official `hermes update` call after a manually resolved restore.",
    )
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-patch-remote-rewrite",
        action="store_true",
        help=(
            "Allow the one-time recovery path when local main and "
            "team-michael/main already diverged. Push still uses an explicit lease."
        ),
    )
    parser.add_argument("--lock-timeout", type=float, default=600)
    return parser.parse_args()


def find_hermes(repo: Path) -> str:
    for candidate in (
        repo / "venv" / "bin" / "hermes",
        repo / ".venv" / "bin" / "hermes",
    ):
        if candidate.exists():
            return str(candidate)
    found = shutil.which("hermes")
    if found:
        return found
    raise RuntimeError("could not find hermes executable")


def install_local_state_import(repo: Path) -> None:
    scripts = repo / "ignored" / "local" / "scripts"
    if not scripts.exists():
        raise RuntimeError(f"missing local-state scripts: {scripts}")
    sys.path.insert(0, str(scripts))


def fetch_ref(repo: Path, remote: str, branch: str) -> None:
    from local_state import git

    git(
        repo,
        "fetch",
        remote,
        f"{branch}:refs/remotes/{remote}/{branch}",
    )


def sync_patch_remote(
    repo: Path,
    *,
    remote: str,
    branch: str,
    allow_rewrite: bool,
) -> str:
    """Fast-forward from the patch remote or reject unexplained divergence."""
    from local_state import LocalStateError, git, git_output

    remote_ref = f"{remote}/{branch}"
    remote_head = git_output(repo, "rev-parse", remote_ref)
    counts = git_output(
        repo,
        "rev-list",
        "--left-right",
        "--count",
        f"HEAD...{remote_ref}",
    )
    local_only, remote_only = (int(part) for part in counts.split())
    if remote_only and not local_only:
        git(repo, "merge", "--ff-only", remote_ref)
    elif local_only and remote_only and not allow_rewrite:
        raise LocalStateError(
            f"main and {remote_ref} diverged ({local_only} local, "
            f"{remote_only} remote); refusing an automatic rewrite"
        )
    return remote_head


def create_backup_ref(repo: Path) -> str:
    from local_state import git, git_output

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_ref = f"refs/hermes-local-backups/update-{stamp}"
    git(repo, "update-ref", backup_ref, git_output(repo, "rev-parse", "HEAD"))
    print(f"local patch backup: {backup_ref}")
    return backup_ref


def restore_local_commits(
    repo: Path,
    *,
    backup_ref: str,
    commits: list[str],
) -> None:
    from local_state import LocalStateError, git, git_output

    if git(
        repo,
        "merge-base",
        "--is-ancestor",
        backup_ref,
        "HEAD",
        check=False,
    ).returncode == 0:
        print("local patches remained on main; no restore needed")
        return
    if not commits:
        print("no local-only commits need restoration")
        return

    if git_output(repo, "diff", "--name-only", "--diff-filter=U"):
        raise LocalStateError(
            "unmerged files exist before local patch restoration; resolve them first"
        )

    print(f"restoring {len(commits)} reviewed local commit(s) on main")
    for commit in commits:
        result = git(
            repo,
            "cherry-pick",
            "--empty=drop",
            commit,
            check=False,
        )
        if result.returncode != 0:
            details = (result.stdout + "\n" + result.stderr).strip()
            raise LocalStateError(
                "local patch restore stopped on a conflict.\n"
                "Keep main checked out, prefer origin/main where upstream has the "
                "same behavior, resolve the conflict, run `git cherry-pick --continue`, "
                "then rerun update-hermes with --skip-update.\n"
                + details
            )


def apply_and_audit(repo: Path) -> None:
    from local_state import run_checked

    apply_script = repo / "ignored" / "local" / "scripts" / "apply-local-state.py"
    audit_script = repo / "ignored" / "local" / "scripts" / "audit-local-state.py"
    run_checked(
        ["python3", str(apply_script), "--replace-existing", "--link-soul"],
        cwd=repo,
    )
    run_checked(["python3", str(audit_script)], cwd=repo)


def run_manifest_tests(repo: Path) -> None:
    from local_state import load_core_patch_manifest, run_checked

    _, commands = load_core_patch_manifest(repo)
    for command in commands:
        expanded = [
            str(repo / part[7:]) if part.startswith("{repo}/") else part
            for part in command
        ]
        run_checked(expanded, cwd=repo)


def push_with_lease(
    repo: Path,
    *,
    remote: str,
    branch: str,
    expected_remote_head: str,
) -> None:
    from local_state import LocalStateError, git, git_output

    fetch_ref(repo, remote, branch)
    actual = git_output(repo, "rev-parse", f"{remote}/{branch}")
    if actual != expected_remote_head:
        raise LocalStateError(
            f"{remote}/{branch} moved from {expected_remote_head[:12]} to "
            f"{actual[:12]}; force-with-lease push was not attempted"
        )
    git(
        repo,
        "push",
        f"--force-with-lease=refs/heads/{branch}:{expected_remote_head}",
        remote,
        f"HEAD:{branch}",
    )
    fetch_ref(repo, remote, branch)
    if git_output(repo, "rev-parse", "HEAD") != git_output(
        repo, "rev-parse", f"{remote}/{branch}"
    ):
        raise LocalStateError(f"post-push verification failed for {remote}/{branch}")


def main() -> int:
    args = parse_args()
    repo = args.repo.expanduser().resolve()
    install_local_state_import(repo)

    from local_state import (
        LocalStateError,
        commit_staged_state,
        ensure_under_hermes,
        export_live_profiles,
        git,
        git_output,
        local_only_commits,
        maintenance_lock,
        require_main,
        require_no_core_worktree_changes,
        require_no_staged_changes,
        stage_existing_state_files,
        validate_local_commits,
    )

    repo = ensure_under_hermes(repo)
    branch = "main"
    update_error: subprocess.CalledProcessError | None = None

    try:
        with maintenance_lock(args.lock_timeout):
            require_main(repo)
            require_no_staged_changes(repo)
            require_no_core_worktree_changes(repo)

            fetch_ref(repo, "origin", "main")
            fetch_ref(repo, args.patch_remote, branch)
            expected_remote_head = sync_patch_remote(
                repo,
                remote=args.patch_remote,
                branch=branch,
                allow_rewrite=args.allow_patch_remote_rewrite,
            )

            export_live_profiles(repo, dry_run=args.dry_run)
            if args.dry_run:
                validate_local_commits(repo, args.upstream)
                print("dry-run: update, commit, profile apply, and push skipped")
                return 0

            stage_existing_state_files(repo)
            commit_staged_state(
                repo,
                subject="chore(profiles): preserve local Hermes state [skip ci]",
            )
            commits = validate_local_commits(repo, args.upstream)
            backup_ref = create_backup_ref(repo)

            if args.skip_update:
                print("official hermes update skipped")
            else:
                hermes = find_hermes(repo)
                try:
                    subprocess.run(
                        [hermes, "update", "--yes"],
                        cwd=repo,
                        check=True,
                        env=os.environ.copy(),
                    )
                except subprocess.CalledProcessError as exc:
                    update_error = exc

                require_main(repo)
                restore_local_commits(
                    repo,
                    backup_ref=backup_ref,
                    commits=commits,
                )
                if update_error is not None:
                    raise update_error

            fetch_ref(repo, "origin", "main")
            if git(
                repo,
                "merge-base",
                "--is-ancestor",
                "origin/main",
                "HEAD",
                check=False,
            ).returncode != 0:
                raise LocalStateError("origin/main is not an ancestor of updated main")

            validate_local_commits(repo, args.upstream)
            apply_and_audit(repo)
            run_manifest_tests(repo)
            require_no_staged_changes(repo)
            require_no_core_worktree_changes(repo)

            if args.no_push:
                print("push skipped")
            else:
                push_with_lease(
                    repo,
                    remote=args.patch_remote,
                    branch=branch,
                    expected_remote_head=expected_remote_head,
                )

            print(
                "update-hermes completed: "
                f"main={git_output(repo, 'rev-parse', '--short', 'HEAD')}"
            )
            return 0
    except (LocalStateError, RuntimeError) as exc:
        print(f"update-hermes refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
