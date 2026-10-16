# Tasks: Dynamic Context-Window Scaling & Unified Metrics Dashboard

All tasks cite requirement IDs and follow Dalio Phase 2 execution sequencing.

---

## Phase 1: Adaptive Guard Core Engine (`REQ-AE-001`, `REQ-AE-002`)
- [x] `TASK-AE-001`: Update `codex-attention-guard-plugin` (`scripts/fsm.py`, `scripts/post_tool_guard.py`) with auto-increasing attempt counter (`streak: 1, 2...`), human-readable advice text on Attempt 1 and Attempt 2, and passing reset.
- [x] `TASK-AE-002`: Update `dsh-plugin-attention-guard` (`src/circuit-breaker.ts`) with auto-increasing attempt counter (`streak: 1, 2...`), human-readable advice text on Attempt 1 and Attempt 2, and passing reset.
- [x] `TASK-AE-003`: Update `antigravity-attention-guard-plugin` (`scripts/ledger.py`, `scripts/attention-refresh.py`) with cumulative tool I/O character volume tracking ($\ge 40\text{K}$ tokens injects reminder; $< 20\text{K}$ tokens suppresses static turn modulo).
- [x] `TASK-AE-004`: Update telemetry emission in all three plugins to transmit `"platform"` (`antigravity`, `codex`, `dsh`), `session_id`, `raw_tokens_est`, `filtered_tokens_est`, and `streak`.
- [x] `TASK-AE-005`: Run test suites across `codex`, `dsh`, and `antigravity` verifying `TEST-AE-001` and `TEST-AE-002`.

---

## Phase 2: Metrics Server Database & Ingest (`REQ-AE-003`, `REQ-AE-004`, `REQ-AE-005`)
- [x] `TASK-AE-006`: In `attention-metrics-server/backend/main.go`, add schema migrations for `platform`, `session_id`, `raw_tokens`, and `filtered_tokens` with compound index `(platform, created_at DESC)`.
- [x] `TASK-AE-007`: Update `IngestRequest` handler in `backend/main.go` to parse `platform` (with User-Agent fallback) and store `session_id`, `raw_tokens`, `filtered_tokens`.
- [x] `TASK-AE-008`: Implement `GET /api/metrics` with `platform`, `session_id`, `event_type`, and `limit` query parameters.
- [x] `TASK-AE-009`: Implement `GET /api/metrics/token-savings` aggregating raw/filtered tokens, percentage savings, and estimated USD cost saved.
- [x] `TASK-AE-010`: Implement `GET /api/metrics/funnel` calculating `tripped_sessions`, `rca_authored_sessions`, `recovered_sessions`, and `recovery_rate_pct`.
- [x] `TASK-AE-011`: Implement `GET /api/metrics/sessions` and `GET /api/metrics/sessions/:id` returning recent sessions and full chronological trajectories.
- [x] `TASK-AE-012`: Write Go unit and integration tests (`backend/integration_test.go`) validating `TEST-AE-003` and `TEST-AE-004`.

---

## Phase 3: Frontend Trajectory & Unified Dashboard UI (`REQ-AE-006`)
- [x] `TASK-AE-013`: In `attention-metrics-server/frontend`, implement reactive platform selector dropdown (`All Platforms`, `Antigravity`, `Codex`, `DeepSeek Harness`).
- [x] `TASK-AE-014`: Implement Token Economics KPI card displaying RTK tokens saved and USD cost avoidance.
- [x] `TASK-AE-015`: Implement Circuit Breaker Funnel visualizer component rendering conversion from Tripped $\to$ RCA $\to$ Recovery.
- [x] `TASK-AE-016`: Implement Sessions tab rendering recent sessions with attempt streaks and recovery status.
- [x] `TASK-AE-017`: Verify frontend build (`npm run build`) and validate `TEST-AE-005`.
