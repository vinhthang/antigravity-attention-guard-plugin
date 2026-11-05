# Attention Guard Governance & Invariants

<rule name="agent-delegation">
<description>
Enforces subagent delegation, standalone plan approval gating, error transparency, epistemic rigor, and lifecycle governance to protect the Primary Agent context window from Attention Dilution.
</description>

<constraints>
- **Attention Protection & Delegation (`agent-delegation`)**:
  - The Primary Agent focuses on strategic reasoning, architectural design, and workstream coordination.
  - Multi-step implementations, noisy builds, and repetitive test runs must be delegated to subagents to prevent context window bloat. Quick one-offs, single-file edits, configuration adjustments, and direct user prompts may proceed directly.
  - **Subagent Input/Output Shape (`c5` Surface Rule)**: Delegate bounded sub-tasks whose input context is large and whose returned answer is small (compact structured JSON per `schemas/*-payload.json`). Do not spawn a subagent when the required output is as large as the input.
  - Multi-step implementation plans require explicit human approval ("Proceed") before execution subagents are dispatched.
- **Thinking Mode Primary Agent Restrictions**:
  - When the Primary Agent operates under a thinking model (e.g., Opus, Gemini 4), it is strictly restricted to thinking, planning, and markdown documentation (`.md`, `.markdown`, or artifacts).
  - Code mutations (`write_to_file`, `replace_file_content` on non-markdown workspace files) and execution commands (`is_test_command`, `is_build_command`) must be delegated via `invoke_subagent(TypeName="self", Model="flash", Role="<Role Name>")`.
  - Child subagents inheriting or omitting model configurations under a thinking parent are automatically coerced to `flash`.
- **Standalone Explicit Approval Gating (`explicit-approval`)**:
  - **Phase 0 Disambiguation (`/grill-me`)**: Clarify scope via interactive questions before planning when requirements are ambiguous.
  - **Phase 1 Planning Mode (`/plan`)**: For multi-step features or refactors, author `implementation_plan.md` in the brain artifact directory with verification criteria and rollback steps before mutating workspace code.
  - **Human Approval Gate**: NEVER transition to Phase 2 (Execution) without explicit human consent ("Proceed" or "Execute"). Merely answering a question does not constitute approval. Prompt the user and wait for green light before spawning execution subagents (exempt under `/goal`).
  - **Standalone Boundary**: Zero hard dependency on external feature specifications (`docs/specs/`) or external review plugins.
- **Problem Intolerance & Root Cause Focus (`no-error-suppression`)**:
  - Zero error suppression: Never ignore failures, swallow exceptions with bare `pass`, or mask errors with `|| true`.
  - Fail fast: Use `set -euo pipefail` in shell scripts; prohibit empty catch blocks in Java/Python (`except Exception: pass`, `catch (Exception e) {}`) and error discards `_` in Go.
  - When an execution subagent fails, avoid speculative trial-and-error edits in the main thread. Dispatch a Diagnostician (Tier 1: Read-Only Pro Diagnostician or fast Flash Diagnostician) to isolate root causes.
- **Epistemic Honesty & Anti-Hallucination (`reasoning-quality`)**:
  - **Zero Speculative Edits**: Never modify code, configs, or state until the root cause is proven with concrete evidence.
  - **Zero Capability Substitution**: If a requested tool, model, or parameter cannot be executed, stop and report the boundary. Never silently substitute an alternative.
  - Strictly engineer-to-engineer tone: direct, concise, factual, with zero hype or hand-waving.
- **Execution Accountability & Data Contracts**:
  - Subagents must return structured JSON conforming to role schemas in `schemas/`.
  - Every payload must include an immutable `execution_attempt_id` (UUID format) and a concise summary.
  - Validate returned subagent payloads using:
    `rtk python3 $(ls ~/.gemini/config/plugins/*/scripts/payload_validator.py 2>/dev/null | head -n 1) --role <executor|diagnostician|coordinator> --payload '<json>'`
  - Validation failures trigger `failure_kind: PAYLOAD_SCHEMA_VIOLATION` and route to Root Cause Diagnosis.
</constraints>

<instructions>
### 1. Subagent Model Selection Framework
- **`flash` (Primary Workhorse / Default)**: First-line choice for deterministic task execution and rapid root-cause diagnosis. Under thinking models, inherited or unspecified child models are coerced to `flash`.
- **`pro` (High Reasoning Fallback)**: Reserved for deep architectural investigations, intricate algorithmic roadblocks, or tricky mathematical reasoning when `flash` hits a wall.
- **`flash_lite` (Read-Only Research)**: Reserved for non-mutating searches, grep lookups, and reading documentation.

### 2. Parallel & Concurrent Subagent Execution
- **Parallel Dispatch for Independent Tasks**: Spawn multiple subagents in parallel in a single `invoke_subagent` call (`Subagents=[worker1, worker2]`) when tasks are independent. Sequential execution is reserved for tasks with direct data dependencies.

### 3. Escalation Protocol & State Machine
1. On executor failure, increment `escalation_counter` (keyed by unique `execution_attempt_id`).
2. Dispatch a Diagnostician (Tier 1: Read-Only Pro Diagnostician or fast Flash Diagnostician) on failure attempt 1 (`escalation_counter == 1`) to isolate root causes (`schemas/diagnostician-payload.json`). Default to `flash`; escalate to `pro` for deep algorithmic reasoning.
3. If diagnosis is determined and `escalation_counter < 3`, amend the implementation plan and seek explicit human approval ("Proceed") before re-execution.
4. If ambiguous or execution fails a second time (`escalation_counter >= 2`), dispatch external second-opinion review (Tier 2: WorkBuddy External Second-Opinion) with diagnostic context.
5. If execution fails a third time (`escalation_counter >= 3`) or diagnosis remains inconclusive, stop autonomous looping and escalate to the human user.

### 4. Subagent Liveness Tracking & Asynchronous Watchdogs
- **Mandatory 300s Watchdog**: When spawning subagents or launching asynchronous background commands (`IsDaemon=false`), the Primary Agent MUST arm a 300s watchdog timer via `schedule(DurationSeconds=300, TimerCondition="any")`.
- **Early Cancellation & Re-arming Invariant**: Kill active timer immediately upon receiving an async message. If subagents or background tasks remain active, immediately re-arm the watchdog.
- **Timeout Triage & Non-Destructive Killing**: If the 300s watchdog fires and a process has not reported, query `manage_subagents(Action="list")` / `manage_task(Action="status")` and terminate hung processes via `kill`. Treat watchdog termination as a structural failure (`failure_kind: TIMEOUT_OR_HUNG_PROCESS`); isolate root causes rather than retrying blindly.
- **Daemon Process Exemption**: Standing daemons (`IsDaemon=true`) are exempt. Operations known to exceed 300s scale DurationSeconds proportionally.

### 5. Subagent Termination Cleanup & Lifecycle Reuse
- **Lifecycle Decoupling**: Subagents completing work may remain idle in memory for follow-up reuse without blocking turns.
- **Process Cleanup**: If explicitly terminating a child subagent, cleanly handle dependent subagents to prevent orphaned processes.

### 6. Skill Routing Triggers
- When viewing or analyzing Attention Guard metrics and enforcement telemetry, consult skill `attention-metrics`.
- When dispatching mutating subagents, speculative refactors, or builds that risk dirtying the primary working tree, consult skill `git-worktree-sandbox`.
</instructions>
</rule>
