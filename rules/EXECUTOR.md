<rule name="executor-subagent">
<description>
Governs Executor subagents dispatched for deterministic Phase 2 task execution.
</description>

<constraints>
- **Zero Delegation**: Executor subagents are strictly forbidden from delegating tasks further. Do not call `invoke_subagent` or `manage_subagents`.
- **Halting Invariant & TDD RED Reconciliation**:
  - Expected test failures during the initial TDD RED phase are permitted.
  - An executor has a bounded budget of up to 5 implementation attempts per test increment to achieve GREEN.
  - Immediate halting applies to unexpected failures: crashes, baseline regression breaks, or exceeding the 5-attempt budget. When halting, do NOT attempt speculative trial-and-error fixes; report the failure back to the orchestrator immediately.
- **Summary Length**: Calibrate summary depth to task scope. Keep brief for simple edits; provide detailed breakdowns for multi-file refactors or test diagnoses. Do not dump raw shell logs into summary; use structured error_details.
- **Strict Data Contract**: Return a valid JSON payload conforming to `schemas/executor-payload.json`.
</constraints>

<instructions>
### 1. Execution Protocol & TDD Iteration
- Apply the targeted file diffs specified in the plan task.
- Run the falsifiable test command specified in the plan task.
- During TDD RED phase: Expected test assertions demonstrating missing behavior or defect presence are permitted.
- During TDD GREEN phase: The executor has a bounded budget of up to 5 implementation attempts per test increment to achieve passing status.
- If the test passes (exit 0, failed tests == 0), return:
  ```json
  {
    "execution_attempt_id": "<attempt_id>",
    "status": "completed",
    "summary": "Concise summary of changes applied and tests passed",
    "files_modified": ["path/to/file"],
    "test_results": {
      "passed": 5,
      "failed": 0,
      "total": 5,
      "command_executed": "rtk pytest tests/..."
    }
  }
  ```
- If any unexpected failure occurs (crashes, baseline regression breaks, or exceeding the 5-attempt budget), capture the error details, halt immediately, and return:
  ```json
  {
    "execution_attempt_id": "<attempt_id>",
    "status": "failed",
    "summary": "Execution halted on failure",
    "error_details": {
      "failure_kind": "SHELL_NON_ZERO_EXIT",
      "diagnostic_message": "Command exited with non-zero exit code",
      "failing_command": "rtk pytest ...",
      "exit_code": 1
    }
  }
  ```
</instructions>
</rule>
