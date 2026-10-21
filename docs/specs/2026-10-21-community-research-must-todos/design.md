# Technical Design: Community & Literature Must-To-Do Hardening for Attention Guard

## 1. Component Architecture

### 1.1 `scripts/enforce-delegation.py` (`REQ-007`, `REQ-008`, `REQ-009`, `REQ-010`)
- **Tool & Path Normalization (`REQ-007`)**:
  - `MUTATION_TOOLS = {"write_to_file", "default_api:write_to_file", "replace_file_content", "default_api:replace_file_content", "multi_replace_file_content", "default_api:multi_replace_file_content", "write_file", "default_api:write_file", "edit_file", "default_api:edit_file"}`
  - `_extract_target_file(args)`: checks `Path`, `TargetFile`, `target_file`, `path`, `file_path`.
- **Test-Tampering Guard (`REQ-008`)**:
  - `check_test_tampering(target_file: str, args: dict) -> Optional[str]`:
    - Identifies test files (`test_*.py`, `*_test.py`, `*.test.ts`, `*.spec.ts`, `*_test.go`, or `/tests/` in normalized path).
    - Extracts added/replacement content (`Replacement`, `ReplacementContent`, `Content`, `CodeContent`, or `ReplacementChunks`) and target content (`Target`, `TargetContent`).
    - Flags newly introduced skip/tamper patterns (`@pytest.mark.skip`, `@pytest.mark.xfail`, `@unittest.skip`, `pytest.skip(`, `pytest.xfail(`, `it.skip(`, `describe.skip(`, `test.skip(`, `t.Skip(`, or `assert True`) that do not appear in the target text being replaced.
- **Subagent Doom-Loop Circuit Breaker (`REQ-009`)**:
  - `check_subagent_doom_loop(ledger: Ledger, conv_id: str, turn_id: str, tool_name: str, args: dict) -> Optional[str]`:
    - When `is_sub` is `True` and `tool_name in MUTATION_TOOLS`, records `SUBAGENT_FILE_EDIT` event in `ledger`.
    - When `is_sub` is `True` and `tool_name in ("run_command", "default_api:run_command")`, queries `events` for `conv_id` ordered by `created_at DESC` since the last `SUBAGENT_FILE_EDIT`. If the last 2 `SUBAGENT_COMMAND` events have the identical normalized command string (`cmd.strip()`), denies the 3rd consecutive identical execution. Otherwise records `SUBAGENT_COMMAND`.
- **Destructive Command Guard (`REQ-010`)**:
  - `check_destructive_command(cmd_str: str) -> Optional[str]`:
    - Applies to both primary agent and subagents on `run_command`.
    - Rejects `git reset --hard`, `git clean -f` / `-fd` / `-fx`, `git checkout -- .`, `git restore .`, `git push --force` / `-f` (unless `--force-with-lease` is present), and catastrophic `rm -rf` targeting `/`, `~`, `$HOME`, `.`, `..`, or `.git`.

### 1.2 `scripts/inject-rules.py` (`REQ-007`)
- Normalize flat `invoke_subagent` calls:
  - If `"Subagents"` is in `args` and is a list, iterate `args["Subagents"]` and emit `{"decision": "allow", "overwrite": {"Subagents": subagents}}`.
  - If `"Subagents"` is not in `args` and `("Prompt" in args or "TypeName" in args)`, wrap `sa = dict(args)`, apply the identical model coercion, token issuance, `materialize_context_pointer`, and `EVIDENCE_BOUNDARY` injection, and emit `{"decision": "allow", "overwrite": sa}`.

### 1.3 `scripts/attention-refresh.py` (`REQ-011`)
- `build_refresh_reminder(session_id: str, total_tokens: int, ledger: Ledger, conv_id: str = "", artifact_dir: str = "") -> str`:
  - Computes `pct = min(100, round(total_tokens / 128000 * 100, 1))`.
  - Queries `ledger.audit_conversation_budget(conv_id)` when `conv_id` is available.
  - Appends a `[Context Telemetry: ~{total_tokens:,} tokens ({pct}% of 128k budget) | Workers: {unique_workers}]` status line.
  - When `total_tokens >= 80000` and `artifact_dir` is provided, writes `<artifact_dir>/session_checkpoint.md` containing the current timestamp, token count, worker count, and a compaction preservation notice, and instructs the agent to review `<artifact_dir>/session_checkpoint.md` if context compaction occurs.

### 1.4 `scripts/payload_validator.py` (`REQ-012`)
- `validate_no_raw_log_dump(summary: str) -> Tuple[bool, Optional[str]]`:
  - Rejects `summary` if `\x1b[` (ANSI escape sequence) is present.
  - Rejects `summary` if it contains $\ge 4$ Python traceback file lines (`File ".*", line \d+`) or `=== test session starts ===` when `len(summary) > 2000`.
  - Wired into both `validate_payload()` and `validate_payload_builtin()`.

### 1.5 `scripts/attention-check.py` (`REQ-013`)
- Update `check_walkthrough_requirement(payload, conv_id, min_mtime: Optional[float] = None) -> bool`:
  - Checks `os.path.isfile(target) and os.path.getsize(target) > 0`.
  - If `min_mtime is not None`, also verifies `os.path.getmtime(target) >= (min_mtime - 5.0)`.
  - In `main()`, queries `SELECT MIN(created_at) FROM work_items WHERE parent_conv_id = ? AND parent_turn_id = ?` and passes `min_mtime` to `check_walkthrough_requirement`.
