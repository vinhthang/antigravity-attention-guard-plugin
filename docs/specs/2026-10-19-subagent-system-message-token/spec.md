# Specification: Subagent Token Detection, Shell Command Argument Boundaries & Opus Auditor Preservation

- **Feature ID**: `2026-10-19-subagent-system-message-token`
- **Status**: `Approved`
- **Version**: `1.1.0`
- **Date**: `2026-10-19`

## 1. Problem Statement & Context

1. In `scripts/common.py` (`is_subagent()`, line 146), the transcript scanner previously extracted `[ANTIGRAVITY_TOKEN:<uuid>]` only from `"USER_INPUT"` steps, missing `"SYSTEM_MESSAGE"` steps at `step_index: 0`.
2. In `scripts/enforce-delegation.py` (`is_test_command()`, lines 59–76) and `scripts/common.py` (`is_build_command()`, lines 64–67), invoking `python3 <script.py> [script_args...]` scanned all tokens in `script_args` for substrings like `"pytest"`, `"unittest"`, or `"pip"`. Consequently, running non-test scripts such as `payload_validator.py --payload '{"command_executed": "rtk pytest -v"}'` triggered false-positive Thinking-Mode restrictions.
3. In `scripts/inject-rules.py` (lines 37–40), when a thinking-mode Primary Agent dispatches a subagent with `Model="inherit"` or `None`, it unconditionally coerces `Model` to `"flash"`. However, semantic traceability auditing (`traceability-auditor`) requires an Opus / high-reasoning subagent (`"pro"` or `"inherit"`) and must never be coerced to or executed with `"flash"`.

---

## 2. Normative Requirements

### `REQ-001`: `SYSTEM_MESSAGE` & `USER_INPUT` Token Extraction in `is_subagent()`
- **Statement**: `is_subagent(data)` in `scripts/common.py` MUST scan both `"USER_INPUT"` and `"SYSTEM_MESSAGE"` transcript steps when extracting `[ANTIGRAVITY_TOKEN:<uuid>]` tokens.
- **Acceptance Criteria**:
  - `AC-001-1`: `is_subagent(data)` matches `step.get("type") in ("USER_INPUT", "SYSTEM_MESSAGE")` and returns `(True, is_verified, turn_id, role, session_id)` when a valid `WORK_PREPARED` token is present in a `"SYSTEM_MESSAGE"` step at `step_index: 0`.
  - `AC-001-2`: Existing `"USER_INPUT"` token detection and `WORK_PREPARED` ledger verification remain unchanged.

### `REQ-002`: Unit Test Coverage for `SYSTEM_MESSAGE` Subagent Transcripts
- **Statement**: The test suite MUST include a regression test verifying that `is_subagent()` identifies a subagent whose `[ANTIGRAVITY_TOKEN:...]` is recorded in a `"SYSTEM_MESSAGE"` transcript step.
- **Acceptance Criteria**:
  - `AC-002-1`: Unit test in `tests/` creates a transcript with `"type": "SYSTEM_MESSAGE"` containing `[ANTIGRAVITY_TOKEN:...]` and asserts `is_subagent()` returns `is_sub == True` and `is_verified == True`.
  - `AC-002-2`: Full `pytest` suite in `antigravity-attention-guard-plugin` passes with 0 failures.

### `REQ-003`: Script Argument Boundary Enforcement in `is_test_command()` and `is_build_command()`
- **Statement**: `is_test_command()` in `scripts/enforce-delegation.py` and `is_build_command()` in `scripts/common.py` MUST stop scanning `python`/`python3` tokens once the target script or `-m <module>` / `-c <code>` is identified, so CLI arguments passed *to* a Python script (such as `--payload '{"command_executed": "rtk pytest -v"}'`) never trigger false positives.
- **Acceptance Criteria**:
  - `AC-003-1`: `is_test_command("rtk python3 payload_validator.py --payload '{\"command_executed\": \"rtk pytest -v\"}'")` returns `False`, while `is_test_command("rtk python3 -m pytest tests/")` and `is_test_command("rtk pytest -v")` return `True`.
  - `AC-003-2`: `is_build_command("rtk python3 script.py --tool pip")` returns `False`, while `is_build_command("rtk python3 -m pip install pkg")` and `is_build_command("rtk pip install pkg")` return `True`.

### `REQ-004`: High-Reasoning Model Preservation for `traceability-auditor` in `inject-rules.py`
- **Statement**: `scripts/inject-rules.py` MUST preserve `"inherit"` or `"pro"` (defaulting unspecified `Model` to `"pro"` instead of `"flash"`) for `traceability-auditor` subagents, and deny dispatch if `Model` is explicitly set to `"flash"` or `"flash_lite"`.
- **Acceptance Criteria**:
  - `AC-004-1`: When `TypeName == "traceability-auditor"` or `"traceability" in Role.lower()`, `inject-rules.py` denies `Model in ("flash", "flash_lite")` and preserves `"inherit"` or `"pro"` (setting `Model = "pro"` if omitted).
