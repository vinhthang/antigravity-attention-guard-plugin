# Antigravity Attention Guard Plugin

> A deterministic lifecycle plugin for [Google Antigravity](https://antigravity.google) that prevents Attention Dilution in long-running AI agent sessions.

**Keywords**: antigravity, antigravity-plugin, google-antigravity, ai-agent, attention-dilution, context-window, llm-governance, agent-delegation, subagent, lifecycle-hooks, rtk, token-optimization

## Features

| Hook | Script | Purpose |
|---|---|---|
| PreToolUse | `enforce-delegation.py` | Blocks Primary Agent from code modification, shell execution, and MCP write tools. Forces delegation to Flash subagents. |
| PreToolUse | `rtk-enforcer.py` | Auto-prepends `rtk` to subagent commands for 60-95% output token compression. Gracefully skips if RTK is not installed. |
| PreInvocation | `attention-guard.py` | Monitors session duration and injects planning reminders after configurable timeout (default: 120s). |
| Stop | `attention-check.py` | Verifies agent output quality. Forces re-reading of all project and global rules if the agent forgets to summarize its work. Max 3 retries to prevent infinite loops. |

## Installation

```bash
git clone https://github.com/vinhthang/antigravity-attention-guard-plugin.git ~/.gemini/config/plugins/attention-guard
```

No dependencies required. Python 3.6+ only (uses stdlib).

## Updating

```bash
cd ~/.gemini/config/plugins/attention-guard && git pull
```

Antigravity instantly applies updates without restart.

## How It Works

### Agent Delegation Protocol

The plugin enforces a strict two-phase lifecycle:

1. **Phase 1 (Primary Agent)**: High-level reasoning, planning, and artifact creation only. No direct code changes.
2. **Phase 2 (Subagents)**: Spawned with `Model: "flash"` to execute code changes, run commands, and validate checks.

### Dynamic MCP Write Tool Discovery

The plugin automatically scans `~/.gemini/antigravity/mcp/` to discover installed MCP servers and their write tools. Any MCP tool starting with a mutating verb (`create`, `write`, `edit`, `push`, `delete`, `move`, `fork`, `update`, etc.) is automatically blocked for the Primary Agent. Results are cached for 5 minutes.

### RTK Auto-Enforcement

If [RTK (Rust Token Killer)](https://github.com/vinhthang/rtk) is installed, the plugin automatically prepends `rtk` to subagent commands to compress output by 60-95%. Simple commands (`echo`, `mkdir`, `cp`, `chmod`) and already-prefixed commands are skipped.

## Subagent Detection Limitation

The Antigravity hook payload only exposes `modelName` for agent identification. There is no `isSubagent` field in the official hook contract.

- Subagents **MUST** be spawned with `Model: "flash"` for detection to work.
- Subagents spawned with `Model: "inherit"` or `Model: "pro"` will be incorrectly blocked.
- This is a platform limitation, not a plugin bug.

## Running Tests

```bash
pytest tests/ -v
```

## Compatibility

- **Platforms**: macOS, Linux, Windows (Python 3.6+)
- **Primary Agent Models**: Gemini, Claude, GPT (any model without "flash" in the name)
- **Subagent Models**: Any model with "flash" in the name (e.g., `gemini-3.7-flash-tiered`)
- **RTK**: Optional. Plugin works without RTK installed.

## License

MIT

