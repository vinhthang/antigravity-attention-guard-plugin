# Specification: Work Item Lifecycle Hygiene, Doom-Loop Signature Normalization & Guard Precision Fixes

**Feature ID**: `2026-10-30-hook-lifecycle-and-guard-precision-fixes`  
**Status**: `approved`  
**Created**: `2026-10-30`  
**Version**: `1.0.0`  
**Sign-off**: `User Approved (2026-10-30)`  
**Precedence**: `spec.md` > `decisions.md` > `design.md` > `tasks.md`

---

## 1. Overview & Root Cause Summary

Auditing live telemetry in `~/.gemini/antigravity/attention_guard.db` (129 `work_items`, 46 `PRIMARY_TOOL_DENIED` events) after the Oct 27 performance optimization revealed four operational defects across `antigravity-attention-guard-plugin` and `dsh-attention-guard-plugin`:

1. **Defect 1 — Stuck `ACTIVE` Work Items Bypassing the `walkthrough.md` Gate (`REQ-023`)**:
   - `inject-rules.py` inserts `status = 'ACTIVE'` into `work_items` during `PreToolUse` (`matcher: "invoke_subagent"`). When another `PreToolUse` hook (`spec-gate.py`) denies `invoke_subagent`, `PostToolUse` (`record-tool-result.py`) never executes and no subagent claims the token (`claimed = 0`), leaving the `work_items` row stuck in `ACTIVE` (`72c311a4`, `dcc8ddcb`).
   - Similarly, when the Primary Agent terminates a subagent via `manage_subagents(Action="kill" | "kill_all")`, no hook updates the subagent's `work_items` row from `ACTIVE` to `TERMINATED` (`d551a1b2`, `93ab9a9b`).
   - Because `active_count > 0` remains true for that parent turn, `attention-check.py` takes the `elif active_count > 0: return emit({"decision": "allow"})` branch on Primary Agent `Stop`, silently bypassing the `walkthrough.md` verification gate.
2. **Defect 2 — Subagent Doom-Loop Circuit Breaker Bypass via Trivial Polling Variations (`REQ-024`)**:
   - `check_subagent_doom_loop()` checks exact command string equality (`recorded_cmd.strip() == cmd_norm`). Subagents polling background logs or processes bypass the 3-strike circuit breaker 10+ times in a row by varying line-count arguments (`tail -n 25 <file>` -> `tail -n 35 <file>` -> `wc -l <file>` -> `python3 -c "... lines[-25:]"` -> `lines[-26:]`) and receive no actionable instruction to stop shell polling.
3. **Defect 3 — False Positive in `check_test_tampering()` on Cross-Language & Quoted Test Fixtures (`REQ-025`)**:
   - `check_test_tampering()` scans all `TEST_TAMPER_PATTERNS` via raw substring matching regardless of target file language or whether the pattern is inside a quoted string literal/comment. Writing unit tests for tamper detection in `tests/guards.spec.ts` was blocked because `@pytest.mark.skip` appeared as a string literal test input inside a TypeScript `.spec.ts` file.
4. **Defect 4 — False Positive in `check_destructive_command()` on Backslash-Continued Multiline `rm -rf \` (`REQ-026`)**:
   - `check_destructive_command()` passes multiline commands containing `\\\n` line continuations directly to `shlex.split()`. When `rm -rf \` is followed by a newline, `\n` is tokenized and stripped to `""` (`norm = tgt.rstrip("/").strip()`), triggering a false-positive `catastrophic rm targeting '\n'` denial on valid paths.

---

## 2. Normative Requirements (EARS Syntax)

### `REQ-023` — Work Item Lifecycle Hygiene on Rejected `PreToolUse` and `manage_subagents` Kills
- **WHEN** `inject-rules.py` prepares a new subagent token, `enforce-delegation.py` intercepts `manage_subagents(Action="kill" | "kill_all")`, or `attention-check.py` evaluates `Stop`, **THE** plugin **SHALL** transition orphaned unclaimed `PreToolUse` work items and explicitly killed subagent work items from `ACTIVE` to `TERMINATED`, and **SHALL** ensure any `fully_idle=True` subagent `Stop` event transitions its claimed `ACTIVE` work item to a terminal status (`COMPLETED`, `FAILED`, or `TIMED_OUT`).
- **Acceptance Criteria**:
  - Calling `manage_subagents` with `Action="kill"` and `ConversationIds=[sub_conv_id]` transitions the corresponding `ACTIVE` `work_items` row (matched via `tokens.claimed_by = sub_conv_id`) to `TERMINATED`.
  - Calling `manage_subagents` with `Action="kill_all"` transitions all `ACTIVE` `work_items` rows for `parent_conv_id` to `TERMINATED`.
  - If `inject-rules.py` creates an `ACTIVE` `work_items` row at `step_idx_1` (`WORK_PREPARED` recorded, `tokens.claimed == 0`, and no `PostToolUse` `HANDOFF_ACCEPTED` recorded for `step_idx_1`), a subsequent `inject-rules.py` invocation at `step_idx_2 != step_idx_1` or Primary Agent `Stop` transitions that unclaimed `step_idx_1` row to `TERMINATED` so `check_walkthrough_requirement()` is never bypassed after real subagents complete.
  - All 4 stale `ACTIVE` work items in `~/.gemini/antigravity/attention_guard.db` (`93ab9a9b`, `d551a1b2`, `dcc8ddcb`, `72c311a4`) are cleaned up via `system_audit.py --repair-db`.

### `REQ-024` — Polling-Signature Normalization & Actionable Guidance in Doom-Loop Circuit Breaker
- **WHEN** `check_subagent_doom_loop()` in `scripts/enforce-delegation.py` (and `checkDoomLoop()` in `dsh-attention-guard-plugin/src/circuit-breaker.ts`) evaluates consecutive subagent commands without an intervening file edit, **THE** guard **SHALL** compare normalized command signatures (`normalize_command_signature(cmd)`) so repeated log/file-polling or process-polling commands targeting the same file or process with minor flag/slice variations count toward the 3-strike threshold, and **SHALL** include actionable remediation guidance in the denial message.
- **Acceptance Criteria**:
  - 3 consecutive log-polling commands targeting the same file (e.g. `rtk tail -n 25 /tmp/run.log`, `rtk tail -n 50 /tmp/run.log`, `rtk wc -l /tmp/run.log` or `python3 -c "... open('/tmp/run.log') ... lines[-25:]"` / `lines[-26:]`) without an intervening file edit are denied on the 3rd execution.
  - 3 consecutive process-polling commands targeting the same process/PID (e.g. `rtk pgrep -P 59170 -l`, `rtk pgrep -fl -P 59170`, `ps -p 59170 -o pid,comm`) without an intervening file edit are denied on the 3rd execution.
  - Distinct commands targeting different files or performing different build/test operations continue to reset the consecutive counter.
  - The denial message preserves the prefix `"Attention Guard: Subagent doom-loop circuit breaker. Command '...' executed 3 times consecutively without intervening file edits."` and appends guidance instructing the subagent not to busy-wait in a shell loop.

### `REQ-025` — Language-Scoped & Statement-Aware Test-Tampering Detection
- **WHEN** `check_test_tampering()` in `scripts/enforce-delegation.py` (and `checkTestTampering()` in `dsh-attention-guard-plugin/src/guards.ts`) inspects edits to a test file, **THE** guard **SHALL** scope tamper markers to the target test file's language ecosystem (`.py`, `.ts`/`.tsx`/`.js`/`.jsx`, `.go`) and ignore markers that appear solely inside comments or quoted string literals (such as test fixtures testing the tamper detector itself).
- **Acceptance Criteria**:
  - Writing a Python test file (`tests/test_feature.py`) that introduces executable `@pytest.mark.skip`, `pytest.skip('reason')`, or `assert True` is denied.
  - Writing a TypeScript test file (`tests/guards.spec.ts`) containing `"@pytest.mark.skip"` or `"pytest.skip("` inside string literals, or testing `checkTestTampering("echo 'it.skip(' >> tests/foo.spec.ts")`, is allowed.
  - Writing a TypeScript test file (`tests/feature.spec.ts`) that introduces an actual `it.skip(`, `describe.skip(`, or `test.skip(` call statement is denied.

### `REQ-026` — Multiline Backslash-Continuation Normalization in `check_destructive_command()`
- **WHEN** `check_destructive_command()` in `scripts/enforce-delegation.py` (and `checkDestructiveCommand()` in `dsh-attention-guard-plugin/src/guards.ts`) parses a shell command string, **THE** guard **SHALL** normalize POSIX backslash-newline line continuations (`\\\r?\n`) before splitting/tokenizing and ignore whitespace-only tokens when inspecting `rm` targets.
- **Acceptance Criteria**:
  - Multiline `rtk rm -rf \\\n  "/Users/thanghoang/Library/Application Support/JetBrains/..." \\\n  "/Users/thanghoang/.cache/github-copilot"` is allowed (`None`).
  - Catastrophic `rm -rf` commands (including multiline `rm -rf \\\n  /` or `rm -rf \\\n  ~` or `rm -rf .git`) remain blocked.
