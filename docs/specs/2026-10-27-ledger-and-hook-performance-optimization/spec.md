# Specification: SQLite Ledger Indexing, Schema Gating, Single-Pass Transcript Caching & Surface Validation Fixes

**Feature ID**: `2026-10-27-ledger-and-hook-performance-optimization`  
**Status**: `approved`  
**Created**: `2026-10-27`  
**Version**: `1.0.0`  
**Sign-off**: `User Approved (2026-10-27)`  
**Precedence**: `spec.md` > `decisions.md` > `design.md` > `tasks.md`

---

## 1. Overview & Root Cause Summary

Production profiling and auditing of `attention-guard` and `~/.gemini/antigravity/attention_guard.db` (14.3 MB, >10,800 `SUBAGENT_COMMAND` rows) identified six defects causing multi-second hook latency on every tool call and turn stop:

1. **Bug 1 — Unindexed Full-Table Scans & Case-Insensitive `LIKE` (`REQ-016`)**:
   - Queries using `WHERE event_id LIKE ?` (`f"{conv_id}_%"`) and `WHERE type = 'WORK_PREPARED'` perform full-table scans over `events` because SQLite's `LIKE` operator is case-insensitive by default (`PRAGMA case_sensitive_like = OFF`), preventing use of the `BINARY`-collated `event_id TEXT PRIMARY KEY` B-tree, and because `events` and `work_items` lack secondary indexes.
2. **Bug 2 — No-Op `_prune_opportunistically()` & Unbounded Event Accumulation (`REQ-017`)**:
   - `Ledger._prune_opportunistically()` is a stub (`pass`), causing `SUBAGENT_COMMAND` and historical `events` rows to accumulate indefinitely without bound.
3. **Bug 3 — Redundant DDL & Failing `ALTER TABLE` Migrations on Every `Ledger()` Instantiation (`REQ-018`)**:
   - `Ledger._init_db()` runs 7 `CREATE TABLE IF NOT EXISTS` statements via `executescript()` and 5 `ALTER TABLE ... ADD COLUMN` statements (each raising and catching `sqlite3.OperationalError: duplicate column name`) 2–3 times per tool call.
4. **Bug 4 — Multiple Full-File Reads and JSON Parses of `transcript.jsonl` per Hook Call (`REQ-019`)**:
   - On every `PreToolUse` invocation, `transcript.jsonl` is opened and parsed line-by-line 3–4 separate times across `get_turn_state()`, `is_subagent()` (token scan + sender fallback), and `is_plan_execution_active()`.
5. **Bug 5 — Unconditional Outbound HTTPS POST & 1-Second `atexit` Join Stall on Turn Stop (`REQ-020`)**:
   - Every `STOP_REQUESTED` and `PRIMARY_TOOL_DENIED` event spawns a thread to `POST` to `https://attention-metrics-server.vinhthang.dev/api/metrics` even when no `ATTENTION_METRICS_API_KEY` is configured, and `atexit` blocks interpreter exit for up to `1.0s` (`t.join(timeout=1.0)`).
6. **Bug 6 — False-Positive `/.gemini/...` Regex Match in `surface_validator.py` & `agent-translator` Surface Errors (`REQ-021`)**:
   - `surface_validator.py` matches `r'(/[\w.\-]+.../scripts/...\.py)'` without a leading boundary check for `~`, turning `~/.gemini/config/plugins/agent-translator/scripts/...` into `/.gemini/...` and reporting 6 false-positive missing script errors, alongside 2 real surface discrepancies in `agent-translator`.

---

## 2. Normative Requirements (EARS Syntax)

### `REQ-016` — SQLite Case-Sensitive Prefix Queries & Secondary Indexes
- **WHEN** `Ledger` opens a SQLite connection or initializes `attention_guard.db`, **THE** ledger **SHALL** enable `PRAGMA case_sensitive_like = ON` on the connection and ensure secondary indexes exist on `events(type, created_at)`, `events(created_at)`, `work_items(parent_conv_id, parent_turn_id, status)`, `work_items(status, updated_at, created_at)`, and `tokens(claimed_by)`.
- **Acceptance Criteria**:
  - `EXPLAIN QUERY PLAN` for `SELECT type, payload FROM events WHERE event_id LIKE ?` reports `SEARCH events USING INDEX sqlite_autoindex_events_1` (PK B-tree range scan) rather than `SCAN events`.
  - `EXPLAIN QUERY PLAN` for `SELECT payload FROM events WHERE type = 'WORK_PREPARED' AND payload LIKE ?` and `work_items` parent lookups use their respective secondary indexes.

### `REQ-017` — Bounded Event Retention, Throttled Opportunistic Pruning & `--repair-db` Vacuuming
- **WHEN** `Ledger` is instantiated or `Ledger.prune()` / `system_audit.py --repair-db` is invoked, **THE** ledger **SHALL** prune transient subagent loop events (`SUBAGENT_COMMAND`, `SUBAGENT_FILE_EDIT`) older than 24 hours and historical `events`, terminal `work_items`, and `tokens` older than the retention window (default 7 days), throttled to run opportunistically at most once per hour during normal hook execution.
- **Acceptance Criteria**:
  - `Ledger.prune(retention_seconds=604800, transient_retention_seconds=86400)` deletes expired rows and updates the last-prune timestamp in `schema_metadata`.
  - `Ledger._prune_opportunistically()` skips database writes when the last prune occurred within `3600` seconds.
  - `system_audit.py --repair-db` prunes expired `events`, ensures all indexes exist, and runs `VACUUM` on `attention_guard.db`.

### `REQ-018` — Fast Schema Version Gating in `Ledger._init_db()`
- **WHEN** `Ledger._init_db()` runs on an already-initialized database whose `PRAGMA user_version` matches the current `SCHEMA_VERSION` (`>= 2`), **THE** ledger **SHALL** skip `executescript()` table creation and `ALTER TABLE` column migrations, and cache initialization state per `(db_path, st_mtime_ns)` within the current process.
- **Acceptance Criteria**:
  - Instantiating `Ledger(db_path)` a second time on an initialized database executes zero `CREATE TABLE` or `ALTER TABLE` statements.
  - Existing v0/v1 databases without `user_version == 2` are seamlessly migrated (columns and indexes added) and stamped with `PRAGMA user_version = 2`.

### `REQ-019` — Single-Pass `transcript.jsonl` Parsing & Process-Local Cache
- **WHEN** hook scripts (`enforce-delegation.py`, `attention-check.py`, `inject-rules.py`, `record-tool-result.py`, `attention-refresh.py`) inspect `transcript.jsonl`, **THE** `scripts/common.py` module **SHALL** parse `transcript.jsonl` in a single pass and cache the parsed summary keyed by `(abspath, mtime_ns, size)` so that `get_turn_state()`, `is_subagent()`, and `is_plan_execution_active()` read and parse the file at most once per hook process.
- **Acceptance Criteria**:
  - `parse_transcript(transcript_path)` returns cached turn state, subagent tokens, step-0 system sender, and parsed step records when the file's `(mtime_ns, size)` is unchanged.
  - Calling `get_turn_state()`, `is_subagent()`, and `is_plan_execution_active()` in the same hook execution opens and parses `transcript.jsonl` only once.
  - `is_subagent(data, ledger=None)` reuses an optional `Ledger` instance when provided.

### `REQ-020` — Non-Stalling, Opt-In Outbound Metrics Push
- **WHEN** `Ledger.insert_event()` records `PRIMARY_TOOL_DENIED` or `STOP_REQUESTED`, **THE** ledger **SHALL** only dispatch `_push_metric_async()` when `ATTENTION_METRICS_PUSH_ENABLED == "1"` or a non-empty `ATTENTION_METRICS_API_KEY` is set (and `AGY_DISABLE_METRICS_PUSH != "1"`), and **SHALL** bound any `atexit` thread join to at most `0.05s` total so hook exit is never stalled for 1 second.
- **Acceptance Criteria**:
  - By default (when neither `ATTENTION_METRICS_API_KEY` nor `ATTENTION_METRICS_PUSH_ENABLED=1` is set), `Ledger.insert_event(..., "STOP_REQUESTED")` spawns zero network threads and completes in $< 5\text{ms}$.

### `REQ-021` — Home-Relative (`~/`) Script Path Resolution in `surface_validator.py` & `agent-translator` Surface Fixes
- **WHEN** `scripts/surface_validator.py` scans `rules/*.md` and `skills/*/SKILL.md` for script paths, **THE** validator **SHALL** recognize leading `~/` paths (`~/.gemini/.../scripts/...`) and expand `~` via `os.path.expanduser()` instead of stripping `~` and checking `/.gemini/...`, and **THE** `agent-translator` plugin surface **SHALL** pass `system_audit.py` with zero errors.
- **Acceptance Criteria**:
  - `surface_validator.py` resolves `~/.gemini/config/plugins/.../scripts/<file>.py` using `os.path.expanduser()` and still flags genuinely non-existent `/abs/path/scripts/<file>.py` or `~/nonexistent/scripts/<file>.py` paths.
  - `rtk python3 scripts/system_audit.py` exits with code `0` (`Overall Valid: True`, `Total Errors: 0`).

### `REQ-022` — DeepSeek Harness (`dsh-attention-guard-plugin`) Guard & Performance Parity
- **WHEN** `dsh-attention-guard-plugin` intercepts shell command resolution and execution in DeepSeek Harness, **THE** plugin **SHALL** enforce parity with `antigravity-attention-guard-plugin` across destructive command blocking, doom-loop circuit breaking, test-tampering detection, cumulative context token salience, and cached RTK command rewriting.
- **Acceptance Criteria**:
  - `checkDestructiveCommand(cmd)` blocks `git reset --hard`, `git clean -f`/`-fd`, `git checkout .`/`-- .`, `git restore .`, `git push --force` (allowing `--force-with-lease`), and catastrophic `rm -rf` targets (`/`, `~`, `$HOME`, `.`, `..`, `.git`) in `ctx.shell.resolve` / `ctx.shell.execute`.
  - `checkTestTampering(cmd)` blocks shell commands writing test-skipping markers (`@pytest.mark.skip`, `pytest.skip(`, `it.skip(`, `describe.skip(`, `test.skip(`, `t.Skip(`, `assert True`) into test files.
  - `AttentionGuardCircuitBreaker` tracks consecutive identical command executions (`checkDoomLoop`, threshold `3`), cumulative session tokens (`totalSessionTokens`, `tokensSinceRefresh` with 40k refresh reminder), and expanded build/test runners (`cmake`, `ninja`, `pip`, `go build`, `npm run build`).
  - `rtk.ts` caches `checkRtkAvailable()` and `rewriteCommand()` results in memory to eliminate redundant `spawnSync` calls for repeated commands, and `pnpm test` + `pnpm run build` pass with 0 errors.
