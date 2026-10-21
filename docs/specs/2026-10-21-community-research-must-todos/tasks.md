# Execution Tasks: Community & Literature Must-To-Do Hardening (`2026-10-21-community-research-must-todos`)

## Step 1: Core Guard & Hook Enhancements
- [x] **Task 1.1**: Update `scripts/enforce-delegation.py` and `scripts/inject-rules.py` to support Antigravity 2.0 tool names (`write_file`, `edit_file`) with `Path`/`Target`/`Replacement` arguments and flat `invoke_subagent` dictionaries (`REQ-007`).
- [x] **Task 1.2**: Implement `is_test_file()` and `check_test_tampering()` in `scripts/enforce-delegation.py` to block test-skipping markers (`@pytest.mark.skip`, `pytest.skip(`, `it.skip(`, `assert True`) on test files unless `AGY_ALLOW_TEST_SKIP=1` (`REQ-008`).
- [x] **Task 1.3**: Implement `check_subagent_doom_loop()` and `record_subagent_file_edit()` in `scripts/enforce-delegation.py` to block 3 consecutive identical subagent `run_command` calls without intervening file edits (`REQ-009`).
- [x] **Task 1.4**: Implement `check_destructive_command()` in `scripts/enforce-delegation.py` to block `git reset --hard`, `git clean -f`, `git checkout -- .`, `git restore .`, `git push --force` (allowing `--force-with-lease`), and catastrophic `rm -rf` targets (`REQ-010`).
- [x] **Task 1.5**: Update `scripts/attention-refresh.py` with `build_refresh_reminder()` to inject dynamic context budget telemetry (`tokens`, `% of 128k budget`, `Workers`) and write `<artifact_dir>/session_checkpoint.md` when `total_tokens >= 80000` (`REQ-011`).
- [x] **Task 1.6**: Implement `validate_no_raw_log_dump()` in `scripts/payload_validator.py` to reject raw ANSI escape codes and unformatted stack trace dumps in subagent `summary` strings (`REQ-012`).
- [x] **Task 1.7**: Update `check_walkthrough_requirement()` in `scripts/attention-check.py` to verify `walkthrough.md` `mtime` against the current turn's `work_items` creation timestamp (`REQ-013`).

## Step 2: Automated Verification & Regression Suite
- [x] **Task 2.1**: Add unit tests in `tests/test_community_must_todos.py` for Antigravity 2.0 `write_file`/`edit_file` (`Path`) and flat `invoke_subagent` (`REQ-007`).
- [x] **Task 2.2**: Add unit tests in `tests/test_community_must_todos.py` for `check_test_tampering()` (`REQ-008`).
- [x] **Task 2.3**: Add unit tests in `tests/test_community_must_todos.py` for `check_subagent_doom_loop()` and reset on file edit (`REQ-009`).
- [x] **Task 2.4**: Add unit tests in `tests/test_community_must_todos.py` for `check_destructive_command()` (`REQ-010`).
- [x] **Task 2.5**: Add unit tests in `tests/test_community_must_todos.py` for `build_refresh_reminder()` and `session_checkpoint.md` creation (`REQ-011`).
- [x] **Task 2.6**: Add unit tests in `tests/test_community_must_todos.py` and `scripts/payload_validator.py` for `validate_no_raw_log_dump()` (`REQ-012`).
- [x] **Task 2.7**: Add unit tests in `tests/test_community_must_todos.py` for turn-scoped `check_walkthrough_requirement()` (`REQ-013`).
- [x] **Task 2.8**: Update `scripts/attention-check.py` (`NO_TOOL_CALL` / `MAX_INVOCATIONS` / `ERROR` `terminationReason` support and `State.REVIEWING` Walkthrough Gate enforcement) and `scripts/common.py` (`step_index: 0` `sender=<uuid>` subagent detection) (`REQ-014`).
- [x] **Task 2.9**: Create `scripts/system_audit.py` and `tests/test_e2e_hook_pipeline.py` covering the full cross-plugin end-to-end hook lifecycle (`REQ-014`, `REQ-015`).
