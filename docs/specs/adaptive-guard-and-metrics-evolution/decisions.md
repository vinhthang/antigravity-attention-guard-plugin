# Decision Record: Adaptive Context-Window Scaling & Metrics Evolution

All architectural decisions recorded here are append-only and cite stable requirement IDs from `spec.md`.

---

## ADR-AE-001: Semantic Error-Signature Hashing & Progressive Budget Reconciliation
- **Cited Requirements**: `REQ-AE-001`
- **Context**: In execution-level runners (`codex` and `dsh`), the existing circuit breaker increments a simple integer `failure_streak`. In progressive TDD, fixing Bug 1 exposes Bug 2 in a test suite. Under a naive counter, this increments `failure_streak = 2` and trips the circuit breaker, treating genuine engineering progress as an infinite loop. Conversely, repetitive identical errors require rapid halting.
- **Decision**: Hash the normalized error output: `SHA256(framework + "|" + error_class + "|" + normalized_message + "|" + call_site)[:12]`. Maintain the last observed hash in session state.
  - If `sig(N) == sig(N-1)`, the agent is repeating an identical failure; trip immediately at attempt 2 (`identical_failure_streak >= 2`).
  - If `sig(N) != sig(N-1)`, the failure is divergent; reset identical streak to 1 and grant an adaptive progressive budget of up to 4 attempts in `FAILURE_STAGE_1`, tripping upon the 5th consecutive failure (`progressive_failure_streak >= 5`). This aligns directly with the authoritative executor rule granting up to 5 implementation attempts per test increment.
  - A passing test execution (`exit_code == 0`) resets both streaks to 0 and transitions to `RECOVERY_VERIFIED`.
- **Consequences**: Eliminates false-positive halts during progressive TDD while maintaining zero tolerance for identical failure loops.

---

## ADR-AE-002: Cumulative Tool I/O Token Salience over Context-Window Introspection
- **Cited Requirements**: `REQ-AE-002`
- **Context**: Static reminders every 25 turns create unnecessary context bloat in small sessions, but are too infrequent in sessions where large subagent payloads cause attention dilution. The Antigravity engine's `PreInvocation` hook receives only an invocation count (`invocationNum`), not ambient LLM context token counts.
- **Decision**: Ground token tracking in cumulative tool I/O characters observed in the local SQLite ledger: $\Delta \text{tokens} = \lfloor(\text{tool\_input} + \text{tool\_output})/4\rfloor$. Inject reminders dynamically when `tokens_since_refresh >= 40,000`. Suppress static 25-turn reminders if total session tokens are $< 20,000$.
- **Consequences**: Maximizes prompt rule salience when context bloat is highest, without relying on unsupported LLM context introspection.

---

## ADR-AE-003: Explicit Payload Platform Tagging with User-Agent Fallback
- **Cited Requirements**: `REQ-AE-003`
- **Context**: Telemetry events need to be indexed and filtered by harness origin (`antigravity`, `codex`, `dsh`). Currently, plugins send varying headers and no explicit platform field in JSON bodies.
- **Decision**: Add an indexed `platform` column (`VARCHAR(32) NOT NULL DEFAULT 'generic'`) and compound index `(platform, created_at)` in `events`. Update all plugin telemetry clients to send `"platform"` in the JSON payload body. Maintain backward compatibility by inspecting client `User-Agent` headers or defaulting to `generic`.
- **Consequences**: Enables millisecond-level filtering by harness and cross-platform comparative dashboards.

---

## ADR-AE-004: Configurable Token Economics & Funnel Accounting
- **Cited Requirements**: `REQ-AE-004`, `REQ-AE-005`
- **Context**: Platform operators need visibility into RTK token compression ROI and circuit-breaker recovery efficacy.
- **Decision**: Plugins report `raw_tokens_est` and `filtered_tokens_est` upon command execution. `attention-metrics-server` aggregates savings and computes cost avoidance using a configurable rate (`TOKEN_COST_PER_MILLION_USD`, default $2.50 / 1M). Circuit breaker recovery funnel is computed over distinct `session_id`s tracking transitions through `FAILURE_STAGE_2_TRIPPED` $\to$ `FILE_MODIFICATION` (diagnostic docs) $\to$ `RECOVERY_VERIFIED`.
- **Consequences**: Quantifies exact infrastructure ROI across all three harnesses and provides an unskewed, session-level view of agent recovery.

