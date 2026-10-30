# Architectural Decision Records: SQLite Ledger Indexing, Schema Gating & Hook Performance Optimization

## ADR-001: Enable `PRAGMA case_sensitive_like = ON` & Secondary B-Tree Indexes (`REQ-016`)
- **Status**: Proposed
- **Addresses**: `REQ-016`
- **Context**: `events.event_id` is formatted as `f"{actor_id}_{turn_id}_{hook_type}_{execution_idx}_{work_id}_{event_type}"` and declared as `event_id TEXT PRIMARY KEY` (which uses SQLite's default `BINARY` collation). However, SQLite's `LIKE` operator is case-insensitive by default, which prevents the query planner from using a `BINARY`-collated B-tree index for `WHERE event_id LIKE 'conv_id_%'`. Consequently, every call to `check_subagent_doom_loop()`, `get_current_fsm_state()`, and `audit_conversation_budget()` executed a full-table scan over 12,000+ rows.
- **Decision**: Execute `PRAGMA case_sensitive_like = ON` on every connection in `Ledger._get_connection()` (UUIDs and event ID prefixes are strictly ASCII case-exact) and create secondary indexes (`idx_events_type_created`, `idx_events_created_at`, `idx_work_items_parent`, `idx_work_items_status`, `idx_tokens_claimed_by`).

## ADR-002: Schema Version Gating via `PRAGMA user_version` & Throttled Opportunistic Pruning (`REQ-017`, `REQ-018`)
- **Status**: Proposed
- **Addresses**: `REQ-017`, `REQ-018`
- **Context**: `Ledger._init_db()` ran 7 `CREATE TABLE IF NOT EXISTS` statements and 5 failing `ALTER TABLE ... ADD COLUMN` statements on every `Ledger()` instantiation (2–3 times per tool call). Meanwhile, `Ledger._prune_opportunistically()` was a no-op (`pass`), allowing `SUBAGENT_COMMAND` rows to grow to 8+ MB.
- **Decision**:
  1. Gate `_init_db()` behind an in-process `(db_path, st_mtime_ns)` cache and SQLite `PRAGMA user_version = 2`. Only when `user_version < 2` (or when `schema_metadata` is missing in an empty database) does `_init_db()` execute table/index creation and column migrations before setting `PRAGMA user_version = 2`.
  2. Store a last-pruned epoch timestamp (using a lightweight sentinel file `<db_path>.last_prune` or `schema_metadata`) so `_prune_opportunistically()` executes `DELETE` statements at most once per 3,600 seconds, removing `SUBAGENT_COMMAND` / `SUBAGENT_FILE_EDIT` events older than 24 hours and historical `events`, terminal `work_items`, and `tokens` older than 7 days.
  3. Extend `system_audit.py --repair-db` to invoke full pruning, index creation, and `VACUUM`.

## ADR-003: Process-Local Single-Pass `transcript.jsonl` Cache (`REQ-019`)
- **Status**: Proposed
- **Addresses**: `REQ-019`
- **Context**: `PreToolUse` and `Stop` hooks parsed `transcript.jsonl` 3–4 times per invocation across `get_turn_state()`, `is_subagent()` (token scan + sender fallback), and `is_plan_execution_active()`.
- **Decision**: Introduce `parse_transcript(transcript_path)` in `scripts/common.py` with an in-memory cache keyed by `(os.path.abspath(transcript_path), stat.st_mtime_ns, stat.st_size)`. A single linear scan extracts `turn_id`, `lines_count`, `[ANTIGRAVITY_TOKEN:...]` tokens, the step-0 `SYSTEM_MESSAGE` sender UUID, and the parsed step dictionaries for `is_plan_execution_active()`.

## ADR-004: Opt-In Non-Blocking Metrics Push & Home-Relative Script Path Validation (`REQ-020`, `REQ-021`)
- **Status**: Proposed
- **Addresses**: `REQ-020`, `REQ-021`
- **Context**: `_push_metric_async()` spawned an outbound HTTPS thread on every `STOP_REQUESTED` and `PRIMARY_TOOL_DENIED` event and stalled process exit via `atexit` (`t.join(timeout=1.0)`), even when no `ATTENTION_METRICS_API_KEY` was configured (whereas batch syncing is already handled by `scripts/sync_metrics.py`). Separately, `surface_validator.py` matched `/[\w.\-]+.../scripts/...\.py` inside `~/.gemini/...`, stripping the leading `~` and reporting false-positive missing script errors.
- **Decision**:
  1. Skip `_push_metric_async()` unless `ATTENTION_METRICS_PUSH_ENABLED == "1"` or `ATTENTION_METRICS_API_KEY` is non-empty (and `AGY_DISABLE_METRICS_PUSH != "1"`), and cap the `atexit` join timeout at `0.05s`.
  2. Update `surface_validator.py` to capture optional leading `~` (`~?/[\w.\-]+...`) with a negative lookbehind `(?<![\w.\-~])` and expand `~` via `os.path.expanduser()`, and clean up the two remaining surface errors in `agent-translator`.

## ADR-005: Cross-Harness Guard & Performance Parity in `dsh-attention-guard-plugin` (`REQ-022`)
- **Status**: Accepted
- **Addresses**: `REQ-022`
- **Context**: `dsh-attention-guard-plugin` (`/Users/thanghoang/github/dsh-attention-guard-plugin`) lacked the mechanical guards (`checkDestructiveCommand`, `checkTestTampering`, `checkDoomLoop`), cumulative context token salience reminders (`>= 40,000` tokens), and in-memory caching of `rtk rewrite` / `which rtk` subprocess calls implemented in `antigravity-attention-guard-plugin`.
- **Decision**: Port the mechanical guards (`src/guards.ts`), doom-loop + token salience tracking (`src/circuit-breaker.ts`), and `rewriteCommand` / `checkRtkAvailable` memoization (`src/rtk.ts`) to `dsh-attention-guard-plugin` while maintaining 100% backward compatibility with existing Cordis plugin tests.
