# Antigravity Attention Guard Plugin

Prevents Attention Dilution in long-running AI agent sessions by enforcing strict delegation, time-based guards, and output verification.

## Installation

```bash
git clone https://github.com/vinhthang/antigravity-attention-guard-plugin.git ~/.gemini/config/plugins/attention-guard
```

## Updating

```bash
cd ~/.gemini/config/plugins/attention-guard && git pull
```

## Features

- **PreToolUse Hook** (`enforce-delegation.py`): Blocks the Primary Agent from directly executing code or modifying files. Forces delegation to Flash subagents.
- **PreInvocation Hook** (`attention-guard.py`): Monitors session duration and injects planning reminders after a configurable timeout (default: 120s).
- **Stop Hook** (`attention-check.py`): Verifies agent output quality. If the agent forgets to summarize its work, it is forced to re-read all project and global instructions to reset its context window. Includes a retry limit (max 3) to prevent infinite rejection loops.

## Important: Subagent Detection Limitation

The Antigravity hook payload only exposes the `modelName` field for agent identification. There is no `isSubagent` or `parentConversationId` field in the [official hook contract](https://github.com/google/antigravity).

This means:
- **Subagents MUST always be spawned with `Model: "flash"`** so their `modelName` contains `"flash"` and they are correctly identified as worker agents.
- Subagents spawned with `Model: "inherit"` or `Model: "pro"` will have the same `modelName` as the Primary Agent and will be **incorrectly blocked** by the PreToolUse hook.
- This is a platform limitation, not a plugin bug. If Antigravity adds structured subagent metadata in the future, the plugin can be updated to use it.

## Cross-Platform Support

All hook scripts are written in Python for cross-platform compatibility. Temp files use `tempfile.gettempdir()` for OS-agnostic path resolution.

## Running Tests

```bash
cd ~/.gemini/config/plugins/attention-guard
pytest tests/ -v
```
