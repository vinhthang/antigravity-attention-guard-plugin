---
name: git-worktree-sandbox
description: Ephemeral git worktree isolation for subagents and speculative tasks. Use when dispatching mutating subagents, testing disruptive code changes, or running long-running builds without polluting the primary working tree or risking uncommitted work.
---

# Git Worktree Sandbox Isolation

Use this skill to provision, manage, and tear down isolated working trees for subagents and speculative implementations.

---

## 1. Native `Workspace="share"` vs. Manual Git Worktree Sandboxes
- **Prefer Native Antigravity 2.0 Workspaces First**: When dispatching parallel workers via `invoke_subagent`, `run_workflow` `agent()`, or `swarm`, pass `Workspace="share"` (or `workspace="share"`) first—Antigravity provisions an isolated working copy sharing the underlying git object store automatically.
- **Use `git-worktree-sandbox` When**:
  1. **Persistent Named Sandbox Branches**: You want deterministic `.worktrees/<task-id>` directories on `sandbox/<task-id>` branches that persist across CLI scripts, manual inspection, or external tools.
  2. **Safe Speculative Discards**: If an experiment goes down an invalid path, `cleanup --delete-branch` prunes the worktree without touching uncommitted changes in the main working tree.
  3. **Controlled CLI Fast-Forward Merges**: Automating `create` -> test -> `merge --target <branch>` directly from shell/CI helpers.

---

## 2. Managing Worktrees

### Create an Isolated Sandbox
```bash
rtk python3 $(ls ~/.gemini/config/plugins/*/skills/git-worktree-sandbox/scripts/worktree_manager.py 2>/dev/null | head -n 1) create <task_id> [--repo <path>]
```
- Provisions `.worktrees/<task-id>` on a temporary branch `sandbox/<task-id>` (`--repo` is accepted either before or after the subcommand).
- Automatically ensures `.worktrees/` is recorded in `.gitignore`.

### List Active Sandboxes
```bash
rtk python3 $(ls ~/.gemini/config/plugins/*/skills/git-worktree-sandbox/scripts/worktree_manager.py 2>/dev/null | head -n 1) list [--repo <path>]
```

### Safely Discard a Sandbox (On Failure)
```bash
rtk python3 $(ls ~/.gemini/config/plugins/*/skills/git-worktree-sandbox/scripts/worktree_manager.py 2>/dev/null | head -n 1) cleanup <task_id> --delete-branch [--repo <path>]
```

### Fast-Forward Merge (On Success)
```bash
rtk python3 $(ls ~/.gemini/config/plugins/*/skills/git-worktree-sandbox/scripts/worktree_manager.py 2>/dev/null | head -n 1) merge <task_id> --target <branch> [--repo <path>]
```

---

## 3. Subagent Integration Flow

```
Primary Agent
    │
    ├── 1. Provisions Worktree: worktree_manager.py create subagent-123
    │
    ├── 2. Dispatches Subagent: Cwd=.worktrees/subagent-123
    │
    ├── 3. Subagent Executes TDD Cycle in Isolation
    │
    └── 4. On Green Pass: Merge or Cherry-Pick changes
           On Failure: Cleanup worktree with zero main-tree side effects
```

- **Feedback Loop Rule**: Run `worktree_manager.py list [--repo <path>]` after `cleanup` or `merge` to confirm no orphaned worktree or `sandbox/<task-id>` branch remains.
