# Specification: Dynamic Context-Window Scaling & Unified Metrics Dashboard

**Feature ID**: `adaptive-guard-and-metrics-evolution`  
**Status**: `approved`  
**Created**: `2026-10-16`  
**Version**: `2.0.0`  
**Sign-off**: `User Approved (2026-10-16)`  
**Precedence**: `spec.md` > `decisions.md` > `design.md` > `tasks.md`

---

## 1. Problem Statement & Scope

1. **Auto-Increasing Attempt Counter & Human-Readable Guidance**:
   Replace complex hash signatures with a transparent auto-increasing attempt counter (`Attempt 1`, `Attempt 2`, ...) and clear, human-readable guidance text.
   - On Attempt 1: Advise writing a test reproducer or diagnostic doc.
   - On Attempt 2: Trip circuit breaker (`FAILURE_STAGE_2_TRIPPED`), lock speculative code edits, and require `diagnosis.md` / `rca.md`.
   - On test pass (`exit_code == 0`): Reset counter to 0 (`RECOVERY_VERIFIED`).
2. **Context-Depth Driven Salience (`antigravity`)**:
   In `scripts/attention-refresh.py`, trigger prompt refresh dynamically when the session accumulates $\ge 40,000$ tokens. Suppress periodic 25-turn reminders when session volume is $< 20,000$ tokens.
3. **Unified Cross-Harness Metrics Dashboard (`attention-metrics-server`)**:
   - Ingest events tagged by `platform`: `antigravity`, `codex`, `dsh`.
   - Track tokens saved by RTK (`raw_tokens` vs `filtered_tokens`) and calculate dollar savings.
   - Endpoints for token savings ROI, recovery funnel, and session trajectories.
   - Vue 3 dashboard with platform selector, KPI cards, and session list.

---

## 2. Normative Requirements

### Pillar 1: Guard Engine (`codex`, `dsh`, `antigravity`)

- **`REQ-AE-001` (Auto-Increasing Failure Counter & Human-Readable Guidance)**:
  - In `codex` and `dsh`, when a test or build command exits with non-zero exit code:
    - Increment `streak += 1`.
    - If `streak == 1`: State is `FAILURE_STAGE_1`. Inject clear text:  
      `"[ATTENTION GUARD - ATTEMPT 1]: Test failed. Speculative in-place edits discouraged. Author an isolated test reproducer or diagnostic doc before fixing code."`
    - If `streak >= 2`: State is `FAILURE_STAGE_2_TRIPPED`. Inject clear text:  
      `"[ATTENTION GUARD - ATTEMPT {streak}]: Consecutive test failures. Circuit breaker tripped. Code edits locked—author diagnosis.md to isolate root cause."`
    - On passing test (`exit_code == 0`): Reset `streak = 0`, state becomes `RECOVERY_VERIFIED`.
  - Ingest telemetry emits `BREAKER_STATE_CHANGE` and `TEST_EXECUTION_RESULT` with `streak` and readable message.

- **`REQ-AE-002` (Token-Depth Salience in Antigravity)**:
  - In `scripts/ledger.py` and `scripts/attention-refresh.py`:
    - Track tool I/O character volume: $\Delta \text{tokens} = \lfloor \Delta \text{chars} / 4 \rfloor$.
    - Maintain `total_session_tokens` and `tokens_since_refresh`.
    - When `tokens_since_refresh >= 40000`, inject `PRIMARY_RULES_REMINDER` and reset `tokens_since_refresh = 0`.
    - On 25-turn modulo: suppress if `total_session_tokens < 20000`.

---

### Pillar 2: Unified Metrics & Dashboard (`attention-metrics-server`)

- **`REQ-AE-003` (Multi-Harness Platform Dimension & Ingest Validation)**:
  - In `backend/main.go`:
    - Add indexed columns: `platform VARCHAR(32) NOT NULL DEFAULT 'generic'`, `session_id VARCHAR(128)`, `raw_tokens INT DEFAULT 0`, `filtered_tokens INT DEFAULT 0`.
    - Compound index: `(platform, created_at DESC)`.
    - Ingest `POST /api/metrics` accepts top-level `platform` (`antigravity`, `codex`, `dsh`), with fallback to `User-Agent` header or `generic`.
    - `GET /api/metrics` supports `platform`, `session_id`, `event_type`, `limit`.

- **`REQ-AE-004` (RTK Token Economics Aggregation)**:
  - `GET /api/metrics/token-savings?range=7d&platform=all` returns:
    - `total_raw_tokens`, `total_filtered_tokens`, `tokens_saved`, `savings_percentage`.
    - `estimated_cost_saved_usd` (at `$2.50 / 1M` tokens).
    - `platform_breakdown` for `codex`, `dsh`, `antigravity`.

- **`REQ-AE-005` (Circuit-Breaker Recovery Funnel & Trajectories)**:
  - `GET /api/metrics/funnel?range=7d`: aggregates distinct `session_id`s for `tripped_sessions`, `rca_authored_sessions`, `recovered_sessions`, and `recovery_rate_pct`.
  - `GET /api/metrics/sessions?limit=50`: returns recent session summaries.
  - `GET /api/metrics/sessions/:session_id`: returns chronological event list.

- **`REQ-AE-006` (Vue 3 Dashboard Components)**:
  - Platform filter dropdown (`All Platforms`, `Antigravity`, `Codex`, `DeepSeek Harness`).
  - Token Economics KPI card (tokens saved, % reduction, USD saved).
  - Recovery Funnel card (Tripped $\to$ RCA $\to$ Recovered).
  - Sessions exploration tab rendering turn sequence, attempt counts, and status badges.

---

## 3. Acceptance Criteria

- **`TEST-AE-001`**: On test failure 1, streak=1 and readable Attempt 1 text is output. On failure 2, streak=2, circuit breaker trips, and Attempt 2 text is output. On pass, streak resets to 0.
- **`TEST-AE-002`**: In Antigravity, token refresh triggers at $\ge 40\text{K}$ tokens and suppresses at $< 20\text{K}$ tokens.
- **`TEST-AE-003`**: Ingesting metrics from all platforms correctly stores and filters by `platform` (`dsh`, `codex`, `antigravity`).
- **`TEST-AE-004`**: `/api/metrics/token-savings` returns correct savings percentage and USD cost saved.
- **`TEST-AE-005`**: `/api/metrics/sessions` and frontend build compile and render sessions correctly.
