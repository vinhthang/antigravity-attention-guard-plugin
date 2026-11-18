# Design: Lean Attention Guard v2.0.0

Sources: [spec.md](./spec.md), [decisions.md](./decisions.md)

## Components

| Requirement / AC | Path and symbol | Responsibility / change |
| --- | --- | --- |
| REQ-042 / AC-042-1, AC-042-2 | `hooks.json`; `scripts/enforce-delegation.py::main`, `emit_deny`, `check_destructive_command`, `check_test_tampering`; delete `scripts/{attention-check,attention-refresh,record-tool-result,fsm,payload_validator}.py`, `schemas/` | Restrict `hooks.json` to `PreToolUse` on mutating/shell/delegation tools; allow Primary/swarm/workflow edits and tests after universal safety checks; log `{"tool", "is_sub", "reason"}` on `PRIMARY_TOOL_DENIED`. |
| REQ-043 / AC-043-1, AC-043-2 | `scripts/inject-rules.py::main`; `scripts/common.py::scan_transcript_header`, `is_subagent` | Store `(token_id, may_delegate, remaining_depth, parent_conv_id)` on `tokens` without modifying `Model`; resolve `is_subagent()` via `tokens.claimed_by` or first `10` lines of `transcript.jsonl`. |
| REQ-044 / AC-044-1, AC-044-2 | `scripts/enforce-delegation.py::main`, `check_subagent_doom_loop`; `scripts/common.py::extract_active_bg_tasks`, `validate_no_raw_log_dump` | Enforce subagent recursion caps, 3x normalized command doom-loop breaker (`BREAKER_STATE_CHANGE`), active background-task fence, and raw-log-dump check on `send_message` without UUID JSON or `shell=True` `verify_cmd`. |
| REQ-045 / AC-045-1, AC-045-2 | `scripts/ledger.py::Ledger`; `scripts/diagnostics.py::main`; `scripts/sync_metrics.py` | Migrate `attention_guard.db` to `SCHEMA_VERSION = 3` (`tokens` + `events`), report `primary_denials` / `subagent_denials` / `denials_by_tool` in `diagnostics.py`, and keep `sync_metrics.py` compatible with `attention-metrics-server`. |
| REQ-046 / AC-046-1, AC-046-2 | `rules/AGENTS.md`, `templates/{EXECUTOR,COORDINATOR}.md`, `plugin.json`, `README.md`, `scripts/deploy_plugin.py`, `scripts/surface_validator.py`, `scripts/system_audit.py` | Slim `AGENTS.md` to `<= 4,000` chars, bump `plugin.json` to `"2.0.0"`, remove `schemas` requirement and prune retired `scripts/*.py` + `schemas/` in `deploy_plugin.py --deploy`, and align `system_audit.py`. |

## Interfaces and flow

- `Ledger` (`SCHEMA_VERSION = 3`):
  - `tokens(token_id TEXT PRIMARY KEY, claimed INTEGER DEFAULT 0, claimed_by TEXT, may_delegate INTEGER DEFAULT 0, remaining_depth INTEGER DEFAULT 0, parent_conv_id TEXT, created_at REAL)`
  - `events(event_id TEXT PRIMARY KEY, type TEXT, payload TEXT, created_at REAL)`
  - Helper methods: `issue_token(token_id, *, may_delegate, remaining_depth, parent_conv_id)`, `get_claimed_token_by_conv(conv_id)`, `get_token(token_id)`, `claim_token(token_id, conv_id)`, `insert_event(...)`.
- `is_subagent(data: dict, ledger: Ledger | None = None) -> tuple[bool, bool, int, str | None, str | None]`:
  Returns `(is_sub, may_delegate, remaining_depth, parent_conv_id, parent_turn_id)` (preserving 5-tuple return signature for clean caller ergonomics). Checks `ledger.get_claimed_token_by_conv(conv_id)` first; otherwise reads at most `10` lines (`<= 64 KB` per line) from `transcriptPath` to match `[ANTIGRAVITY_TOKEN:<uuid>]` (skipping tokens where `parent_conv_id == conv_id`) or `first_system_sender`.
- `enforce-delegation.py` control flow:
  1. Check `AGY_ATTENTION_GUARD_KILL_SWITCH == "1"` / `AGY_ATTENTION_GUARD_OBSERVATION_MODE == "1"`.
  2. Run `check_destructive_command(cmd)` on `run_command` and `check_test_tampering(target_file, args)` on `MUTATION_TOOLS`.
  3. Call `is_subagent(data, ledger=ledger)`. If `not is_sub`, return `{"decision": "allow"}`.
  4. If `is_sub`: enforce recursion cap (`invoke_subagent`/`manage_subagents`/`run_workflow`/`swarm`), `check_subagent_doom_loop()` on `run_command`, `record_subagent_file_edit()` on `MUTATION_TOOLS`, and `extract_active_bg_tasks()` + `validate_no_raw_log_dump()` on `send_message`.

## Boundaries and recovery

- Legacy SQLite upgrade: When `PRAGMA user_version < 3` on an existing `attention_guard.db`, `_init_db()` inspects `PRAGMA table_info(tokens)` and issues `ALTER TABLE tokens ADD COLUMN ...` only for missing columns, preserving existing token/event history without locking or dropping legacy tables.
- Missing DB resilience: `diagnostics.py --metrics --json` returns `{"PRIMARY_TOOL_DENIED": 0, "primary_denials": 0, "subagent_denials": 0, "denials_by_tool": {}}` with exit `0` when `attention_guard.db` is absent.
- Deployment pruning: `deploy_plugin.py --deploy` verifies `verify_source_bundle()` before mutating `target_dir`, removes `target_dir/schemas` if absent in `source_dir`, and deletes stale `.py`/`.md` files in `target_dir/scripts`, `target_dir/rules`, and `target_dir/templates` that no longer exist in `source_dir`.

## Dependencies and unresolved design work

None.
