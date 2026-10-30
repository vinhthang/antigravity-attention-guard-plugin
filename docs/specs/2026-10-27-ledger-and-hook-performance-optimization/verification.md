# Verification Evidence: SQLite Ledger Indexing, Schema Gating, Single-Pass Transcript Caching & Surface Validation Fixes (`2026-10-27-ledger-and-hook-performance-optimization`)

## 1. Automated Unit & Integration Test Suite (`REQ-016`, `REQ-017`, `REQ-018`, `REQ-019`, `REQ-020`, `REQ-021`)

- **Execution Attempt ID**: `ffc21985-fa84-443a-b6f5-d9ca389fc3f0`
- **Artifacts Verified**: `scripts/ledger.py`, `scripts/common.py`, `scripts/enforce-delegation.py`, `scripts/attention-check.py`, `scripts/inject-rules.py`, `scripts/surface_validator.py`, `scripts/system_audit.py`, `tests/test_ledger_performance.py`, `tests/test_surface_validator.py`
- **Command**: `rtk pytest`
- **Verbatim Output**:
```text
Pytest: 185 passed
```
- **Verified Requirements**:
  - `Verified: REQ-016` — `test_case_sensitive_like_and_indexes` in `tests/test_ledger_performance.py` confirms `PRAGMA case_sensitive_like = 1`, `EXPLAIN QUERY PLAN` index search (`SEARCH events USING INDEX sqlite_autoindex_events_1`) instead of full-table scan, and presence of secondary indexes (`idx_events_type_created`, `idx_events_created_at`, `idx_work_items_parent`, `idx_work_items_status`, `idx_tokens_claimed_by`).
  - `Verified: REQ-017` — `test_ledger_prune_and_opportunistic_throttle` in `tests/test_ledger_performance.py` confirms `Ledger.prune()` and throttled `_prune_opportunistically()` delete expired transient (`SUBAGENT_COMMAND`, `SUBAGENT_FILE_EDIT`) and historical rows while preserving recent/active records.
  - `Verified: REQ-018` — `test_init_db_user_version_gating` in `tests/test_ledger_performance.py` confirms `PRAGMA user_version = 2` (`SCHEMA_VERSION = 2`) and zero `executescript` / `ALTER TABLE` invocations on subsequent `Ledger()` instantiations.
  - `Verified: REQ-019` — `test_single_pass_parse_transcript_cache` and `test_parse_transcript_later_system_message_not_misclassified_as_subagent` in `tests/test_ledger_performance.py` confirm single-pass `parse_transcript()` caching across `get_turn_state()`, `is_subagent()`, and `is_plan_execution_active()`.
  - `Verified: REQ-020` — `test_push_metric_async_opt_in` in `tests/test_ledger_performance.py` confirms `_push_metric_async()` is skipped by default unless `ATTENTION_METRICS_PUSH_ENABLED=1` or `ATTENTION_METRICS_API_KEY` is configured.
  - `Verified: REQ-021` — `test_validate_plugin_surface_home_relative_script_path` and `test_valid_plugin_surface_agent_translator` in `tests/test_surface_validator.py` confirm `~/.gemini/.../scripts/*.py` expansion and zero surface errors across all 5 installed plugins.

---

## 2. Live Ecosystem Audit & `attention_guard.db` Repair/Vacuum (`REQ-016`, `REQ-017`, `REQ-021`)

- **Command**: `rtk python3 scripts/system_audit.py --repair-db`
- **Verbatim Output**:
```text
=== Antigravity Ecosystem Audit ===
Overall Valid: True
Total Errors : 0

--- Plugins (5) ---
  [PASS] agent-translator (/Users/thanghoang/github/agent-translator)
  [PASS] ai-review-plugin (/Users/thanghoang/github/ai-review-plugin)
  [PASS] attention-guard (/Users/thanghoang/github/antigravity-attention-guard-plugin)
  [PASS] gitleaks-guard (/Users/thanghoang/.gemini/config/plugins/gitleaks-guard)
  [PASS] spec-driven-plugin (/Users/thanghoang/github/spec-driven-plugin)

--- SQLite Ledger (/Users/thanghoang/.gemini/antigravity/attention_guard.db) ---
  Total Work Items: 185
  Counts Breakdown: {'ACTIVE': 11, 'COMPLETED': 130, 'TIMED_OUT': 44}
  Repairs Executed: {'active_marked_terminated': 8, 'stale_timed_out_deleted': 44, 'prune': {'events_deleted': 2, 'work_items_deleted': 0, 'tokens_deleted': 0}, 'events_deleted': 2, 'work_items_deleted': 0, 'tokens_deleted': 0}
```
- **Live Database Schema & Compaction Check**:
```text
user_version: 2
indexes: ['sqlite_autoindex_turns_1', 'sqlite_autoindex_tokens_1', 'sqlite_autoindex_events_1', 'sqlite_autoindex_work_items_1', 'sqlite_autoindex_session_stats_1', 'sqlite_autoindex_session_refresh_state_1', 'idx_events_type_created', 'idx_events_created_at', 'idx_work_items_parent', 'idx_work_items_status', 'idx_tokens_claimed_by']
size_mb: 1.91 (compacted from 15.5 MB via prune + VACUUM)
```

---

## 3. DeepSeek Harness Plugin Parity (`dsh-attention-guard-plugin`, `REQ-022`)

- **Execution Attempt ID**: `7718c8e6-e17f-4ba6-86dc-05bcaea1efd3`
- **Command**: `cd /Users/thanghoang/github/dsh-attention-guard-plugin && rtk pnpm test && rtk pnpm run typecheck && rtk pnpm run build`
- **Verbatim Output**:
```text
$ vitest run

 RUN  v1.6.1 /Users/thanghoang/github/dsh-attention-guard-plugin

 ✓ tests/rtk.spec.ts (21)
 ✓ tests/circuit-breaker.spec.ts (16)
 ✓ tests/guards.spec.ts (16)
 ✓ tests/plugin.spec.ts (9)

 Test Files  4 passed (4)
      Tests  62 passed (62)
   Start at  21:10:21
   Duration  307ms (transform 157ms, setup 0ms, collect 215ms, tests 163ms, environment 0ms, prepare 206ms)

$ tsc --noEmit
$ tsc
```
- **Verified Requirement**: `Verified: REQ-022`
