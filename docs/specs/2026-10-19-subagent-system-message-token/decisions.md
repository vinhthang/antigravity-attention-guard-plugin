# Architecture Decision Records (ADR): Subagent Token Detection & Shell Argument Boundaries

- **Feature ID**: `2026-10-19-subagent-system-message-token`
- **Status**: `Approved`

## `ADR-001`: Scan Both `USER_INPUT` and `SYSTEM_MESSAGE` Steps in `is_subagent()`
- **Context**: `inject-rules.py` prepends `[ANTIGRAVITY_TOKEN:<uuid>]` to the subagent's `Prompt` argument during `PreToolUse` on `invoke_subagent`. When Antigravity initializes the subagent's conversation transcript (`transcript.jsonl`), that initial prompt is recorded at `step_index: 0` with `"source": "USER_EXPLICIT"` and `"type": "SYSTEM_MESSAGE"`, whereas subsequent `send_message` turns are recorded with `"type": "USER_INPUT"`. Checking only `"USER_INPUT"` caused `is_subagent()` to miss the initial spawn token.
- **Decision**: Update line 146 of `scripts/common.py` from `if step.get("type") == "USER_INPUT":` to `if step.get("type") in ("USER_INPUT", "SYSTEM_MESSAGE"):`.
- **Consequences**: Subagents are reliably identified on their first turn (`step_index: 0`) as well as follow-up turns, preventing false Primary Agent classification and thinking-mode deadlocks while keeping `WORK_PREPARED` SQLite ledger verification intact.
- **Addresses**: `REQ-001`, `REQ-002`

## `ADR-002`: Stop `python`/`python3` Token Inspection at the Target Script or Module Boundary & Preserve Opus for `traceability-auditor`
- **Context**:
  1. `is_test_command()` and `is_build_command()` scanned all `shlex.split` tokens after `python3`, causing JSON payload arguments containing `"pytest"` or `"pip"` (`payload_validator.py --payload '{"command_executed": "rtk pytest -v"}'`) to be blocked as test/build commands.
  2. `inject-rules.py` coerced all subagents with `Model="inherit"` or `None` under a thinking parent to `"flash"`, which would downgrade an Opus `traceability-auditor` subagent to `flash`.
- **Decision**:
  1. In `is_test_command()` and `is_build_command()`, parse `python`/`python3` interpreter flags (`-u`, `-B`, `-W <arg>`, `-X <arg>`, `-m <mod>`, `-c <code>`) up to the first positional `<script>` token, evaluate only `<mod>` or `<script>`, and immediately stop scanning subsequent script arguments.
  2. In `inject-rules.py`, recognize `traceability-auditor` (`TypeName == "traceability-auditor"` or `"traceability"` in `Role.lower()`), reject `flash`/`flash_lite`, and preserve `"inherit"`/`"pro"`.
- **Consequences**: Eliminates false-positive command blocks on `payload_validator.py` and other helper scripts while enforcing high-reasoning model execution for semantic spec auditing.
- **Addresses**: `REQ-003`, `REQ-004`
