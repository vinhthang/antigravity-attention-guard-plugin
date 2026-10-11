<rule name="agent-delegation">
<description>
Enforces subagent delegation and lifecycle governance to protect the Primary Agent's context window from Attention Dilution.
</description>

<constraints>
- **Attention Protection & Delegation**:
  - The Primary Agent focuses on strategic reasoning, architectural design, and workstream coordination.
  - Multi-step implementations, noisy builds, and repetitive test runs must be delegated to subagents to prevent context window bloat. Quick one-offs, single-file edits, configuration adjustments, and direct user prompts may proceed directly.
  - Multi-step implementation plans require explicit human approval ("Proceed") before execution subagents are dispatched.
- **Thinking Mode Primary Agent Restrictions**:
  - When the Primary Agent operates under a thinking model (e.g., Opus, Gemini 4), it is strictly restricted to thinking, planning, and markdown documentation (`.md`, `.markdown`, or artifacts).
  - Code mutations (`write_to_file`, `replace_file_content` on non-markdown workspace files) and execution commands (`is_test_command`, `is_build_command`) must be delegated via `invoke_subagent(TypeName="self", Model="flash", Role="<Role Name>")`.
  - Child subagents inheriting or omitting model configurations under a thinking parent are automatically coerced to `flash`.
- **Problem Intolerance & Root Cause Focus**:
  - Zero error suppression: Never ignore failures, swallow exceptions with bare `pass`, or mask errors with `|| true`. Any command failure or assertion break is a structural blocker.
  - When an execution subagent fails, avoid speculative trial-and-error edits in the main thread (the primary cause of attention dilution). Dispatch a Diagnostician (Tier 1: Read-Only Pro Diagnostician or fast Flash Diagnostician) to isolate root causes before attempting fixes.
- **Execution Accountability & Data Contracts**:
  - Subagents must return structured JSON conforming to role schemas in `schemas/`.
  - Every payload must include an immutable `execution_attempt_id` (UUID format) and a concise summary.
  - Validate returned subagent payloads using:
    `rtk python3 /Users/thanghoang/.gemini/config/plugins/attention-guard/scripts/payload_validator.py --role <executor|diagnostician|coordinator> --payload '<json>'`
- Validation failures trigger `failure_kind: PAYLOAD_SCHEMA_VIOLATION` and route to Root Cause Diagnosis.
</constraints>

<instructions>
### 1. Subagent Model Selection Framework
- **`flash` (Primary Workhorse / Default)**: The first-line choice for both deterministic task execution and rapid root-cause diagnosis. Highly optimized for tool use, low latency, precise schema adherence, and fast feedback loops. When a Primary Agent runs in thinking mode (e.g., Opus, Gemini 4), any dispatched subagents with inherited or unspecified models are automatically coerced to `flash` to preserve execution velocity and enforce delegation discipline.
- **`pro` (High Reasoning Fallback)**: Reserved for deep architectural investigations, intricate algorithmic roadblocks, or tricky mathematical reasoning when `flash` hits a wall. When executing code mutations, `pro` must follow the sequential write discipline defined in `COORDINATOR.md`.
- **`flash_lite` (Read-Only Research)**: Reserved for non-mutating searches, grep lookups, and reading documentation.

### 2. Escalation Protocol & State Machine
1. On executor failure, increment `escalation_counter` (keyed by unique `execution_attempt_id`).
2. Dispatch a Diagnostician (Tier 1: Read-Only Pro Diagnostician or fast Flash Diagnostician) on failure attempt 1 (`escalation_counter == 1`) to isolate root causes (`schemas/diagnostician-payload.json`). Default to `flash` for rapid, grounded tool execution; escalate to `pro` only when deep algorithmic reasoning is required.
3. If diagnosis is determined and `escalation_counter < 3`, amend the implementation plan and seek explicit human approval ("Proceed") before any re-execution attempt.
4. If diagnosis is ambiguous or execution fails a second time (`escalation_counter >= 2`), dispatch external second-opinion review (Tier 2: WorkBuddy External Second-Opinion) with diagnostic context.
5. If execution fails a third time (`escalation_counter >= 3`) or diagnosis remains inconclusive, stop autonomous looping and escalate directly to the human user.

### 3. Subagent Liveness Tracking & Asynchronous Watchdogs
- **Mandatory 300s Watchdog**: When spawning subagents via `invoke_subagent` OR launching finite asynchronous background commands via `run_command` (where `IsDaemon` is false), the Primary Agent MUST ALWAYS arm a 300s watchdog timer via `schedule(DurationSeconds=300, TimerCondition="any")`.
- **Early Cancellation & Re-arming Invariant**:
  - When an async message arrives (subagent payload or background task completion), immediately kill the active timer task if still running.
  - If additional subagents or background tasks remain active (`manage_subagents(Action="list")` or `manage_task(Action="list")`), immediately re-arm the watchdog timer for the remaining in-flight operations before yielding the turn.
- **Daemon Process & Long-Running Scaling**:
  - Standing background daemons (`IsDaemon=true`, e.g. dev servers, tunnels, file watchers) are exempt from watchdog termination.
  - For operations known in advance to legitimately exceed 300s (e.g. massive compiler builds or multi-gigabyte transfers), scale DurationSeconds proportionally to the expected upper bound rather than using the default 300s.
- **Timeout Triage & Non-Destructive Killing**:
  - If the 300s watchdog fires and a subagent has not reported: query `manage_subagents(Action="list")`, inspect `stateDetail`, and terminate hung processes via `manage_subagents(Action="kill")`.
  - If the watchdog fires and a background command has not exited: inspect task status via `manage_task(Action="status")`, examine log tails, and terminate hung tasks via `manage_task(Action="kill")`.
- **Post-Timeout Escalation**: A watchdog termination is a structural failure (`failure_kind: TIMEOUT_OR_HUNG_PROCESS`). Never swallow timeouts or re-run the exact command blindly. Increment `escalation_counter` and route to Root Cause Diagnosis to isolate why the process blocked (e.g. unbuffered pipe, stdin prompt, deadlock).

### 4. Subagent Termination Cleanup & Lifecycle Reuse
- **Lifecycle Decoupling**: Task completion is decoupled from process lifecycle. When a subagent completes its work and returns a completed payload, it may remain idle in memory for follow-up reuse without blocking turns.
- **Process Cleanup**: If the Primary Agent explicitly terminates a child subagent (e.g. on timeout or hung process), it must handle dependent subagents cleanly and avoid orphaned processes.
</instructions>
</rule>
