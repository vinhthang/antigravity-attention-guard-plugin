# Attention Guard: Delegation Protocol

1. **Two-Phase Lifecycle & Agent Delegation:** 
   - **Phase 1 (Planning / Primary Agent):** High-level reasoning. Analyze risks and define boundaries. Create `implementation_plan.md` and update `task.md` with a checklist (`- [ ]`). No code changes yet.
   - **Phase 2 (Execution / Subagents):** Low-level deterministic execution. Delegate code edits, terminal commands, and checks to subagents based on the Model Selection Framework. Mark `task.md` done (`- [x]`).

2. **Subagent Model Selection Framework:**
   - **`pro` (Maximum Reasoning):** Use for tasks requiring high autonomy, significant net-new logic, deep refactoring, or complex tools/infrastructure debugging (e.g., SSH, k3s).
   - **`flash` (Mechanical Execution):** Use for tasks where the "thinking" is already done in the plan. Applying targeted diffs, running standard test suites, or formatting.
   - **`flash_lite` (Read-Only):** Reserve strictly for non-mutating research, simple file reading, or grep searches.

3. **Escalation Protocol:**
   - If a `flash` subagent encounters an unexpected failure (e.g., broken build, test failure), it MUST NOT attempt to fix it blindly. It must stop and report back immediately.
   - The Primary Agent will then spawn a `pro` subagent to investigate and debug the failure.

4. **Subagent Communication:**
   - When a subagent finishes a task, it MUST use the `send_message` tool to report its findings or completion status back to the parent agent before terminating.
