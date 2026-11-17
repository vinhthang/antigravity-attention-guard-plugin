# Antigravity Attention Guard Plugin

> **Agent governance, attention protection, and multi-agent orchestration for Google Antigravity 2.0 and Gemini 4.**

**Antigravity Attention Guard** prevents **Attention Dilution**—a failure mode where a primary coding agent floods its context window with compiler errors, noisy command traces, and speculative file edits, losing high-level architectural awareness.

The plugin enforces tiered delegation across `invoke_subagent`, `run_workflow`, and native `swarm`, protects Gemini 4 (`Argon` / `Carbon`) and Claude `Opus` thinking orchestrators, and validates structured execution contracts through native lifecycle hooks and an SQLite state machine.

---

## Architecture Overview

```
                     ┌───────────────────────────────────────────────────┐
                     │     Primary Agent (Gemini 4 Argon/Carbon, Opus)   │
                     │   - Strategic Planning, Architecture & Specs      │
                     │   - Direct Markdown (*.md) & Brain Artifacts      │
                     └─────────────────────────┬─────────────────────────┘
                                               │
              ┌────────────────────────────────┼────────────────────────────────┐
              │ 1-2 Bounded Tasks              │ 3+ Disjoint Tasks / Pipelines  │ Peer Collaboration
              ▼                                ▼                                ▼
┌───────────────────────────┐    ┌───────────────────────────┐    ┌───────────────────────────┐
│ invoke_subagent (flat)    │    │ run_workflow (Python)     │    │ Native swarm (Board)      │
│ - Model: flash / pro      │    │ - parallel / pipeline     │    │ - workspace: "share" auth │
│ - Workspace: inherit|share│    │ - workspace: "share"      │    │ - workspace: "inherit" ver│
│ - Token & JSON contract   │    │ - JSON finish schema      │    │ - Zero-cost swarm_wait    │
└─────────────┬─────────────┘    └─────────────┬─────────────┘    └─────────────┬─────────────┘
              └────────────────────────────────┼────────────────────────────────┘
                                               ▼
                     ┌───────────────────────────────────────────────────┐
                     │     Safety & Turn Quality Gates (Pre/Post/Stop)   │
                     │   - Destructive cmd, test-tamper & doom-loop      │
                     │   - 300s async watchdog & walkthrough.md gate     │
                     └───────────────────────────────────────────────────┘
```

---

## Core Capabilities

### 1. Context Protection & Thinking-Model Governance
- **Clean Orchestrator Window**: Keeps Gemini 4 (`Argon` / `Carbon`) and Claude `Opus` focused on codebase grounding, specification design, planning artifacts, and multi-agent coordination.
- **Adaptive Workflow**:
  - **Plan & Delegate**: Multi-step features and refactors author `implementation_plan.md` and pass through the Human Approval Gate ("Proceed") before dispatching execution workers.
  - **Direct Documentation**: The Primary Agent freely authors all Markdown files (`*.md`) and Brain Artifacts without delegation blocks.
  - **Native Worker Recognition (`REQ-039`)**: `is_native_worker()` and automatic `swarm(action="add")` brief tagging (`[AGY_SWARM_WORKER]` / leaf `[AGY_SWARM_HELPER]`) allow Antigravity 2.0 `swarm` authors (which inherit Gemini 4 by contract) and `run_workflow` `agent()` workers (using `model="flash"` or a leading `[AGY_WORKFLOW_WORKER]` prompt prefix when inheriting Gemini 4, or host `workflowId`/`isWorkflowAgent` metadata) to edit code and run tests freely while keeping destructive-command, test-tampering, and doom-loop guards active.

### 2. Three-Surface Multi-Agent Orchestration (Antigravity 2.0)
- **Flat `invoke_subagent` (`Workspace="inherit|share|branch"`)**: Issue multiple concurrent flat `invoke_subagent` calls in a single turn with `Workspace="share"` when tasks have disjoint write-sets; serialize overlapping files on `Workspace="inherit"`.
- **Code-Driven `run_workflow`**: Fan out over 3+ disjoint slices or staged pipelines using `phase`, `parallel`, `pipeline`, and `agent(..., workspace="share", model="flash", schema=...)` (prefixing `[AGY_WORKFLOW_WORKER]` on prompts that intentionally inherit a thinking model).
- **Native `swarm` (`/teamwork`)**: Coordinate peer authors (`workspace="share"`) and `@verifier` workers (`workspace="inherit"`) on a shared board with `#seq` references and zero-cost `swarm_wait`.
- **Bounded Delegation Depth (`REQ-007`, `REQ-039`, `REQ-040`)**: `invoke_subagent` subagents are mechanically blocked from `invoke_subagent` (beyond depth 1), `manage_subagents`, `run_workflow`, and `swarm`; native workers are blocked from `invoke_subagent`, `manage_subagents`, and `run_workflow`, and native `swarm(action="add")` helpers are bounded to a single helper tier (`[AGY_SWARM_HELPER]`).

### 3. Structured JSON Data Contracts
- `invoke_subagent` workers return machine-verifiable JSON payloads validated by [`scripts/payload_validator.py`](scripts/payload_validator.py) against Draft-07 schemas in [`schemas/`](schemas/), and `send_message` handoffs enforce valid JSON dictionaries (`REQ-033`).
- **Dynamic Summary Depth**: Summaries scale naturally to task complexity while `validate_no_raw_log_dump()` (`REQ-012`) blocks raw ANSI codes, deep tracebacks, and unformatted `pytest` session dumps.

### 4. Liveness Watchdogs & Turn Quality Gate
- **300s Async Watchdog (`REQ-028`, `REQ-040`)**: [`scripts/attention-check.py`](scripts/attention-check.py) verifies that active `invoke_subagent` workers, backgrounded `run_workflow` tasks, and non-daemon `run_command` tasks have an armed `schedule(DurationSeconds=300, TimerCondition="any")` timer before turn stop (without mis-matching sibling `IsDaemon=true` daemons).
- **Walkthrough Freshness Gate (`REQ-013`)**: Verifies `walkthrough.md` `mtime` against the current turn's `work_items` before closing completed subagent turns, with a bounded human-escalation bypass.

### 5. Model-Aware Context Telemetry & Pre-Compaction Checkpoints (`REQ-011`, `REQ-038`)
- [`scripts/common.py`](scripts/common.py) (`resolve_context_budget`) automatically calibrates context budgets by model family—`1,000k` budget / `400k` checkpoint threshold for Gemini 4 (`Argon` / `Carbon`) and Gemini 3 1M-window models, `200k` / `140k` for Claude models, and configurable `AGY_TOKEN_BUDGET` / `AGY_CHECKPOINT_THRESHOLD` overrides—resetting active character counts cleanly across `CHECKPOINT`, `COMPACTION`, and `<CONTEXT_SUMMARY>` boundaries.

### 6. Mechanical Safety & Surface Validation
- **Test-Tampering & Destructive Command Guards (`REQ-008`, `REQ-010`)**: Blocks `@pytest.mark.skip`, `pytest.skip(`, `assert True`, `git reset --hard`, `git clean -f`, `git checkout .`, `git restore .`, unleased `git push --force`, and catastrophic `rm -rf`.
- **Subagent Doom-Loop Circuit Breaker (`REQ-009`, `REQ-030`)**: Halts workers repeating identical process/file polling commands $\ge 3$ times consecutively without an intervening file edit.
- **Plugin Surface & Ecosystem Audit (`REQ-015`, `REQ-034`)**: [`scripts/surface_validator.py`](scripts/surface_validator.py) and [`scripts/system_audit.py`](scripts/system_audit.py) enforce the `8,000`-character always-on budget, skill routing triggers, portable paths, hook script existence, and SQLite ledger health (`~/.gemini/antigravity/attention_guard.db`).

---

## Modularity & Companion Plugins

- **`spec-driven-plugin` (`v3.x`)**: Five-document specification workflow (`docs/specs/<feature-id>/{spec,decisions,design,tasks,verification}.md`), disjoint `- Files:` task partitioning for parallel workspaces, Antigravity 2.0 orchestration guide (`references/antigravity.md`), and read-only CLI linter (`validate_specs.py`) with zero lifecycle hooks.
- **`ai-review-plugin`**: Multi-engine adversarial peer reviews across specifications, designs, and code diffs.
- **`antigravity-attention-guard-plugin` (`v1.1.0`)**: Execution delegation, context-window protection, mechanical safety guards, and worker lifecycle telemetry.

---

## Lifecycle Hooks Reference

| Hook | Matcher | Script | Responsibility |
|---|---|---|---|
| `PreInvocation` | - | [`scripts/attention-refresh.py`](scripts/attention-refresh.py) | Injects periodic Primary Agent rule reminders, model-aware context telemetry, and pre-compaction `session_checkpoint.md` snapshots (suppressed inside subagents and native workers). |
| `PreToolUse` | `.*` | [`scripts/enforce-delegation.py`](scripts/enforce-delegation.py) | Enforces destructive-command, test-tampering, and doom-loop guards; delegates code/tests under thinking models while exempting recognized native `swarm`/`run_workflow` workers; blocks subagent recursion across `invoke_subagent`, `run_workflow`, and `swarm`. |
| `PreToolUse` | `invoke_subagent\|swarm` | [`scripts/inject-rules.py`](scripts/inject-rules.py) | Issues `[ANTIGRAVITY_TOKEN:...]` + role templates and coerces `inherit` to `flash` for `invoke_subagent`; appends `[AGY_SWARM_WORKER]` to `swarm(action="add")` author briefs. |
| `PostToolUse` | `invoke_subagent\|send_message` | [`scripts/record-tool-result.py`](scripts/record-tool-result.py) | Records tool character volume and `HANDOFF_ACCEPTED` / `HANDOFF_FAILED` transitions in SQLite ledger. |
| `Stop` | - | [`scripts/attention-check.py`](scripts/attention-check.py) | Enforces 300s async watchdog timers and turn-scoped `walkthrough.md` freshness with bounded human-escalation bypass. |

---

## Deploying & Running Tests

```bash
# Run unit & integration test suite
rtk pytest tests/

# Sync repository changes to live ~/.gemini/config/plugins/attention-guard
rtk python3 scripts/deploy_plugin.py --deploy

# Run full ecosystem & SQLite ledger audit
rtk python3 scripts/system_audit.py
```

---

## License

MIT
