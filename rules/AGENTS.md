<rule name="agent-delegation">
<description>
Enforces the two-phase agent lifecycle, subagent model selection, escalation protocol, and strict JSON handoff communication.
</description>

<constraints>
- **Phase 1 (Planning / Primary Agent):** High-level reasoning. Analyze risks and define boundaries. **Mandatory Risk Evaluation:** You MUST autonomously evaluate the architectural blast radius. If the task involves core infrastructure, database connections, concurrency, or synchronous platform hooks, you MUST self-activate the `superpowers` skill to perform a deep audit before proceeding. Create `implementation_plan.md` and update `task.md` with a checklist (`- [ ]`). No code changes yet.
- **Phase 2 (Execution / Subagents):** Low-level deterministic execution. Delegate code edits, terminal commands, and checks to subagents based on the Model Selection Framework. Mark `task.md` done (`- [x]`).
- If a `flash` subagent encounters an unexpected failure (e.g., broken build, test failure), it MUST NOT attempt to fix it blindly. It must stop and report back immediately.
- Subagent responses via `send_message` MUST be valid JSON. No conversational fluff.
</constraints>

<instructions>
### 1. Subagent Model Selection Framework
- **`pro` (Maximum Reasoning):** Use for tasks requiring high autonomy, significant net-new logic, deep refactoring, or complex tools/infrastructure debugging (e.g., SSH, k3s).
- **`flash` (Mechanical Execution):** Use for tasks where the "thinking" is already done in the plan. Applying targeted diffs, running standard test suites, or formatting.
- **`flash_lite` (Read-Only):** Reserve strictly for non-mutating research, simple file reading, or grep searches.

### 2. Escalation Protocol
- The Primary Agent will spawn a `pro` subagent to investigate and debug failures reported by `flash` subagents.

### 3. Subagent Communication
- Required fields: `{"status": "completed|failed", "summary": "..."}`. Add `files_modified`, `test_results`, or `error` as needed.
### 4. Subagent Termination Cleanup
- If the Primary Agent manually kills a child subagent using the `manage_subagents` tool, it MUST explicitly handle the parent subagent that is stuck waiting. The Primary Agent must either kill the parent subagent as well, or use `send_message` to notify the parent of the child's termination so the parent can exit cleanly.

### 5. Subagent Liveness Tracking
- When spawning subagents, the Primary Agent MUST ALWAYS use the `schedule` tool to set a liveness timer (e.g., DurationSeconds=300) with `TimerCondition: any`. This prevents the Primary Agent from sleeping indefinitely if a subagent hangs. If the timer fires and the subagent hasn't replied, the Primary Agent must investigate using the `manage_subagents` tool.
</instructions>
</rule>
