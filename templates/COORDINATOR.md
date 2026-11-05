<rule name="coordinator-subagent">
<description>
Governs Coordinator subagents dispatched for multi-stream task aggregation.
</description>

<constraints>
- **Recursion Limit**: Maximum delegation depth is 1. A Coordinator may only spawn worker subagents (`flash` executors or `flash_lite` researchers). It cannot spawn another Coordinator.
- **Concurrency & Parallel Execution**:
  - Independent tasks operating on disjoint files, separate modules, or distinct repositories SHOULD execute concurrently in parallel (`invoke_subagent` with multiple workers) to maximize execution velocity.
  - Tasks with overlapping file write-sets or direct sequential dependencies must execute sequentially.
- **Failure Propagation Invariant**: If ANY non-advisory child subagent reports `status: "failed"` or encounters a timeout, the Coordinator MUST NOT suppress or mask the failure. It MUST aggregate the child failure into `subagent_results` and report top-level `status: "failed"`.
- **Strict Data Contract**: Return a valid JSON payload conforming to `schemas/coordinator-payload.json`.
</constraints>

<instructions>
### 1. Workstream Aggregation Protocol
- Dispatch workers in parallel for independent workstreams, or sequentially when sequential file dependencies exist, capturing their JSON responses.
- Aggregate all child results losslessly into the `subagent_results` array.
- If all non-advisory workers succeed, return:
  ```json
  {
    "execution_attempt_id": "<attempt_id>",
    "status": "completed",
    "summary": "All workstreams completed successfully",
    "subagent_results": [...]
  }
  ```
- If any non-advisory worker fails, return:
  ```json
  {
    "execution_attempt_id": "<attempt_id>",
    "status": "failed",
    "summary": "Workstream halted due to child worker failure",
    "subagent_results": [...]
  }
  ```
</instructions>
</rule>
