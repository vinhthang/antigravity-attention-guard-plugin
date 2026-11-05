# Specification Index

Central catalog of architectural specifications and design decisions for `antigravity-attention-guard-plugin`.

| Feature ID | Title | Status | Requirement Range | Key Decisions | Spec Path |
|---|---|---|---|---|---|
| dynamic-summary-length | Decouple Subagent Summary Length from Schema Caps | completed | `REQ-DSL-001` - `REQ-DSL-004` | Remove maxLength constraint from schemas and validators | [spec.md](dynamic-summary-length/spec.md) |
| adaptive-guard-and-metrics-evolution | Dynamic Context-Window Scaling & Unified Metrics Dashboard | completed | `REQ-AE-001` - `REQ-AE-006` | Auto-increasing attempt counter + readable text, token salience, multi-harness metrics & timeline UI | [spec.md](adaptive-guard-and-metrics-evolution/spec.md) |
| 2026-10-19-subagent-system-message-token | Subagent Token Detection, Shell Argument Boundaries & Opus Auditor Preservation | completed | `REQ-001` - `REQ-004` | `ADR-001` - `ADR-002` | [spec.md](2026-10-19-subagent-system-message-token/spec.md) |
| 2026-10-20-harness2-surface-context-attribution | Harness² Surface Validation, Pointer-Based Context Boundary & Causal Edit Attribution | completed | `REQ-001` - `REQ-006` | `ADR-001` - `ADR-003` | [spec.md](2026-10-20-harness2-surface-context-attribution/spec.md) |
| 2026-10-21-community-research-must-todos | Community & Academic Research Must-To-Do Enhancements | completed | `REQ-007` - `REQ-015` | `ADR-001` - `ADR-004` | [spec.md](2026-10-21-community-research-must-todos/spec.md) |
| 2026-10-27-ledger-and-hook-performance-optimization | SQLite Ledger Indexing, Schema Gating, Single-Pass Transcript Caching & Surface Validation Fixes | completed | `REQ-016` - `REQ-022` | `ADR-001` - `ADR-005` | [spec.md](2026-10-27-ledger-and-hook-performance-optimization/spec.md) |
| 2026-10-30-hook-lifecycle-and-guard-precision-fixes | Work Item Lifecycle Hygiene, Doom-Loop Signature Normalization & Guard Precision Fixes | completed | `REQ-023` - `REQ-026` | `ADR-001` - `ADR-004` | [spec.md](2026-10-30-hook-lifecycle-and-guard-precision-fixes/spec.md) |
| 2026-10-31-subagent-task-fence-and-watchdog-enforcement | Subagent Background Task Completion Fence, `send_message` Re-Dispatch Tracking, Watchdog Enforcement & Telemetry Alignment | completed | `REQ-027` - `REQ-029`, `REQ-031` - `REQ-032` | `ADR-001` - `ADR-005` | [spec.md](2026-10-31-subagent-task-fence-and-watchdog-enforcement/spec.md) |
| 2026-11-02-inline-python-signature-precision | Precision Inline `python -c` Polling Signature Normalization | completed | `REQ-030` | `ADR-001` | [spec.md](2026-11-02-inline-python-signature-precision/spec.md) |
| 2026-11-05-standalone-marketplace-packaging | Standalone Marketplace Packaging, Modular Rule/Skill Consolidation & Portable Hook Architecture | completed | `REQ-033` - `REQ-037` | `ADR-001` - `ADR-003` | [spec.md](2026-11-05-standalone-marketplace-packaging/spec.md) |
