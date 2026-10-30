# Technical Design: Work Item Lifecycle Hygiene, Doom-Loop Signature Normalization & Guard Precision Fixes

## 1. Architectural Mapping to Requirements

| Component | File(s) | Requirement IDs |
|---|---|---|
| Orphaned `PreToolUse` & `manage_subagents` Kill Reconciliation | `scripts/ledger.py`, `scripts/inject-rules.py`, `scripts/enforce-delegation.py`, `scripts/attention-check.py`, `scripts/system_audit.py` | `Addresses: REQ-023` |
| Polling-Signature Normalization in Doom-Loop Circuit Breaker | `scripts/enforce-delegation.py`, `dsh-attention-guard-plugin/src/circuit-breaker.ts` | `Addresses: REQ-024` |
| Language-Scoped & String-Literal-Aware Test Tampering Guard | `scripts/enforce-delegation.py`, `dsh-attention-guard-plugin/src/guards.ts` | `Addresses: REQ-025` |
| Backslash-Newline Continuation Normalization in Destructive Command Guard | `scripts/enforce-delegation.py`, `dsh-attention-guard-plugin/src/guards.ts` | `Addresses: REQ-026` |

---

## 2. Detailed Component Design

### 2.1 Work Item Lifecycle Hygiene (`REQ-023`)

1. **`Ledger.reconcile_orphaned_work_items(self, parent_conv_id: str, parent_turn_id: str, current_step_idx: str | None = None) -> int` (`scripts/ledger.py`)**:
   - Queries `work_items` joined with `tokens` where `w.parent_conv_id = ? AND w.parent_turn_id = ? AND w.status = 'ACTIVE'`.
   - For each active work item `(work_id, step_idx)` whose token is unclaimed (`COALESCE(t.claimed, 0) == 0`):
     - If `current_step_idx is not None` and `str(step_idx) == str(current_step_idx)`: skip (currently being prepared).
     - Check if a `WORK_PREPARED` event exists for `work_id` (`event_id LIKE f"{parent_conv_id}_{parent_turn_id}_PreToolUse_{step_idx}_{work_id}_WORK_PREPARED"`).
     - If `WORK_PREPARED` exists and no `PostToolUse` `HANDOFF_ACCEPTED` event exists for `(parent_conv_id, parent_turn_id, step_idx)` (`event_id = f"{parent_conv_id}_{parent_turn_id}_PostToolUse_{step_idx}_invoke_HANDOFF_ACCEPTED"`):
       - Update `work_items SET status = 'TERMINATED', updated_at = ? WHERE work_id = ?`.
2. **Hook Integration (`scripts/inject-rules.py`, `scripts/enforce-delegation.py`, `scripts/attention-check.py`)**:
   - In `inject-rules.py`: call `ledger.reconcile_orphaned_work_items(parent_conv_id, str(turn_id), current_step_idx=str(step_idx))` before inserting new work items.
   - In `enforce-delegation.py`: when `not is_sub` and `tool_name in ("manage_subagents", "default_api:manage_subagents")`:
     - If `args.get("Action") == "kill"`: terminate `ACTIVE` `work_items` where `work_id IN (SELECT token_id FROM tokens WHERE claimed_by = ?)` for each ID in `args.get("ConversationIds") or []`.
     - If `args.get("Action") == "kill_all"`: terminate `ACTIVE` `work_items` where `parent_conv_id = ?`.
   - In `attention-check.py`:
     - On subagent `Stop` (`is_sub=True`, `fully_idle=True`), if `event_type is None`, set `event_type = Event.WORK_TERMINATED_ERROR.name` if `any(k in str(term_reason).lower() for k in ("error", "cancel", "kill", "abort"))` else `Event.WORK_TERMINATED_OK.name`.
     - Before computing `all_work_terminal` (subagent `Stop`) and before computing `active_count` (Primary Agent `Stop`), call `ledger.reconcile_orphaned_work_items(parent_conv_id_or_conv_id, str(turn_id))`.

### 2.2 Polling-Signature Normalization in Doom-Loop Circuit Breaker (`REQ-024`)

1. **`normalize_command_signature(cmd: str) -> str` (`scripts/enforce-delegation.py` & `dsh-attention-guard-plugin/src/circuit-breaker.ts`)**:
   - Strip leading `rtk`, `rtk proxy`, and `sudo` prefixes and collapse whitespace.
   - Strip leading `sleep <N> &&` or `rtk sleep <N> &&` prefix when chained before a status/process check.
   - **File-Polling Signature (`POLL_FILE:<path>`)**:
     - If the command invokes `tail`, `head`, `wc` on a target file path, or invokes `python`/`python3 -c` containing `open(` / `Path(` and `readlines` / `read_text` without write mode (`"w"`, `"a"`, `write_text`), extract the file path and return `f"POLL_FILE:{file_path}"`.
   - **Process-Polling Signature (`POLL_PROC:<target>`)**:
     - If the command invokes `pgrep` or `ps` (or `ps ... | grep ...`), extract the PID (`-P <pid>` / `-p <pid>`) or grep pattern and return `f"POLL_PROC:{target}"`.
   - Otherwise return `cmd.strip()`.
2. **Comparison & Guidance**:
   - Compare `normalize_command_signature(recorded_cmd) == normalize_command_signature(cmd_norm)` in `check_subagent_doom_loop()`.
   - Return:
     `f"Attention Guard: Subagent doom-loop circuit breaker. Command '{cmd_norm}' executed {identical_count + 1} times consecutively without intervening file edits. Do not poll processes or logs in a shell loop; return your current status or await async completion."`

### 2.3 Language-Scoped & Statement-Aware `check_test_tampering()` (`REQ-025`)

1. **Language Pattern Mapping**:
   - `.py`: `["@pytest.mark.skip", "@pytest.mark.xfail", "@unittest.skip", "pytest.skip(", "pytest.xfail(", "assert True"]`
   - `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs`: `["it.skip(", "describe.skip(", "test.skip("]`
   - `.go`: `["t.Skip("]`
   - Other test files: union of all patterns.
2. **Statement-Level Evaluation**:
   - Extract added lines (`line` in `replacement.splitlines()` not in `set(target.splitlines())`).
   - For each added line, strip trailing line comments (`#...` for Python, `//...` for TS/JS/Go) and replace quoted string literals (`"..."`, `'...'`, `` `...` ``) with empty placeholders `""` before checking if `pattern` appears in the unquoted code structure (handling `assert True` as a standalone statement/clause `r"\bassert\s+True\b"`).

### 2.4 Line-Continuation Normalization in `check_destructive_command()` (`REQ-026`)

1. **Pre-Split Normalization**:
   - Normalize `clean_cmd = re.sub(r"\\\r?\n", " ", cmd_str)` before splitting on `[;&|]+` and calling `shlex.split()`.
   - When inspecting `rm` targets, skip tokens where `tgt.strip() == ""` unless the original command explicitly passed an empty quoted argument (`""` or `''`).
