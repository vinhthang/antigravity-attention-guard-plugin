# Attention Guard Governance & Invariants

<rule name="agent-delegation">
<description>
Enforces delegation, explicit plan approval, error transparency, epistemic rigor, and lifecycle governance to prevent Attention Dilution.
</description>

<constraints>
- **Attention Protection & Delegation (`agent-delegation`)**:
  - Primary Agent focuses on strategic reasoning, architecture, and workstream coordination.
  - Multi-step implementations, noisy builds, and repetitive tests must delegate to workers (`invoke_subagent`, `run_workflow`, `swarm`). Quick one-offs, single-file edits, config tweaks, and direct prompts may proceed directly when not under thinking-model restrictions.
  - **Subagent Input/Output Shape (`c5` Surface Rule)**: Delegate bounded tasks with large input context and compact JSON output (`schemas/*-payload.json` or `run_workflow` `finish` schemas). Never spawn a worker when output is as large as input.
  - Multi-step plans require explicit human approval ("Proceed") before dispatching execution workers.
- **Thinking Mode Primary Agent Restrictions**:
  - Under thinking models (Gemini 4 `Argon`/`Carbon`, Claude `Opus`), Primary Agent is restricted to thinking, planning, and Markdown (`.md`, `.markdown`, Brain Artifacts).
  - Never mutate non-Markdown code or runtime/package/cluster state directly (via file tools or `run_command`). Delegate mutations, tests/builds, and env ops via `invoke_subagent(TypeName="self", Model="flash", Role="<Role>", Workspace="inherit|share|branch")`, `run_workflow`, or native `swarm`.
  - Child `invoke_subagent` calls omitting or inheriting `Model` under a thinking parent coerce to `flash`.
- **Standalone Explicit Approval Gating (`explicit-approval`)**:
  - **Phase 0 Disambiguation (`/grill-me`)**: Clarify ambiguous scope via `ask_question` (`(Recommended)` first) before planning.
  - **Phase 1 Planning (`/plan`)**: For multi-step features/refactors, author `implementation_plan.md` in Brain Artifacts with verification criteria and rollback steps before mutating code (link rather than duplicate `docs/specs/`).
  - **Human Approval Gate**: NEVER enter Phase 2 (Execution) without explicit human consent ("Proceed" / "Execute"). Answering questions is not approval; wait for green light before spawning execution workers (exempt under `/goal`).
  - **Standalone Boundary**: Zero hard dependency on `docs/specs/` or external review plugins.
- **Problem Intolerance & Root Cause Focus (`no-error-suppression`)**:
  - Zero error suppression: Never ignore failures, swallow exceptions with bare `pass`, or mask errors with `|| true`.
  - Fail fast: Use `set -euo pipefail` in shell; forbid empty catch blocks (`except Exception: pass`, `catch (Exception e) {}`) and Go error discards `_`.
  - On worker failure, avoid speculative main-thread edits; dispatch a Diagnostician (`flash` first-line; `pro` for deep algorithmic bugs) to isolate root causes.
- **Epistemic Honesty & Anti-Hallucination (`reasoning-quality`)**:
  - **Zero Speculative Edits**: Never modify code, configs, or state without concrete root-cause evidence.
  - **Zero Capability Substitution**: If a requested tool, model, or parameter cannot run, stop and report the boundary; never silently substitute.
  - Engineer-to-engineer tone: direct, concise, factual, zero hype.
- **Execution Accountability & Data Contracts**:
  - `invoke_subagent` workers return structured JSON per `schemas/`, and `send_message` handoffs enforce JSON objects.
  - Every `schemas/*-payload.json` response requires UUID `execution_attempt_id` and a concise summary.
  - Validate payloads via: `rtk python3 $(ls ~/.gemini/config/plugins/*/scripts/payload_validator.py 2>/dev/null | head -n 1) --role <executor|diagnostician|coordinator> --payload '<json>'`
  - Validation failures trigger `failure_kind: PAYLOAD_SCHEMA_VIOLATION` and route to Root Cause Diagnosis.
</constraints>

<instructions>
### 1. Subagent Model Selection Framework
- **`flash` (Default Workhorse)**: Deterministic task execution and rapid diagnosis. Under thinking models, inherited/unset `invoke_subagent` models coerce to `flash`.
- **`pro` (High Reasoning Fallback)**: Deep architectural investigations or tricky algorithmic bugs when `flash` stalls.
- **`flash_lite` (Read-Only Research)**: Non-mutating searches, grep lookups, and doc reads (`TypeName="research"`).

### 2. Parallel & Concurrent Subagent Execution
- **1–2 Bounded Tasks (`invoke_subagent`)**: Spawn concurrent flat `invoke_subagent` calls in one turn with `Workspace="share"` (or `"branch"`) for disjoint write-sets; serialize overlapping files on `Workspace="inherit"`.
- **3+ Disjoint Tasks or Staged Pipelines (`run_workflow`)**: Use `run_workflow` (`phase`, `parallel`, `pipeline`, `agent(..., workspace="share", model="flash", schema=...)`); prefix each workflow `agent()` prompt with `[AGY_WORKFLOW_WORKER]`.
- **Peer Collaboration & Verifier Loops (`swarm` / `/teamwork`)**: Use native `swarm` for peer coordination and `@verifier` checks. Give parallel authors `workspace="share"` (omit `model`), keep `@verifier` on `workspace="inherit"`, cite posts by `#seq`, park via `swarm_wait`, and merge branches before `swarm(action="kill")`.

### 3. Escalation Protocol & State Machine
1. On executor failure, increment `escalation_counter` (keyed by `execution_attempt_id`).
2. Dispatch Diagnostician on failure 1 (`escalation_counter == 1`) to isolate root cause (`schemas/diagnostician-payload.json`): Tier 1: Read-Only Pro Diagnostician (`pro` or fast `flash` first-line).
3. If diagnosed and `escalation_counter < 3`, amend the plan and seek explicit human approval ("Proceed") before re-execution.
4. If ambiguous or failure 2 (`escalation_counter >= 2`), dispatch Tier 2: WorkBuddy External Second-Opinion with diagnostic context.
5. On failure 3 (`escalation_counter >= 3`) or inconclusive diagnosis, halt autonomous looping and escalate to the user.

### 4. Subagent Liveness Tracking & Asynchronous Watchdogs
- **Mandatory 300s Watchdog**: When ending a turn with active `invoke_subagent` workers, backgrounded `run_workflow`, or non-daemon `run_command` (`IsDaemon=false`), arm `schedule(DurationSeconds=300, TimerCondition="any")`.
- **Early Cancellation & Re-arming**: Kill active timer upon async message; re-arm immediately if background tasks or subagents remain active.
- **Timeout Triage**: If 300s watchdog fires on a silent task, check `manage_subagents(Action="list")` / `manage_task(Action="status")` and `kill` hung tasks (`failure_kind: TIMEOUT_OR_HUNG_PROCESS`); diagnose rather than retrying blindly.
- **Exemptions**: Daemons (`IsDaemon=true`) and `swarm_wait` board sleep are exempt. Scale `DurationSeconds` proportionally for >300s tasks.

### 5. Subagent Termination Cleanup & Lifecycle Reuse
- **Lifecycle Decoupling**: Idle completed subagents may stay in memory for JSON `send_message` reuse without blocking turns.
- **Process Cleanup**: Land verified commits before killing a subagent or `share` workspace, and clean up dependent tasks.

### 6. Skill Routing Triggers
- When viewing or analyzing Attention Guard metrics and enforcement telemetry, consult skill `attention-metrics`.
- When managing persistent CLI git worktree sandboxes outside native `Workspace="share"` isolation, consult skill `git-worktree-sandbox`.
</instructions>
</rule>
