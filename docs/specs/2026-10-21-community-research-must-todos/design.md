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

### 1.5 `scripts/attention-check.py` (`REQ-013`, `REQ-014`)
- Update `check_walkthrough_requirement(payload, conv_id, min_mtime: Optional[float] = None) -> bool`:
  - Checks `os.path.isfile(target) and os.path.getsize(target) > 0`.
  - If `min_mtime is not None`, also verifies `os.path.getmtime(target) >= (min_mtime - 5.0)`.
  - In `main()`, queries `SELECT MIN(created_at) FROM work_items WHERE parent_conv_id = ? AND parent_turn_id = ?` and passes `min_mtime` to `check_walkthrough_requirement`.
- Update `Stop` `terminationReason` handling (`REQ-014`):
  - `OK_REASONS = {"model_stop", "NO_TOOL_CALL", "TERMINAL_STEP_TYPE", "INJECTED_RESPONSE"}`
  - `TIMEOUT_REASONS = {"max_steps_exceeded", "MAX_INVOCATIONS", "MAX_FORCED_INVOCATIONS", "MAX_TOKEN_BUDGET_EXCEEDED"}`
  - `ERROR_REASONS = {"ERROR", "USER_CANCELED"}`
  - If `error` or `term_reason in ERROR_REASONS`: `event_type = Event.WORK_TERMINATED_ERROR.name`
  - Else if `term_reason in TIMEOUT_REASONS`: `event_type = Event.WORK_TIMED_OUT.name`
  - Else if `fully_idle and term_reason in OK_REASONS and not error`: `event_type = Event.WORK_TERMINATED_OK.name`

### 1.6 `scripts/common.py` (`REQ-014`)
- In `is_subagent(data)`:
  - After scanning `tokens` for `[ANTIGRAVITY_TOKEN:<uuid>]` against `WORK_PREPARED` in `Ledger`, if no token matched and `os.environ.get("AGY_DISABLE_SENDER_FALLBACK") != "1"`, inspect the first JSON line (`step_index == 0`) of `transcript_path`.
  - If `first_step.get("source") == "SYSTEM"` and `first_step.get("type") == "SYSTEM_MESSAGE"`, search `content` for `r"\bsender=([0-9a-fA-F\-]{36})\b"`. If matched and `parent_conv_id != conv_id`, return `(True, False, 0, parent_conv_id, "0")`.

### 1.7 `scripts/system_audit.py` & `tests/test_e2e_hook_pipeline.py` (`REQ-015`)
- `scripts/system_audit.py`:
  - `audit_ecosystem(plugins_root: Path, config_root: Path, db_path: Path, repair_db: bool = False) -> dict`:
    - Checks all `hooks.json` files across `config_root` and `plugins_root/*` for valid matchers covering Antigravity 2.0 tools (`write_file`, `edit_file`, `read_file`, `invoke_subagent`) and existing target scripts.
    - Checks all `agents/*.md` files for valid YAML frontmatter and Antigravity 2.0 tool names (`read_file`, `write_file`).
    - Runs `validate_plugin_surface()` on every plugin under `plugins_root`.
    - Audits `db_path` (`attention_guard.db`) for `work_items` status distribution and optionally cleans up stale `ACTIVE`/`TIMED_OUT` rows older than 1 hour when `--repair-db` is passed.
- `tests/test_e2e_hook_pipeline.py`:
  - Executes the end-to-end hook pipeline across `spec-gate.py`, `enforce-delegation.py`, `inject-rules.py`, `record-tool-result.py`, `attention-check.py`, `attention-refresh.py`, `json-gate.py`, and `ast-gate.py` using actual `hooks.json` matchers and Antigravity 2.0 payloads (`NO_TOOL_CALL`, `write_file`, `edit_file`, flat `invoke_subagent`).
