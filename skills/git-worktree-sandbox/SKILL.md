---
name: git-worktree-sandbox
description: Ephemeral git worktree isolation for subagents and speculative tasks. Use when dispatching mutating subagents, testing disruptive code changes, or running long-running builds without polluting the primary working tree or risking uncommitted work.
---

# Git Worktree Sandbox Isolation

Use this skill to provision, manage, and tear down isolated working trees for subagents and speculative implementations.

---

## 1. Why Worktree Isolation?
1. **Zero Collision**: Subagents work on their own branch in `.worktrees/<task-id>` without touching your primary files or test cache.
2. **Safe Discards**: If a subagent fails or goes down an invalid path, the entire worktree is pruned without touching uncommitted changes in the main working tree.
3. **True Concurrency**: Enables parallel builds or test runs on different commits simultaneously.

---

## 2. Managing Worktrees

### Create an Isolated Sandbox
```bash
python3 $(ls ~/.gemini/config/plugins/*/skills/git-worktree-sandbox/scripts/worktree_manager.py 2>/dev/null | head -n 1) create <task_id> [--repo <path>]
```
- Provisions `.worktrees/<task_id>` on a temporary branch `sandbox/<task_id>`.
- Automatically ensures `.worktrees/` is recorded in `.gitignore`.

### List Active Sandboxes
```bash
python3 $(ls ~/.gemini/config/plugins/*/skills/git-worktree-sandbox/scripts/worktree_manager.py 2>/dev/null | head -n 1) list
```

### Safely Discard a Sandbox (On Failure)
```bash
python3 $(ls ~/.gemini/config/plugins/*/skills/git-worktree-sandbox/scripts/worktree_manager.py 2>/dev/null | head -n 1) cleanup <task_id> --delete-branch
```

### Fast-Forward Merge (On Success)
```bash
python3 $(ls ~/.gemini/config/plugins/*/skills/git-worktree-sandbox/scripts/worktree_manager.py 2>/dev/null | head -n 1) merge <task_id> --target <branch>
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
