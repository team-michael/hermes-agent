#!/usr/bin/env python3
"""Commit and push safe Hermes profile state without touching upstream history."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from local_state import (
    LocalStateError,
    commit_staged_state,
    ensure_under_hermes,
    export_live_profiles,
    git,
    git_output,
    maintenance_lock,
    require_main,
    require_no_core_worktree_changes,
    require_no_staged_changes,
    stage_existing_state_files,
)


DEFAULT_REPO = Path.home() / ".hermes" / "hermes-agent"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--remote", default="team-michael")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--lock-timeout", type=float, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = ensure_under_hermes(args.repo)
    remote_ref = f"{args.remote}/{args.branch}"

    try:
        with maintenance_lock(args.lock_timeout):
            require_main(repo)
            require_no_staged_changes(repo)
            require_no_core_worktree_changes(repo)

            git(
                repo,
                "fetch",
                args.remote,
                f"{args.branch}:refs/remotes/{remote_ref}",
            )
            head_before = git_output(repo, "rev-parse", "HEAD")
            remote_before = git_output(repo, "rev-parse", remote_ref)
            if head_before != remote_before:
                raise LocalStateError(
                    f"local main and {remote_ref} differ; run update-hermes or reconcile "
                    "them before the state-only Cron"
                )

            export_live_profiles(repo, dry_run=args.dry_run)
            if args.dry_run:
                print("dry-run: no files staged, committed, or pushed")
                return 0

            staged = stage_existing_state_files(repo)
            if not staged:
                print("local state unchanged")
                return 0

            commit_staged_state(
                repo,
                subject="chore(profiles): sync local Hermes state [skip ci]",
                author_name="Andrej Karpathy",
            )

            git(
                repo,
                "fetch",
                args.remote,
                f"{args.branch}:refs/remotes/{remote_ref}",
            )
            remote_now = git_output(repo, "rev-parse", remote_ref)
            if remote_now != remote_before:
                raise LocalStateError(
                    f"{remote_ref} moved while local state was being committed; "
                    "normal push was not attempted"
                )

            git(repo, "push", args.remote, f"HEAD:{args.branch}")
            git(
                repo,
                "fetch",
                args.remote,
                f"{args.branch}:refs/remotes/{remote_ref}",
            )
            if git_output(repo, "rev-parse", "HEAD") != git_output(
                repo, "rev-parse", remote_ref
            ):
                raise LocalStateError(f"post-push verification failed for {remote_ref}")

            print(f"local state pushed: {remote_ref}")
            return 0
    except LocalStateError as exc:
        print(f"Hermes local-state sync refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
