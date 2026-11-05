#!/usr/bin/env python3
"""Git Worktree Sandbox Manager - Ephemeral workspace isolation for agents & subagents.

Allows subagents to execute tests, mutations, and speculative builds without
polluting the primary working tree or risking unstashed changes.
"""
import sys
import os
import argparse
import subprocess
import shutil

def run_git(args, cwd):
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, check=True)

def ensure_gitignore(repo_path: str):
    gitignore = os.path.join(repo_path, ".gitignore")
    entry = ".worktrees/"
    if os.path.exists(gitignore):
        with open(gitignore, "r", encoding="utf-8") as f:
            content = f.read()
        if entry not in content:
            with open(gitignore, "a", encoding="utf-8") as f:
                f.write(f"\n# Ephemeral Agent Worktrees\n{entry}\n")
    else:
        with open(gitignore, "w", encoding="utf-8") as f:
            f.write(f"# Ephemeral Agent Worktrees\n{entry}\n")

def cmd_create(args):
    repo = os.path.abspath(args.repo)
    task_id = args.task_id
    worktree_dir = os.path.join(repo, ".worktrees", task_id)
    branch = f"sandbox/{task_id}"

    ensure_gitignore(repo)

    if os.path.exists(worktree_dir):
        print(f"Error: Worktree path already exists: {worktree_dir}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(worktree_dir), exist_ok=True)

    try:
        # Create worktree with a new sandbox branch
        subprocess.run(["git", "worktree", "add", "-b", branch, worktree_dir, args.base], cwd=repo, check=True)
        print(f"CREATED_WORKTREE: {worktree_dir}")
        print(f"BRANCH: {branch}")
    except subprocess.CalledProcessError as e:
        print(f"Error creating worktree: {e}", file=sys.stderr)
        sys.exit(1)

def cmd_list(args):
    repo = os.path.abspath(args.repo)
    try:
        res = run_git(["worktree", "list"], cwd=repo)
        print(res.stdout.strip())
    except Exception as e:
        print(f"Error listing worktrees: {e}", file=sys.stderr)
        sys.exit(1)

def cmd_cleanup(args):
    repo = os.path.abspath(args.repo)
    task_id = args.task_id
    worktree_dir = os.path.join(repo, ".worktrees", task_id)
    branch = f"sandbox/{task_id}"

    if os.path.exists(worktree_dir):
        try:
            subprocess.run(["git", "worktree", "remove", "--force", worktree_dir], cwd=repo, check=True)
            print(f"REMOVED_WORKTREE: {worktree_dir}")
        except subprocess.CalledProcessError:
            shutil.rmtree(worktree_dir, ignore_errors=True)
            subprocess.run(["git", "worktree", "prune"], cwd=repo)
            print(f"PRUNED_WORKTREE: {worktree_dir}")

    if args.delete_branch:
        subprocess.run(["git", "branch", "-D", branch], cwd=repo, capture_output=True)
        print(f"DELETED_BRANCH: {branch}")

def cmd_merge(args):
    repo = os.path.abspath(args.repo)
    task_id = args.task_id
    branch = f"sandbox/{task_id}"
    target = args.target

    try:
        # Checkout target and merge
        run_git(["checkout", target], cwd=repo)
        run_git(["merge", "--ff-only", branch], cwd=repo)
        print(f"MERGED: {branch} into {target}")
        args.delete_branch = True
        cmd_cleanup(args)
    except subprocess.CalledProcessError as e:
        print(f"Merge conflict or fast-forward failed: {e}", file=sys.stderr)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Git Worktree Sandbox Manager for Agents")
    parser.add_argument("--repo", default=os.getcwd(), help="Path to git repository root")
    subparsers = parser.add_subparsers(dest="action", required=True)

    p_create = subparsers.add_parser("create")
    p_create.add_argument("task_id", help="Unique identifier for the subagent or task")
    p_create.add_argument("--base", default="HEAD", help="Base branch/commit to branch from")

    p_list = subparsers.add_parser("list")

    p_cleanup = subparsers.add_parser("cleanup")
    p_cleanup.add_argument("task_id", help="Task ID of worktree to remove")
    p_cleanup.add_argument("--delete-branch", action="store_true", help="Also delete the sandbox branch")

    p_merge = subparsers.add_parser("merge")
    p_merge.add_argument("task_id", help="Task ID of worktree to merge")
    p_merge.add_argument("--target", default="HEAD", help="Target branch to merge into")

    args = parser.parse_args()
    if args.action == "create":
        cmd_create(args)
    elif args.action == "list":
        cmd_list(args)
    elif args.action == "cleanup":
        cmd_cleanup(args)
    elif args.action == "merge":
        cmd_merge(args)

if __name__ == "__main__":
    main()
