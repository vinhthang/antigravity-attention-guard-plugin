<rule name="agent-delegation">
<description>
Enforces subagent delegation and lifecycle governance to protect the Primary Agent's context window from Attention Dilution.
</description>

<constraints>
- **Attention Protection & Delegation**:
  - The Primary Agent focuses on strategic reasoning, architectural design, and workstream coordination.
  - Multi-step implementations, noisy builds, and repetitive test runs must be delegated to subagents to prevent context window bloat. Quick one-offs, single-file edits, configuration adjustments, and direct user prompts may proceed directly.
  - Multi-step implementation plans require explicit human approval ("Proceed") before execution subagents are dispatched.
- **Problem Intolerance & Root Cause Focus**:
  - Zero error suppression: Never ignore failures, swallow exceptions with bare `pass`, or mask errors with `|| true`. Any command failure or assertion break is a structural blocker.
  - When an execution subagent fails, avoid speculative trial-and-error edits in the main thread (the primary cause of attention dilution). Dispatch a `pro` Diagnostician to isolate root causes before attempting fixes.
- **Execution Accountability & Data Contracts**:
  - Subagents must return structured JSON conforming to role schemas in `schemas/`.
  - Every payload must include an immutable `execution_attempt_id` (UUID format) and a concise summary.
  - Validate returned subagent payloads using:
    `rtk python3 scripts/payload_validator.py --role <executor|diagnostician|coordinator> --payload '<json>'`
  - Validation failures trigger `failure_kind: PAYLOAD_SCHEMA_VIOLATION` and route to Root Cause Diagnosis.
</constraints>

<instructions>
### 1. Subagent Model Selection Framework
- **`pro` (High Reasoning)**: Used for in-depth Root Cause Diagnosis, complex refactoring, tricky algorithmic implementation, architectural investigations, and workstream Coordination. When executing code mutations, `pro` must follow the sequential write discipline defined in `COORDINATOR.md`.
- **`flash` (Mechanical Execution)**: Used for deterministic execution where planning is already completed (applying targeted diffs, running tests, formatting).
- **`flash_lite` (Read-Only Research)**: Reserved for non-mutating searches, grep lookups, and reading documentation.

### 2. Escalation Protocol & State Machine
1. On executor failure, increment `escalation_counter` (keyed by unique `execution_attempt_id`).
2. Dispatch a `pro` Diagnostician (Tier 1: Read-Only Pro Diagnostician for diagnosis, or Pro Specialist for complex reproduction/refactoring) on failure attempt 1 (`escalation_counter == 1`) to isolate root causes (`schemas/diagnostician-payload.json`).
3. If diagnosis is determined and `escalation_counter < 3`, amend the implementation plan and seek explicit human approval ("Proceed") before any re-execution attempt.
4. If diagnosis is ambiguous or execution fails a second time (`escalation_counter >= 2`), dispatch external second-opinion review (Tier 2: WorkBuddy External Second-Opinion) with diagnostic context.
5. If execution fails a third time (`escalation_counter >= 3`) or diagnosis remains inconclusive, stop autonomous looping and escalate directly to the human user.

### 3. Subagent Liveness Tracking
- When spawning subagents, the Primary Agent MUST ALWAYS arm a 300s liveness timer via `schedule(DurationSeconds=300, TimerCondition="any")`.
- When a subagent message arrives, immediately kill the active timer task.
- If the timer fires and the subagent hasn't reported, query `manage_subagents(Action="list")` and terminate hung processes.

### 4. Subagent Termination Cleanup
- If the Primary Agent kills a child subagent, it must handle dependent subagents cleanly and avoid orphaned processes.
</instructions>
</rule>
