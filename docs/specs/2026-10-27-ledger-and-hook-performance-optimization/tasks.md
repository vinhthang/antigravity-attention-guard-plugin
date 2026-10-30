# Execution Tasks: SQLite Ledger Indexing, Schema Gating & Hook Performance Optimization (`2026-10-27-ledger-and-hook-performance-optimization`)

## Step 1: TDD Red Phase — Write Failing Performance & Regression Tests
- [x] **Task 1.1**: Add tests in `tests/test_ledger_performance.py` verifying `PRAGMA case_sensitive_like = ON` and B-tree index usage (`EXPLAIN QUERY PLAN`) for `events` prefix and type queries (`REQ-016`).
- [x] **Task 1.2**: Add tests in `tests/test_ledger_performance.py` verifying `Ledger.prune()`, throttled `Ledger._prune_opportunistically()`, and `system_audit.py --repair-db` pruning + `VACUUM` (`REQ-017`).
- [x] **Task 1.3**: Add tests in `tests/test_ledger_performance.py` verifying `PRAGMA user_version` schema gating in `Ledger._init_db()` (zero `CREATE TABLE` / `ALTER TABLE` statements on subsequent instantiations) (`REQ-018`).
- [x] **Task 1.4**: Add tests in `tests/test_ledger_performance.py` verifying `parse_transcript()` single-pass caching across `get_turn_state()`, `is_subagent()`, and `is_plan_execution_active()` (`REQ-019`).
- [x] **Task 1.5**: Add tests in `tests/test_ledger_performance.py` verifying `_push_metric_async()` is skipped by default unless `ATTENTION_METRICS_PUSH_ENABLED=1` or `ATTENTION_METRICS_API_KEY` is set (`REQ-020`).
- [x] **Task 1.6**: Add tests in `tests/test_surface_validator.py` verifying `~/.../scripts/*.py` expansion in `surface_validator.py` (`REQ-021`).

## Step 2: TDD Green Phase — Implement Fixes Across Scripts
- [x] **Task 2.1**: Update `scripts/ledger.py` with `PRAGMA case_sensitive_like = ON`, `SCHEMA_VERSION = 2` gating, secondary indexes, `prune()`, throttled `_prune_opportunistically()`, and opt-in `_push_metric_async()` (`REQ-016`, `REQ-017`, `REQ-018`, `REQ-020`).
- [x] **Task 2.2**: Update `scripts/common.py`, `scripts/enforce-delegation.py`, `scripts/attention-check.py`, `scripts/inject-rules.py`, and `scripts/record-tool-result.py` to use single-pass `parse_transcript()` caching and shared `Ledger` instances (`REQ-019`).
- [x] **Task 2.3**: Update `scripts/system_audit.py` (`audit_sqlite_ledger` repair + prune + `VACUUM`) and `scripts/surface_validator.py` (`~/` path handling), and repair the two surface issues in `~/.gemini/config/plugins/agent-translator` (`REQ-017`, `REQ-021`).

## Step 3: Live Database Cleanup & End-to-End Verification
- [x] **Task 3.1**: Run `rtk python3 scripts/system_audit.py --repair-db` to clean, index, and `VACUUM` `~/.gemini/antigravity/attention_guard.db` (`REQ-016`, `REQ-017`, `REQ-021`).
- [x] **Task 3.2**: Update `dsh-attention-guard-plugin` (`src/guards.ts`, `src/circuit-breaker.ts`, `src/rtk.ts`, `src/index.ts`, `src/schema.ts`, and `tests/guards.spec.ts`) for guard & performance parity, and verify with `rtk pnpm test` and `rtk pnpm run build` (`REQ-022`).
- [x] **Task 3.3**: Run full pytest suite (`rtk pytest`) and record verbatim evidence in `docs/specs/2026-10-27-ledger-and-hook-performance-optimization/verification.md` (`REQ-016`, `REQ-017`, `REQ-018`, `REQ-019`, `REQ-020`, `REQ-021`, `REQ-022`).
