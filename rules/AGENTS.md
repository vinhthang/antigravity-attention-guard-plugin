# Attention Guard: Delegation Protocol

1. **Two-Phase Lifecycle & Agent Delegation:** 
   - **Phase 1 (Planning / Primary Agent):** High-level reasoning. Analyze risks and define boundaries. Create `implementation_plan.md` and update `task.md` with a checklist (`- [ ]`). No code changes yet.
   - **Phase 2 (Execution / Subagents):** Low-level deterministic execution. Spawn subagents with `Model: "flash"` to apply edits, run commands, and validate checks. Mark `task.md` done (`- [x]`).

2. **Subagent Communication:**
   - When a subagent finishes a task, it MUST use the `send_message` tool to report its findings or completion status back to the parent agent before terminating.
