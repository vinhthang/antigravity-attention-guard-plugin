# Antigravity Attention Guard Plugin (`v2.0.0` — Lean Edition)

> **Fast `O(1)` mechanical safety rails and zero-ceremony multi-agent governance for Google Antigravity 2.0.**

**Antigravity Attention Guard `v2.0.0`** protects coding sessions from destructive commands, test tampering, runaway subagent fork-bombs, polling doom-loops, and raw terminal log dumps—while getting completely out of the way of normal coding, testing, and git workflows (`0 ms` overhead on read tools, turn start, and turn stop; `< 5 ms` on mutating calls).

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Read Tools & Turn Lifecycle (0 ms)                   │
│   read_file, search, MCP, ask_question, PreInvocation, PostToolUse, Stop│
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│             PreToolUse Safety Guard (< 5 ms O(1) Fast Path)             │
│  write_file / edit_file / run_command / invoke_subagent / send_message  │
├───────────────────────────────────┬─────────────────────────────────────┤
│ Universal Rails (All Agents)      │ Subagent Rails ([ANTIGRAVITY_TOKEN])│
│ - Block destructive git / rm -rf  │ - Cap recursion (no fork-bombs)     │
│ - Block test skip / assert True   │ - 3x Doom-loop circuit breaker      │
│ - Direct code/test/git allowed    │ - Active bg-task & raw-log fence    │
└───────────────────────────────────┴──────────────────┬──────────────────┘
                                                       │
                                                       ▼
                                    ┌─────────────────────────────────────┐
                                    │   Slim SQLite Ledger (v3 Schema)    │
                                    │   tokens + events -> sync_metrics   │
                                    └─────────────────────────────────────┘
```

---

## Core Capabilities

### 1. Mechanical Safety Rails (`scripts/enforce-delegation.py`)
- **Destructive Command Guard**: Blocks `git reset --hard`, `git clean -f`, `git checkout .`, `git restore .`, unleased `git push --force`, and catastrophic `rm -rf` across all agents.
- **Test-Tampering Guard**: Blocks introducing `@pytest.mark.skip`, `pytest.skip(`, `it.skip(`, `describe.skip(`, `t.Skip(`, or vacuous `assert True` bypasses in test files.
- **Subagent Fork-Bomb Cap**: Subagents identified via `[ANTIGRAVITY_TOKEN:<uuid>]` are mechanically blocked from `run_workflow`, `swarm`, and unbounded `invoke_subagent` recursion.
- **Subagent Doom-Loop Circuit Breaker**: Halts subagents repeating identical command or process/file-polling signatures (`POLL_PROC`, `POLL_FILE`) $\ge 3$ times consecutively without an intervening file edit.
- **Background-Task & Anti-Log-Dump Fence**: Prevents subagents from calling `send_message` while background `task-*` commands are still running or dumping raw ANSI codes / multi-frame tracebacks into parent context.

### 2. Zero-Ceremony Primary Agent Autonomy
- **No Self-Lockout**: Primary Agents (Gemini 4 `Argon`/`Carbon`, Claude `Opus`, `Flash`) and native `swarm` / `run_workflow` workers execute quick fixes, 1–2 file edits, `rtk` test runs, and git operations directly—delegating via `invoke_subagent(..., Workspace="share")`, `run_workflow`, or `swarm` when work spans 3+ files, parallel slices, or noisy builds.
- **No Watchdog or Walkthrough Traps**: Zero `Stop`, `PreInvocation`, or `PostToolUse` hooks; relies natively on Antigravity 2.0 reactive wakeups, `<user_rules>`, and `<CONTEXT_SUMMARY>` compaction.
- **Model Respect**: `scripts/inject-rules.py` preserves caller `Model` choices (`flash`, `flash_lite`, `pro`, `inherit`) verbatim without silent overrides, while offloading prompts `> 12,000` chars to disk pointers via `scripts/context_boundary.py`.

### 3. Slim `O(1)` SQLite Telemetry & Surface Validation
- **Fast Header & SQLite Lookup**: `scripts/common.py::is_subagent()` resolves subagent identity via SQLite `tokens.claimed_by` or a bounded 10-line transcript header check—keeping hook latency flat even on multi-megabyte session transcripts.
- **Metrics & Dashboard Sync**: `scripts/diagnostics.py --metrics --json` and `scripts/sync_metrics.py` report `PRIMARY_TOOL_DENIED` (with `tool` and `is_sub` attribution) and `BREAKER_STATE_CHANGE` events to `attention-metrics-server`.
- **Bundle & Surface Audit**: `scripts/surface_validator.py`, `scripts/system_audit.py`, and `scripts/deploy_plugin.py` validate always-on rule budgets (`<= 8,000` chars; `v2.0.0` uses `~3,300` chars), skill triggers, and hook script paths while pruning retired artifacts on deploy.

---

## Lifecycle Hooks Reference

| Hook | Matcher | Script | Responsibility |
|---|---|---|---|
| `PreToolUse` | `run_command\|write_file\|edit_file\|...\|send_message` | [`scripts/enforce-delegation.py`](scripts/enforce-delegation.py) | Enforces destructive-command and test-tampering guards universally, plus subagent recursion, doom-loop, background-task, and anti-log-dump fences. |
| `PreToolUse` | `invoke_subagent` | [`scripts/inject-rules.py`](scripts/inject-rules.py) | Issues `[ANTIGRAVITY_TOKEN:<uuid>]`, offloads `> 12k`-char prompts to disk pointers, and appends concise role & evidence-isolation rules while preserving `Model`. |

---

## Deploying & Running Tests

```bash
# Run test & latency benchmark suite
PYTHONDONTWRITEBYTECODE=1 rtk pytest tests/

# Validate plugin surface and deploy to ~/.gemini/config/plugins/attention-guard
PYTHONDONTWRITEBYTECODE=1 rtk python3 scripts/surface_validator.py
PYTHONDONTWRITEBYTECODE=1 rtk python3 scripts/deploy_plugin.py --deploy

# Query local SQLite telemetry
PYTHONDONTWRITEBYTECODE=1 rtk python3 scripts/diagnostics.py --metrics --json
```
