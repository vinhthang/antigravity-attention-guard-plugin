<rule name="agent-delegation">
<description>
Enforces Ray Dalio's 5-Step Process (Clear Goals, Problem Intolerance, Root Cause Diagnosis, Deterministic Design, Execution Accountability) across the agent lifecycle.
</description>

<constraints>
- **Step 1: Set Clear Goals (Phase 1 / Primary Agent & Adaptive Planning)**:
  - **Adaptive Planning Protocol**:
    - **Plan & Delegate**: Multi-step architecture features, complex refactors, and test-driven implementations require `implementation_plan.md` and Human Gate ("Proceed") before subagent execution. You MUST define falsifiable acceptance criteria—including exact automated verification commands and expected exit states—before any execution subagents are dispatched.
    - **Direct Execution**: Quick one-offs, single-file edits, configuration adjustments, and direct user prompts can be executed directly by the Primary Agent without plan overhead.
- **Step 4: Deterministic Design & Human Gate**: Author `implementation_plan.md` and track checklists in `task.md` (`- [ ]`) for planned delegation workflows. Subagent execution is strictly gated behind explicit human approval ("Proceed"). Direct execution tasks proceed directly without plan overhead.
- **Step 2: Identify & Don't Tolerate Problems (Phase 2 / Subagents)**: Strictly adhere to `rules/no-error-suppression.md`. Zero error suppression, no bare `pass`, and no silent failure swallows. Any command failure or assertion break is a structural blocker.
- **Step 3: Root Cause Diagnosis Gate (Escalation Protocol)**:
  - When an executor subagent encounters a failure, the Primary Agent MUST dispatch a `pro` subagent as a **Diagnostician**.
  - **The Diagnostician is strictly read-only.** It is forbidden from modifying code or running state-altering commands.
  - The Diagnostician MUST isolate the proximate cause (e.g. traceback line) from the root cause (flawed assumption, race condition, data contract mismatch).
  - Maximum 3 escalation attempts. If `escalation_counter >= 3` or diagnosis is inconclusive, stop autonomous looping and escalate to the human user.
- **Step 5: Push Through to Results (Execution Accountability)**:
  - Subagents MUST return strict, valid JSON conforming to role schemas in `schemas/`.
  - Every payload MUST include an immutable `execution_attempt_id` (UUID format).
  - Executor summaries MUST NOT exceed 1200 characters.
  - **Payload Validation**: Upon receiving a subagent response, the Primary Agent MUST validate the returned JSON using:
    `rtk python3 scripts/payload_validator.py --role <executor|diagnostician|coordinator> --payload '<json>'`
  - If validation fails, treat it as a structural failure (`failure_kind: PAYLOAD_SCHEMA_VIOLATION`) and trigger Step 3 Root Cause Diagnosis.
</constraints>

<instructions>
### 1. Subagent Model Selection Framework
- **`pro` (Maximum Reasoning)**: Reserved for read-only Root Cause Diagnosis, complex architecture investigations, and workstream Coordination.
- **`flash` (Mechanical Execution)**: Used for deterministic execution where planning is already completed (applying explicit diffs, running tests, formatting).
- **`flash_lite` (Read-Only Research)**: Reserved for non-mutating searches, grep lookups, and reading documentation.

### 2. Escalation Protocol & State Machine
1. On executor failure, increment `escalation_counter` (keyed by unique `execution_attempt_id`).
2. Dispatch a read-only `pro` Diagnostician (Tier 1: Read-Only Pro Diagnostician) on failure attempt 1 (`escalation_counter == 1`) with read-only tools to isolate root causes (`schemas/diagnostician-payload.json`).
3. If diagnosis is determined and `escalation_counter < 3`, amend the implementation plan in Phase 1 and seek explicit human approval ("Proceed") before any re-execution attempt.
4. If diagnosis is ambiguous or execution fails a second time (`escalation_counter >= 2`), dispatch external second-opinion review (Tier 2: WorkBuddy External Second-Opinion) with diagnostic context. Tier 2 feeds diagnostic hypotheses back into Step 4 plan amendment, requiring explicit human approval ("Proceed") before re-executing.
5. If execution fails a third time (`escalation_counter >= 3`) or diagnosis remains inconclusive, stop autonomous looping and transition directly to human escalation (Dalio Human Gate). Reset counter to 0 only upon explicit human guidance.

### 3. Subagent Liveness Tracking
- When spawning subagents, the Primary Agent MUST ALWAYS arm a 300s liveness timer via `schedule(DurationSeconds=300, TimerCondition="any")`.
- When a subagent message arrives, immediately kill the active timer task.
- If the timer fires and the subagent hasn't reported, query `manage_subagents(Action="list")` and terminate hung processes.

### 4. Subagent Termination Cleanup
- If the Primary Agent kills a child subagent, it must handle dependent subagents cleanly and avoid orphaned processes.
</instructions>
</rule>
