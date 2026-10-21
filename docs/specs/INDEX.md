# Specification Index

Central catalog of architectural specifications and design decisions for `antigravity-attention-guard-plugin`.

| Feature ID | Title | Status | Requirement Range | Key Decisions | Spec Path |
|---|---|---|---|---|---|
| dynamic-summary-length | Decouple Subagent Summary Length from Schema Caps | completed | `REQ-DSL-001` - `REQ-DSL-004` | Remove maxLength constraint from schemas and validators | [spec.md](dynamic-summary-length/spec.md) |
| adaptive-guard-and-metrics-evolution | Dynamic Context-Window Scaling & Unified Metrics Dashboard | completed | `REQ-AE-001` - `REQ-AE-006` | Auto-increasing attempt counter + readable text, token salience, multi-harness metrics & timeline UI | [spec.md](adaptive-guard-and-metrics-evolution/spec.md) |
| 2026-10-19-subagent-system-message-token | Subagent Token Detection, Shell Argument Boundaries & Opus Auditor Preservation | completed | `REQ-001` - `REQ-004` | `ADR-001` - `ADR-002` | [spec.md](2026-10-19-subagent-system-message-token/spec.md) |
| 2026-10-20-harness2-surface-context-attribution | Harness² Surface Validation, Pointer-Based Context Boundary & Causal Edit Attribution | completed | `REQ-001` - `REQ-006` | `ADR-001` - `ADR-003` | [spec.md](2026-10-20-harness2-surface-context-attribution/spec.md) |
| 2026-10-21-community-research-must-todos | Community & Academic Research Must-To-Do Enhancements | completed | `REQ-007` - `REQ-013` | `ADR-001` - `ADR-004` | [spec.md](2026-10-21-community-research-must-todos/spec.md) |
