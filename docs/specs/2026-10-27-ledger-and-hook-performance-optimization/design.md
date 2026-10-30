# Technical Design: SQLite Ledger Indexing, Schema Gating, Single-Pass Transcript Caching & Surface Validation Fixes

## 1. Architectural Mapping to Requirements

| Component | File(s) | Requirement IDs |
|---|---|---|
| SQLite Connection Pragmas, Schema Gating & Indexes | `scripts/ledger.py` | `Addresses: REQ-016`, `Addresses: REQ-018` |
| Opportunistic & Explicit Pruning + Vacuum Repair | `scripts/ledger.py`, `scripts/system_audit.py` | `Addresses: REQ-017` |
| Single-Pass Transcript Parser & `Ledger` Reuse | `scripts/common.py`, `scripts/enforce-delegation.py`, `scripts/attention-check.py`, `scripts/inject-rules.py`, `scripts/record-tool-result.py` | `Addresses: REQ-019` |
| Non-Stalling / Opt-In Metrics Push | `scripts/ledger.py` | `Addresses: REQ-020` |
| Home-Relative (`~/`) Script Validation & `agent-translator` Surface | `scripts/surface_validator.py`, `agent-translator` | `Addresses: REQ-021` |

---

## 2. Detailed Component Design

### 2.1 `scripts/ledger.py` (`REQ-016`, `REQ-017`, `REQ-018`, `REQ-020`)

1. **Connection Configuration (`REQ-016`)**:
   - In `_get_connection(self)`:
     ```python
     conn = sqlite3.connect(self.db_path, timeout=5.0)
     conn.row_factory = sqlite3.Row
     conn.execute("PRAGMA case_sensitive_like = ON")
     conn.execute("PRAGMA busy_timeout = 5000")
     return conn
     ```
   - Enabling `PRAGMA case_sensitive_like = ON` allows SQLite to optimize `WHERE event_id LIKE 'conv_id_%'` into a B-tree range scan (`event_id >= 'conv_id_' AND event_id < 'conv_id`'`) on the primary key index `sqlite_autoindex_events_1`.

2. **Schema Version Gating (`REQ-018`)**:
   - Define `SCHEMA_VERSION = 2` and a process-local set `_INITIALIZED_DBS: set[tuple[str, int]] = set()`.
   - In `_init_db(self)`:
     - Check if `os.path.isfile(self.db_path)` and `(self.db_path, st_mtime_ns)` is in `_INITIALIZED_DBS`; if so, return immediately.
     - Otherwise, open connection and query `PRAGMA user_version` and check if `events` table exists in `sqlite_master`.
     - If `user_version >= SCHEMA_VERSION` and `events` exists, record `(self.db_path, st_mtime_ns)` in `_INITIALIZED_DBS` and return without running `CREATE TABLE` or `ALTER TABLE`.
     - If `user_version < SCHEMA_VERSION` or tables are missing:
       - Set `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL`.
       - Execute `CREATE TABLE IF NOT EXISTS` for all 7 tables (`work_items` includes `updated_at REAL` directly in its `CREATE TABLE` definition).
       - Inspect existing columns via `PRAGMA table_info(tokens)` and `PRAGMA table_info(work_items)` and only run `ALTER TABLE ... ADD COLUMN` for columns not yet present (eliminating exception-driven control flow).
       - Create secondary indexes (`REQ-016`):
         ```sql
         CREATE INDEX IF NOT EXISTS idx_events_type_created ON events(type, created_at);
         CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);
         CREATE INDEX IF NOT EXISTS idx_work_items_parent ON work_items(parent_conv_id, parent_turn_id, status);
         CREATE INDEX IF NOT EXISTS idx_work_items_status ON work_items(status, updated_at, created_at);
         CREATE INDEX IF NOT EXISTS idx_tokens_claimed_by ON tokens(claimed_by);
         ```
       - Set `PRAGMA user_version = 2` and update `_INITIALIZED_DBS`.

3. **Opportunistic & Explicit Pruning (`REQ-017`)**:
   - Implement `prune(self, retention_seconds: float = 7 * 86400, transient_retention_seconds: float = 86400) -> dict`:
     - Deletes `events` where `type IN ('SUBAGENT_COMMAND', 'SUBAGENT_FILE_EDIT') AND created_at < now - transient_retention_seconds`.
     - Deletes `events` where `created_at < now - retention_seconds`.
     - Deletes terminal `work_items` (`status IN ('COMPLETED', 'TERMINATED', 'DONE', 'FAILED', 'TIMED_OUT')`) where `COALESCE(updated_at, created_at) < now - retention_seconds`.
     - Deletes `tokens` where `created_at < now - retention_seconds`.
     - Returns counts of deleted rows per table.
   - Implement `_prune_opportunistically(self, min_interval_seconds: float = 3600.0)`:
     - Checks a lightweight timestamp marker (`<db_path>.last_prune` mtime or in-process `_LAST_PRUNE_CHECK`). If `< min_interval_seconds` has elapsed since the last prune, returns immediately with zero SQLite queries. Otherwise calls `self.prune()` and updates the marker.

4. **Non-Stalling Outbound Metrics Push (`REQ-020`)**:
   - In `_push_metric_async(event_type, payload, created_at=None)`:
     - Return immediately if `os.environ.get("AGY_DISABLE_METRICS_PUSH") == "1"`.
     - Only spawn the push thread if `os.environ.get("ATTENTION_METRICS_PUSH_ENABLED") == "1"` or `bool(os.environ.get("ATTENTION_METRICS_API_KEY", "").strip())`.
     - Reduce `atexit` thread join timeout from `1.0`s to `0.05`s and HTTP timeout to `1.5`s.

### 2.2 `scripts/common.py` & Hook Scripts (`REQ-019`)

1. **Single-Pass Transcript Parser (`scripts/common.py`)**:
   - Maintain `_TRANSCRIPT_CACHE: dict[str, tuple[int, int, dict]] = {}` mapping `abs_path -> (mtime_ns, size, parsed_summary)`.
   - `parse_transcript(transcript_path: str) -> dict`:
     - Returns `{"turn_id": 0, "lines_count": 0, "tokens": [], "first_system_sender": None, "steps": []}` when path is empty or missing.
     - Checks `os.stat(abs_path)`: if `(st.st_mtime_ns, st.st_size)` matches `_TRANSCRIPT_CACHE[abs_path]`, returns cached dictionary immediately.
     - Otherwise reads `transcript_path` once line-by-line, parsing each non-empty JSON line and extracting:
       - `turn_id` and `lines_count`
       - deduplicated `[ANTIGRAVITY_TOKEN:<uuid>]` list from `USER_INPUT` and `SYSTEM_MESSAGE` steps
       - `first_system_sender` from the first non-empty step if `source == "SYSTEM"` and `type == "SYSTEM_MESSAGE"` containing `sender=<uuid>`
       - `steps`: list of `(idx, raw_line, step_dict)` for downstream consumers (`is_plan_execution_active`).
   - `get_turn_state(transcript_path)` delegates to `parse_transcript(transcript_path)`.
   - `is_subagent(data, ledger=None)` delegates to `parse_transcript(transcript_path)` and reuses `ledger` if provided (or instantiates `Ledger()` once).
   - In `scripts/enforce-delegation.py`:
     - `is_plan_execution_active(transcript_path, artifact_dir=None)` uses `parse_transcript(transcript_path)["steps"]` instead of re-opening and re-parsing `transcript_path`.
     - `main()` instantiates `ledger = Ledger()` once and passes it to `is_subagent(data, ledger=ledger)`, `check_subagent_doom_loop(ledger, ...)`, and `record_subagent_file_edit(..., ledger)`.

### 2.3 `scripts/system_audit.py` & `scripts/surface_validator.py` (`REQ-017`, `REQ-021`)

1. **Database Repair & Vacuum (`scripts/system_audit.py`, `REQ-017`)**:
   - In `audit_sqlite_ledger(db_path: Path, repair: bool = False)`:
     - When `repair=True`, instantiate `Ledger(str(p))` so schema migrations and all secondary indexes (`idx_events_type_created`, etc.) are applied, mark stale `ACTIVE` work items older than 3600s as `TERMINATED`, delete `TIMED_OUT` work items older than 86400s, call `ledger.prune()`, and run `VACUUM` outside any open transaction to compact `attention_guard.db`.
2. **Home-Relative Script Path Validation (`scripts/surface_validator.py`, `REQ-021`)**:
   - Update line 371 of `scripts/surface_validator.py`:
     ```python
     for m in re.finditer(r'(?<![\w.\-~])(~?/[\w.\-]+(?:/[\w.\-]+)*/scripts/[A-Za-z0-9_.\-/]+\.py)', content):
         raw_path = m.group(1)
         abs_path = os.path.expanduser(raw_path)
         if not os.path.exists(abs_path):
             errs.append(f"Referenced absolute script '{raw_path}' in '{rel_path}' does not exist on disk")
     ```
3. **`agent-translator` Surface Fixes (`REQ-021`)**:
   - Add the `generate-audio-book` trigger line to `~/.gemini/config/plugins/agent-translator/rules/AGENTS.md` and update stale `scripts/migrate_sanguozhi_workspace.py` reference in `skills/translate-zh-book/SKILL.md`.

### 2.4 DeepSeek Harness Plugin Parity (`dsh-attention-guard-plugin`, `REQ-022`)
- **Mechanical Shell Guards (`src/guards.ts`, `Addresses: REQ-022`)**:
  - `checkDestructiveCommand(cmd: string): string | null`: blocks `git reset --hard`, `git clean -f`/`-fd`/`-fx`, `git checkout .`/`-- .`, `git restore .`, `git push --force`/`-f` without `--force-with-lease`, and catastrophic `rm -rf` targets (`/`, `~`, `$HOME`, `${HOME}`, `.`, `..`, `.git`).
  - `checkTestTampering(cmd: string): string | null`: inspects shell redirection/inline edits targeting test files (`test_*.py`, `*_test.py`, `*.test.ts`, `*.spec.ts`, `*_test.go`, `tests/`) for test-skipping markers (`@pytest.mark.skip`, `pytest.skip(`, `it.skip(`, `describe.skip(`, `test.skip(`, `t.Skip(`, `assert True`).
- **Doom-Loop & Context Salience (`src/circuit-breaker.ts`, `src/index.ts`, `Addresses: REQ-022`)**:
  - Extend `AttentionGuardCircuitBreaker` with `checkDoomLoop(command: string, threshold = 3): string | null`, `recordFileEdit()`, cumulative session token tracking (`recordTokens(chars: number)`), and expanded build/test command detection (`cmake`, `ninja`, `pip`, `go build`, `npm/pnpm/yarn/bun build`).
  - In `src/index.ts`, enforce `checkDestructiveCommand`, `checkTestTampering`, and `checkDoomLoop` before/during execution and append context refresh reminders when `tokensSinceRefresh >= 40000`.
- **Subprocess Memoization (`src/rtk.ts`, `Addresses: REQ-022`)**:
  - Cache `checkRtkAvailable(rtkBinary)` and `rewriteCommand(command, config)` results in bounded `Map` caches (with `clearRtkCache()` helper for tests) to avoid spawning `which` or `rtk rewrite` repeatedly for identical commands.
