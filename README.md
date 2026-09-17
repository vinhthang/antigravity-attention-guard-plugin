# Antigravity Attention Guard Plugin

> **Agent governance, attention protection, and execution sandboxing for Google Antigravity.**

**Antigravity Attention Guard** prevents **Attention Dilution**—a failure mode where a primary coding agent floods its context window with compiler errors, noisy command traces, and speculative file edits, losing high-level architectural awareness.

The plugin enforces **Ray Dalio's 5-Step Process** (Clear Goals, Problem Intolerance, Root Cause Diagnosis, Deterministic Design, Execution Accountability) across the agent lifecycle through native hooks, an SQLite state machine, and a command security firewall.

---

## Architecture Overview

```
                       ┌─────────────────────────────────────────┐
                       │       Primary Agent (Orchestrator)      │
                       │  - Strategic Planning & Architecture    │
                       │  - Planning Mode & Artifacts            │
                       └───────────────────┬─────────────────────┘
                                           │
                        Dispatches with    │ Injects Rules & Tokens
                        Antigravity Token  │ (scripts/inject-rules.py)
                                           ▼
                       ┌─────────────────────────────────────────┐
                       │          Executor Subagents             │
                       │  - Mechanical code edits (flash)        │
                       │  - Local workspace confinement          │
                       │  - Command security firewall            │
                       └───────────────────┬─────────────────────┘
                                           │
                        Fails assertion?   │ Strict JSON Contract
                                           ▼ (schemas/executor-payload.json)
                       ┌─────────────────────────────────────────┐
                       │      Tier 1: Read-Only Diagnostician    │
                       │  - Model: pro (high reasoning)          │
                       │  - Root cause vs proximate cause        │
                       └─────────────────────────────────────────┘
```

---

## Core Capabilities

### 1. Primary Agent Attention Protection
- **Role Separation**: The Primary Agent is barred from direct codebase file modification (`write_to_file`, `replace_file_content` outside artifacts).
- **Clean Context Window**: Keeps the orchestrator focused on codebase exploration, requirements, planning artifacts (`implementation_plan.md`, `task.md`), and delegation.

### 2. Subagent Sandbox & Command Security Firewall
Every terminal command run by subagents is filtered through [`command_validator.py`](scripts/command_validator.py):
- **Binary Whitelist**: Only approved binaries (`git`, `python3`, `pytest`, `npm`, `node`, `go`, `docker`, `rtk`, etc.) can execute. Raw shell interpreters (`bash`, `sh`, `eval`) and destructive tools (`rm`, `chmod`) are forbidden.
- **Operator Blocking**: Unquoted shell operators (`|`, `>`, `>>`, `;`, `&&`, `||`) are blocked to prevent chained arbitrary execution.
- **Workspace Confinement**: Commands cannot access or execute paths outside the workspace or scratch/brain directory.
- **Branch Protection**: Feature branch pushes (e.g. `git push origin feat/...`) are permitted; direct pushes to `main` or `master` are strictly rejected.
- **Zero Recursive Delegation**: Subagents cannot spawn child subagents, preventing runaway fork-bombs.

### 3. State Machine & Work Item Ledger
- **SQLite Ledger**: [`ledger.py`](scripts/ledger.py) maintains an auditable database of work items, tokens, and lifecycle events.
- **Cryptographic Handoff**: [`inject-rules.py`](scripts/inject-rules.py) issues unique `[ANTIGRAVITY_TOKEN:<uuid>]` tokens and injects role-specific constraints (`AGENTS.md`) into subagent prompts.
- **Finite State Machine**: [`fsm.py`](scripts/fsm.py) tracks turn states (`OPEN` → `HANDOFF_PENDING` → `EXECUTION_ACTIVE` → `CLOSED` or `RECOVERY_REQUIRED`).

### 4. Turn Quality Gate (Walkthrough Gate)
- [`attention-check.py`](scripts/attention-check.py) inspects turn termination:
  - If subagents performed work during a turn, the turn cannot close until a valid `walkthrough.md` artifact is created or updated.
  - Acts as an invariant refresher, reminding the Primary Agent to delegate execution.

### 5. Multi-Tier Escalation Protocol
Aligned with Ray Dalio's principles in [`rules/AGENTS.md`](rules/AGENTS.md):
- **Mechanical Execution (`flash`)**: Fast, deterministic execution of approved implementation plans.
- **Tier 1 Diagnostician (`pro`)**: On test or command failure, dispatches a **strictly read-only** `pro` subagent to isolate root cause from proximate cause. Speculative trial-and-error edits are forbidden.
- **Tier 2 External Second-Opinion**: If diagnosis is ambiguous or fails twice, requests secondary review before amending the plan.
- **Dalio Human Gate**: After 3 escalations, autonomous looping terminates and escalates directly to the user.

### 6. Telemetry & Metrics
- Local metrics dashboard accessible via CLI:
  ```bash
  rtk python3 scripts/diagnostics.py --metrics --json
  ```
- Also accessible via the built-in skill `attention-metrics`.
- Configurable background streaming to remote collectors (VictoriaMetrics / Prometheus).

---

## Lifecycle Hooks Reference

| Hook | Matcher | Script | Responsibility |
|---|---|---|---|
| `PreToolUse` | `.*` | [`scripts/enforce-delegation.py`](scripts/enforce-delegation.py) | Blocks direct codebase editing by Primary Agent; enforces command policy and workspace confinement on subagents. |
| `PreToolUse` | `invoke_subagent` | [`scripts/inject-rules.py`](scripts/inject-rules.py) | Issues tokens and injects Dalio rules and subagent contracts into prompts. |
| `PostToolUse` | `invoke_subagent` | [`scripts/record-tool-result.py`](scripts/record-tool-result.py) | Records dispatch outcome and updates state machine in SQLite ledger. |
| `Stop` | - | [`scripts/attention-check.py`](scripts/attention-check.py) | Verifies walkthrough completion, handles subagent termination, and enforces turn closure invariants. |

---

## Installation & Deployment

### Global Installation

```bash
git clone https://github.com/vinhthang/antigravity-attention-guard-plugin.git ~/.gemini/config/plugins/attention-guard
```

Or symlink your development workspace:
```bash
python3 scripts/deploy_plugin.py
```

No external runtime dependencies required. Uses Python standard library (`sqlite3`, `json`, `shlex`, `argparse`).

---

## Running Tests

Install test dependencies:
```bash
pip install -r requirements-dev.txt
```

Run test suites:
```bash
# Command validator self-tests
rtk python3 scripts/command_validator.py --test

# Full test suite
rtk pytest tests/ -v
```

---

## Platform Compatibility

| OS | Status | Notes |
|---|---|---|
| macOS | ✅ Supported | Primary development platform |
| Linux | ✅ Supported | `python3` required (standard on modern distributions) |

---

## License

MIT
