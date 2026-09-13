<rule name="executor-subagent">
<description>
Governs Executor subagents dispatched for deterministic Phase 2 task execution.
</description>

<constraints>
- **Zero Delegation**: Executor subagents are strictly forbidden from delegating tasks further. Do not call `invoke_subagent` or `manage_subagents`.
- **Halting Invariant**: If any shell command, compiler check, or test assertion fails, STOP immediately. Do NOT attempt speculative trial-and-error fixes. Report the failure back to the orchestrator immediately.
- **Summary Length**: The `summary` field MUST be concise, between 10 and 1200 characters.
- **Strict Data Contract**: Return a valid JSON payload conforming to `schemas/executor-payload.json`.
</constraints>

<instructions>
### 1. Execution Protocol
- Apply the targeted file diffs specified in the plan task.
- Run the falsifiable test command specified in the plan task.
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
- If any command fails, capture the error details and return:
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
