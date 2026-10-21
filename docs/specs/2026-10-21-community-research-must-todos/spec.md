# Specification: Community & Literature Must-To-Do Hardening for Attention Guard

## 1. Overview & Research Synthesis
A comprehensive survey of 2025–2026 agentic coding research and open-source community harnesses across GitHub, Reddit (`r/ClaudeAI`, `r/LocalLLaMA`), and academic literature identified seven high-leverage gaps in `attention-guard`:
1. **Antigravity 2.0 Tool & Argument Schema Parity**: Modern Antigravity 2.0 uses `write_file` / `edit_file` with `Path` (capital `P`) and flat `invoke_subagent` parameters alongside legacy `write_to_file` / `replace_file_content` (`TargetFile`) and `Subagents=[...]`.
2. **Test-Tampering Prevention** (GitHub `hahahahahahahahah6/agent-guard`): Subagents under retry pressure can manufacture a false GREEN by adding `@pytest.mark.skip`, `pytest.xfail`, `@unittest.skip`, `.skip(`, or `assert True` to test files.
3. **Subagent Doom-Loop Circuit Breaker** (GitHub `claude-guard-hooks`, Reddit `r/ClaudeAI`): Subagents can loop on identical failing shell commands without editing any files, burning tokens until the 300s watchdog expires.
4. **Destructive Git/Shell Command Guard** (GitHub `dwarvesf/claude-guardrails`, `RULE[tdd.md]`): Sweeping destructive commands (`git reset --hard`, `git clean -fd`, `git checkout -- .`, `git push --force`) were prohibited only in Markdown prose rather than mechanically blocked in `enforce-delegation.py`.
5. **Context Budget Status Gauge & Pre-Compaction Checkpoint** (Anthropic *Context Engineering*, GitHub `alibaizhanov/mengram`, Reddit `PreCompact` / `StatusLine` hooks): `attention-refresh.py` injected a static reminder without reporting live token usage, worker counts, or writing a deterministic state checkpoint before high-token compaction.
6. **Observation Masking / Raw Terminal Dump Guard** (NeurIPS/arXiv:2508.21433 *"The Complexity Trap"*, Anthropic *Tool-Result Clearing*): Subagents returning raw ANSI escape codes or multi-thousand-character stack traces inside `summary` pollute the Primary Agent's context window.
7. **Turn-Scoped Walkthrough Freshness Verification** (`obra/superpowers` Two-Stage Review): `attention-check.py` checked only whether `walkthrough.md` existed on disk, not whether it was updated during or after the current turn's subagent execution.

---

## 2. Normative Requirements (EARS Syntax)

### `REQ-007` — Antigravity 2.0 Tool & Argument Schema Parity
- **WHEN** `enforce-delegation.py` or `inject-rules.py` inspects a `PreToolUse` payload, **THE** hooks **SHALL** support both Antigravity 2.0 tool schemas (`write_file`, `edit_file` with `Path`, and flat `invoke_subagent` arguments) and legacy 1.x schemas (`write_to_file`, `replace_file_content`, `multi_replace_file_content` with `TargetFile`, and `Subagents=[...]`).
- **Acceptance Criteria**:
  - `enforce-delegation.py` intercepts `write_file` and `edit_file` (extracting `Path` as well as `TargetFile`/`target_file`/`path`/`file_path`).
  - `inject-rules.py` injects tokens, role rules, and `EVIDENCE_BOUNDARY` for both `args["Subagents"]` list payloads and flat `invoke_subagent` payloads (`TypeName`, `Role`, `Prompt`).

### `REQ-008` — Mechanical Test-Tampering Guard
- **WHEN** a subagent or primary agent invokes a file-mutation tool targeting a test file (`test_*.py`, `*_test.py`, `*.test.ts`, `*.spec.ts`, `*_test.go`, or path under `tests/`), **THE** `enforce-delegation.py` hook **SHALL** inspect the new/replacement content and deny the edit if it introduces test-skipping markers (`@pytest.mark.skip`, `@pytest.mark.xfail`, `@unittest.skip`, `pytest.skip(`, `pytest.xfail(`, `it.skip(`, `describe.skip(`, `test.skip(`, `t.Skip(`) or `assert True` that was not already present in the target text.
- **Acceptance Criteria**:
  - `check_test_tampering(target_file: str, args: dict) -> Optional[str]` is implemented in `scripts/enforce-delegation.py`.
  - Edits adding `@pytest.mark.skip` or `assert True` to a test file are denied with a diagnostic reason.

### `REQ-009` — Subagent Doom-Loop Circuit Breaker
- **WHEN** a subagent executes `run_command`, **THE** `enforce-delegation.py` hook **SHALL** record the command execution in the SQLite ledger and deny execution if the subagent runs the exact same normalized command $\ge 3$ consecutive times without an intervening file modification in the same turn.
- **Acceptance Criteria**:
  - `check_subagent_doom_loop(ledger: Ledger, conv_id: str, turn_id: str, tool_name: str, args: dict) -> Optional[str]` is implemented in `scripts/enforce-delegation.py`.
  - File mutations by the subagent record a `SUBAGENT_FILE_EDIT` reset marker; 3 identical consecutive `run_command` calls without a file edit trigger a `deny` decision.

### `REQ-010` — Mechanical Destructive Command Guard
- **WHEN** any agent or subagent invokes `run_command`, **THE** `enforce-delegation.py` hook **SHALL** mechanically deny sweeping destructive commands (`git reset --hard`, `git clean -fd` / `-f` / `-fx`, `git checkout -- .`, `git restore .`, `git push --force` / `-f` without `--force-with-lease`).
- **Acceptance Criteria**:
  - `check_destructive_command(cmd_str: str) -> Optional[str]` is implemented in `scripts/enforce-delegation.py` and blocks all listed destructive patterns while allowing safe commands (`git status`, `git push origin main`, `git push --force-with-lease`, `git checkout -b feat`).

### `REQ-011` — Dynamic Context Budget Status Gauge & Pre-Compaction Checkpoint
- **WHEN** `scripts/attention-refresh.py` triggers a turn refresh, **THE** hook **SHALL** include live session telemetry (`Estimated Context Tokens`, `Context Budget %`, `Prepared Workers`, `Denied Actions`) in the injected ephemeral message, and **WHEN** `total_tokens >= 80000`, **THE** hook **SHALL** write a deterministic `session_checkpoint.md` file in the conversation's artifact directory summarizing session metrics and recent ledger events.
- **Acceptance Criteria**:
  - `build_refresh_reminder(session_id: str, total_tokens: int, ledger: Ledger, conv_id: str = "", artifact_dir: str = "") -> str` includes live token and worker telemetry.
  - When `total_tokens >= 80000` and `artifact_dir` is writable, `session_checkpoint.md` is created on disk and referenced in the reminder.

### `REQ-012` — Observation Masking / Raw Terminal Dump Guard in `payload_validator.py`
- **WHEN** `scripts/payload_validator.py` validates a subagent JSON payload, **THE** validator **SHALL** reject `summary` strings that contain raw ANSI terminal escape codes (`\x1b[`) or unformatted raw traceback/pytest log dumps ($\ge 4$ consecutive `File "...", line ...` frames or `=== test session starts ===` blocks exceeding 2,000 chars).
- **Acceptance Criteria**:
  - `validate_no_raw_log_dump(summary: str) -> Tuple[bool, Optional[str]]` is enforced in both `validate_payload()` and `validate_payload_builtin()`.

### `REQ-013` — Turn-Scoped Walkthrough Freshness Verification
- **WHEN** `scripts/attention-check.py` verifies `walkthrough.md` on the `Stop` hook after subagents completed work in the current turn, **THE** hook **SHALL** verify both that `walkthrough.md` is non-empty and that its modification time (`os.path.getmtime`) is not older than the earliest `created_at` timestamp of the current turn's `work_items` (minus a 5-second clock tolerance).
- **Acceptance Criteria**:
  - `check_walkthrough_requirement(payload, conv_id, min_mtime: Optional[float] = None) -> bool` rejects stale `walkthrough.md` files modified before the current turn's subagent execution started.

### `REQ-014` — Antigravity 2.0 `Stop` `terminationReason` & `step_index: 0` Subagent Detection
- **WHEN** `scripts/attention-check.py` evaluates a subagent `Stop` event, **THE** hook **SHALL** recognize Antigravity 2.0 `ExecutorTerminationReason` values (`"NO_TOOL_CALL"`, `"TERMINAL_STEP_TYPE"`, `"INJECTED_RESPONSE"`, `"model_stop"` as `WORK_TERMINATED_OK`; `"MAX_INVOCATIONS"`, `"MAX_FORCED_INVOCATIONS"`, `"MAX_TOKEN_BUDGET_EXCEEDED"`, `"max_steps_exceeded"` as `WORK_TIMED_OUT`; and `"ERROR"` or non-empty `error` as `WORK_TERMINATED_ERROR`), and **WHEN** `scripts/common.py::is_subagent(data)` evaluates a transcript where `step_index == 0` is a `SYSTEM_MESSAGE` containing `sender=<parent_uuid>`, **THE** helper **SHALL** identify the conversation as a subagent even if no token was injected.
- **Acceptance Criteria**:
  - `attention-check.py` transitions subagent `work_items` to `'COMPLETED'` and records `WORK_TERMINATED_OK` when `terminationReason == "NO_TOOL_CALL"` and `fullyIdle` is `True`.
  - `common.py::is_subagent(data)` returns `(True, ...)` when `step_index == 0` has `type == "SYSTEM_MESSAGE"` and `sender=<parent_uuid>` with `parent_uuid != conv_id` (unless `AGY_DISABLE_SENDER_FALLBACK=1`).

### `REQ-015` — Cross-Plugin End-to-End Hook Pipeline Integration Test & Ecosystem Audit CLI
- **WHEN** the test suite or pre-deployment audit runs, **THE** repository **SHALL** include an end-to-end subprocess hook pipeline integration test (`tests/test_e2e_hook_pipeline.py`) that executes real `hooks.json` matchers and scripts across `PreInvocation`, `PreToolUse`, `PostToolUse`, and `Stop`, and **SHALL** provide `scripts/system_audit.py` to audit `hooks.json`, `agents/*.md`, `docs/specs/`, plugin surfaces, and SQLite `attention_guard.db` health across all installed plugins.
- **Acceptance Criteria**:
  - `tests/test_e2e_hook_pipeline.py` verifies the complete Primary Agent + Subagent lifecycle (`OPEN` -> `HANDOFF_PENDING` -> `EXECUTION_ACTIVE` -> `WORK_TERMINATED_OK` (`COMPLETED`) -> Walkthrough Gate -> `CLOSED`) using Antigravity 2.0 payloads (`NO_TOOL_CALL`, `edit_file`, `write_file`, flat `invoke_subagent`).
  - `scripts/system_audit.py --json` audits all installed plugins and SQLite `attention_guard.db` (including `--repair-db` to clean up stale `TIMED_OUT`/`ACTIVE` orphan rows).
