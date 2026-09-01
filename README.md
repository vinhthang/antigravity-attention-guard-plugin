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

- **PreToolUse Hook**: Blocks the Primary Agent from directly executing code or modifying files. Forces delegation to Flash subagents.
- **PreInvocation Hook**: Monitors session duration and injects planning reminders after a configurable timeout (default: 120s).
- **Stop Hook**: Verifies agent output quality. If the agent forgets to summarize its work, it is forced to re-read all project and global instructions to reset its context window.
