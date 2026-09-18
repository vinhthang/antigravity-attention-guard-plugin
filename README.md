# Antigravity Attention Guard Plugin

> **Agent governance, attention protection, and execution sandboxing for Google Antigravity.**

**Antigravity Attention Guard** prevents **Attention Dilution**—a failure mode where a primary coding agent floods its context window with compiler errors, noisy command traces, and speculative file edits, losing high-level architectural awareness.

The plugin enforces subagent delegation, attention protection, and execution sandboxing across the agent lifecycle through native hooks, an SQLite state machine, and a command security firewall.

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
                       │      Primary Workhorse Subagents        │
                       │  - Model: flash (fast, grounded, tool)  │
                       │  - Execution, TDD diffs, rapid triage   │
                       │  - Command security firewall            │
                       └───────────────────┬─────────────────────┘
                                           │
                        Complex roadblock? │ Strict JSON Contract
                        or failure triage  ▼ (schemas/*-payload.json)
                       ┌─────────────────────────────────────────┐
                       │       Tier 1: Root Cause Diagnosis      │
                       │  - flash default (fast schema triage)   │
                       │  - pro fallback (high reasoning)        │
                       └─────────────────────────────────────────┘
```

---

## Core Capabilities

### 1. Adaptive Planning & Attention Protection
- **Adaptive Workflow**:
  - **Plan & Delegate**: Multi-step architecture features, complex refactors, and test-driven implementations author `implementation_plan.md` and pass through the Human Gate ("Proceed") before delegating execution to subagents.
  - **Direct Execution**: Quick one-offs, single-file edits, configuration tweaks, and direct user prompts can be executed directly by the Primary Agent without plan overhead.
- **Clean Context Window**: Keeps the orchestrator focused on codebase exploration, high-level requirements, planning artifacts, and workstream coordination.

### 2. Cross-Platform Sandbox & Command Security Firewall
Every terminal command run by subagents is filtered through [`command_validator.py`](scripts/command_validator.py):
- **Expanded Multi-Ecosystem Whitelist**: Supports Python, Node/JS, Rust, Go, Java, .NET, C/C++, and DevOps tools out of the box (`cargo`, `rustc`, `pnpm`, `yarn`, `bun`, `deno`, `vite`, `uv`, `poetry`, `pip`, `ruff`, `mypy`, `dotnet`, `msbuild`, `mvn`, `gradle`, `go`, `docker`, `kubectl`, `helm`, `terraform`, `tofu`, `make`, `cmake`, `ninja`, `rtk`, `git`, etc.).
- **Cross-Platform & Windows Compatibility**: Normalizes binary extensions (`.exe`, `.cmd`, `.bat`), blocks PowerShell/cmd script execution patterns (`powershell -c`, `cmd /c`), and enforces a strict `FORBIDDEN_BINARIES` list across Unix and Windows (`del`, `format`, `erase`, `rmdir`, `diskpart`, `mkfs`, `dd`, `icacls`, `takeown`, `rm`, `chmod`, `sudo`, `runas`).
- **Project-Level Whitelisting**: Allows custom binaries via `ATTENTION_GUARD_EXTRA_BINARIES` environment variable or `.attentionguard.json` project configuration.
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
Aligned with [`rules/AGENTS.md`](rules/AGENTS.md):
- **Primary Workhorse (`flash`)**: Fast, deterministic execution of approved implementation plans and rapid first-line root-cause diagnosis.
- **High-Reasoning Fallback (`pro`)**: Unshackled for deep architectural investigations, intricate algorithmic roadblocks, or multi-file refactoring when `flash` hits a wall (following sequential write discipline in `COORDINATOR.md`).
- **Tier 2 External Second-Opinion**: If diagnosis is ambiguous or fails twice (`escalation_counter >= 2`), requests secondary review (WorkBuddy AI) before amending the plan.
- **Human Gate**: After 3 escalations (`escalation_counter >= 3`), autonomous looping terminates and escalates directly to the user.

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
| `PreInvocation` | - | [`scripts/attention-refresh.py`](scripts/attention-refresh.py) | Periodically injects ephemeral workflow reminders to keep rules salient in long pairing sessions. |
| `PreToolUse` | `.*` | [`scripts/enforce-delegation.py`](scripts/enforce-delegation.py) | Unblocks Primary Agent; enforces command policy and workspace confinement on subagents. |
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
| Windows | ✅ Supported | Cross-platform binary normalization (`.exe`, `.cmd`, `.bat`) & Windows security sandbox |

---

## License

MIT
