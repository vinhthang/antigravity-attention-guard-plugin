<rule name="executor-subagent">
<description>
Governs Executor subagents dispatched for bounded task execution.
</description>

<constraints>
- **Zero Delegation**: Executor subagents are strictly forbidden from delegating tasks further. Do not call `invoke_subagent`, `manage_subagents`, `run_workflow`, or `swarm`.
- **Isolated Workspace Hygiene**: When dispatched with `Workspace="share"` or `Workspace="branch"`, commit verified changes cleanly on your isolated workspace branch and report the branch and commit SHA so the orchestrator can merge or cherry-pick before cleanup.
- **Background Task Completion Fence**: Never fabricate `<system_message>` blocks and never call `send_message` while any non-daemon background `run_command` task (`task-*`) remains running.
- **Bounded TDD Iteration**: Up to 5 implementation attempts per failing test increment are permitted to reach GREEN. Halt immediately on unexpected baseline regressions, crashes, or exceeding 5 attempts rather than making speculative edits.
- **Concise Handoff (Zero Raw Log Dumps)**: Report modified files, exact test command and pass/fail counts, and concise root-cause diagnostics on failure. Never paste raw ANSI escape sequences, full multi-frame tracebacks, or raw `pytest` session logs into `send_message`.
</constraints>
</rule>
