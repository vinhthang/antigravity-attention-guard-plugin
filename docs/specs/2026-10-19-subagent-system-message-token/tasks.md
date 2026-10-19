# Execution Tasks: Subagent Token Detection, Shell Argument Boundaries & Opus Auditor Preservation

- **Feature ID**: `2026-10-19-subagent-system-message-token`
- **Status**: `Approved`

## Implementation Checklist

- [x] **Task 1: Update `is_subagent()` in `scripts/common.py`** (`REQ-001`)
  - [x] Check `if step.get("type") in ("USER_INPUT", "SYSTEM_MESSAGE"):` when scanning `transcriptPath` for `[ANTIGRAVITY_TOKEN:...]` (`AC-001-1`, `AC-001-2`).
- [x] **Task 2: Add regression unit test and record verification evidence** (`REQ-002`)
  - [x] Add unit test verifying `is_subagent()` detects `[ANTIGRAVITY_TOKEN:...]` inside a `"SYSTEM_MESSAGE"` transcript step (`AC-002-1`).
  - [x] Run `pytest -v` and record verbatim test output in `verification.md` (`AC-002-2`).
- [x] **Task 3: Fix `python`/`python3` script argument boundary parsing in `is_test_command()` and `is_build_command()`** (`REQ-003`)
  - [x] Stop scanning tokens after the target `<script>` or `-m <module>` in `enforce-delegation.py` (`is_test_command`) and `common.py` (`is_build_command`) (`AC-003-1`, `AC-003-2`).
- [x] **Task 4: Preserve Opus/`pro`/`inherit` model for `traceability-auditor` subagents in `inject-rules.py` and add unit tests** (`REQ-004`)
  - [x] Deny `flash`/`flash_lite` and preserve `pro`/`inherit` for `traceability-auditor` in `scripts/inject-rules.py`, add unit tests in `tests/test_system_message_subagent.py`, and update `verification.md` (`AC-004-1`).
