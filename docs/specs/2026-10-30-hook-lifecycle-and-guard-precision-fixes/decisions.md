# Architectural Decision Records: Work Item Lifecycle Hygiene, Doom-Loop Signature Normalization & Guard Precision Fixes

## ADR-001: Reconcile Unclaimed `PreToolUse` Tokens & `manage_subagents` Kills (`REQ-023`)
- **Status**: Proposed
- **Addresses**: `REQ-023`
- **Context**: `inject-rules.py` creates `work_items` rows with `status = 'ACTIVE'` during `PreToolUse`. If a sibling `PreToolUse` hook (`spec-gate.py`) rejects `invoke_subagent`, `PostToolUse` (`record-tool-result.py`) never runs and the token remains `claimed = 0`. Additionally, when the Primary Agent terminates a hung subagent via `manage_subagents(Action="kill" | "kill_all")`, no hook updates `work_items.status`. Both cases leave `active_count > 0` in `attention-check.py`, which skips `check_walkthrough_requirement()`.
- **Decision**:
  1. Introduce `Ledger.reconcile_orphaned_work_items(parent_conv_id, parent_turn_id, current_step_idx=None)` (invoked from `inject-rules.py` and `attention-check.py`) to transition `ACTIVE` `work_items` rows to `TERMINATED` when their token is unclaimed (`claimed = 0`), a `WORK_PREPARED` event exists for that `work_id`, and no corresponding `PostToolUse` `HANDOFF_ACCEPTED` event exists for that `step_idx` (when a newer `step_idx` is being prepared or when Primary Agent `Stop` runs).
  2. Intercept `manage_subagents` / `default_api:manage_subagents` in `enforce-delegation.py` when called by the Primary Agent: on `Action == "kill"`, mark `ACTIVE` work items claimed by any ID in `ConversationIds` as `TERMINATED`; on `Action == "kill_all"`, mark all `ACTIVE` work items for `parent_conv_id` as `TERMINATED`.
  3. In `attention-check.py`, ensure any `is_sub` stop with `fully_idle=True` defaults unrecognized `terminationReason` values to `WORK_TERMINATED_ERROR` (if matching `error|cancel|kill|abort`) or `WORK_TERMINATED_OK` so `work_items` never remain `ACTIVE` after a subagent stops.

## ADR-002: Command-Signature Normalization for Subagent Doom-Loop Detection (`REQ-024`)
- **Status**: Proposed
- **Addresses**: `REQ-024`
- **Context**: Subagents polling background tasks (`translation_runner.log`, `cbc_calls.jsonl`, `pgrep -P <pid>`) bypassed `check_subagent_doom_loop()` by changing `tail -n 25` to `tail -n 35`, `wc -l`, or `lines[-25:]` -> `lines[-26:]`.
- **Decision**: Implement `normalize_command_signature(cmd: str) -> str` in `scripts/enforce-delegation.py` (and `normalizeCommandSignature(cmd: string)` in `dsh-attention-guard-plugin/src/circuit-breaker.ts`) that normalizes read-only file-polling commands (`tail`, `head`, `wc`, or `python3 -c` reading lines from a log/jsonl/txt file) to `POLL_FILE:<path>` and process-polling commands (`pgrep`, `ps` without state mutation) to `POLL_PROC:<target>`, and append explicit remediation instructions to the circuit-breaker denial message.

## ADR-003: Language-Scoped, Statement-Aware Test Tampering Detection (`REQ-025`)
- **Status**: Proposed
- **Addresses**: `REQ-025`
- **Context**: `check_test_tampering()` blocked authoring `tests/guards.spec.ts` because `"@pytest.mark.skip"` appeared inside a string literal in a `.spec.ts` file.
- **Decision**: Scope `TEST_TAMPER_PATTERNS` by file extension (`.py` -> pytest/unittest/`assert True`; `.ts`/`.tsx`/`.js`/`.jsx` -> `it.skip(`/ `describe.skip(`/ `test.skip(`; `.go` -> `t.Skip(`) and evaluate added lines after stripping comments and double/single/backtick-quoted string literals (except when the marker itself is the statement being executed), preventing false positives on string-literal test fixtures while still blocking real skip decorators/calls.

## ADR-004: Normalize Backslash-Newline Line Continuations in `check_destructive_command()` (`REQ-026`)
- **Status**: Proposed
- **Addresses**: `REQ-026`
- **Context**: `shlex.split()` on a command containing `\\\n` preserved `\n` as a token, which `norm = tgt.rstrip("/").strip()` reduced to `""`, causing `rm -rf \\\n "/valid/path"` to be rejected as `catastrophic rm targeting '\n'`.
- **Decision**: Collapse `\\\r?\n` line continuations into spaces prior to splitting subcommands and skip whitespace-only target tokens in both `scripts/enforce-delegation.py` and `dsh-attention-guard-plugin/src/guards.ts`.
