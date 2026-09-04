# Antigravity Attention Guard Plugin

> A deterministic lifecycle plugin for [Google Antigravity](https://antigravity.google) that prevents Attention Dilution in long-running AI agent sessions, enforcing strict agent safety, optimal LLM context window management, and robust subagent orchestration for complex agentic workflows.

**Keywords**: Google Antigravity plugins, LLM context window management, agent safety, agentic workflows, subagent orchestration, antigravity, antigravity-plugin, ai-agent, attention-dilution, context-window, llm-governance, agent-delegation, subagent, lifecycle-hooks, rtk, token-optimization

## Features

| Hook | Script | Purpose |
|---|---|---|
| PreToolUse | `enforce-delegation.py` | Blocks Primary Agent from code modification, shell execution, and MCP write tools. Forces delegation to subagents. |
| PreToolUse | `rtk-enforcer.py` | Auto-prepends `rtk` to subagent commands for 60-95% output Context Hygiene. Gracefully skips if RTK is not installed. |
| PreToolUse | `inject-rules.py` | Dynamically injects robust subagent detection markers and liveness tracking rules into subagent prompts. |
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

The plugin enforces a strict two-phase lifecycle for safe agentic workflows:

1. **Phase 1 (Primary Agent)**: High-level reasoning, planning, and artifact creation only. No direct code changes.
2. **Phase 2 (Subagents)**: Spawned to execute code changes, run commands, and validate checks.

Thanks to deterministic transcript markers injected into the subagents' prompts, **any** subagent model (`flash`, `pro`, `flash_lite`, `inherit`, etc.) is now fully supported.

### RTK Auto-Enforcement

If [RTK (Rust Token Killer)](https://github.com/vinhthang/rtk) is installed, the plugin automatically prepends `rtk` to subagent commands to compress output by 60-95%. The intelligent regex accurately detects tool commands and prepends `rtk` correctly even when environment variables are prepended (e.g., `FOO=bar cargo build` becomes `FOO=bar rtk cargo build`). Simple commands (`echo`, `mkdir`, `cp`, `chmod`) and already-prefixed commands are skipped.

### Liveness Tracking

The plugin enforces a **mandatory 5-minute liveness tracking rule** for all subagents via injected prompt instructions (`AGENTS.md`) rather than a hard runtime block. This ensures the Primary Agent sets a liveness timer when spawning subagents, preventing the Primary Agent from sleeping indefinitely if a subagent hangs.

## Running Tests

```bash
pytest tests/ -v
```

## Compatibility

- **Platforms**: macOS, Linux, Windows (Python 3.6+)
- **Primary Agent Models**: Any model (e.g., Gemini, Claude, GPT)
- **Subagent Models**: **ALL** subagent models are supported (`flash`, `pro`, `inherit`, etc.)
- **RTK**: Optional. Plugin works without RTK installed.

## Platform Compatibility

| OS | Status | Notes |
|---|---|---|
| macOS | ✅ Supported | Primary development platform |
| Linux | ✅ Supported | `python3` required (standard on modern distros) |
| Windows | ⚠️ Manual Setup | Replace `/usr/bin/env python3` with `python` in `hooks.json` |

## License

MIT
