# Tasks: Weekly Skills & Rules Health Audit CLI

Sources: [spec.md](./spec.md), [design.md](./design.md)

## Task 1: Implement `scripts/weekly_skill_rule_audit.py` and verify with TDD + mutation testing

- [x] Complete the work and its applicable checks.
- Covers: `REQ-048` / `AC-048-1`, `AC-048-2`
- Files: `scripts/weekly_skill_rule_audit.py`, `tests/test_weekly_skill_rule_audit.py`, `rules/AGENTS.md`
- Dependencies: None
- Blocked by: None
- Work: Author failing tests in `tests/test_weekly_skill_rule_audit.py`, implement `scripts/weekly_skill_rule_audit.py`, update `rules/AGENTS.md` inline auto-heal clause (`<= 4,000` chars), run `pytest`, `mutation_runner.py` (`>= 80%`), `surface_validator.py`, `validate_specs.py`, and `deploy_plugin.py`.
- Completion evidence: Recorded in [Run 1](./verification.md#run-1--2026-11-26).

## Gate 2: traceability and readiness

| Requirement | AC | ADR or rationale | Design | Task | Planned verification | Status / reason |
| --- | --- | --- | --- | --- | --- | --- |
| REQ-048 | AC-048-1 | [ADR-009](./decisions.md#adr-009-bounded-streaming-scan-over-recent-transcriptjsonl-logs) | [Components](./design.md#components) | [Task 1](#task-1-implement-scriptsweekly_skill_rule_auditpy-and-verify-with-tdd--mutation-testing) | [AC-048-1](./verification.md#ac-048-1-req-048) | PASS — healthy audit metrics, usage counts, and clean exit mapped |
| REQ-048 | AC-048-2 | [ADR-009](./decisions.md#adr-009-bounded-streaming-scan-over-recent-transcriptjsonl-logs) | [Boundaries](./design.md#boundaries-and-recovery) | [Task 1](#task-1-implement-scriptsweekly_skill_rule_auditpy-and-verify-with-tdd--mutation-testing) | [AC-048-2](./verification.md#ac-048-2-req-048) | PASS — broken links, bad triggers, budget overflow, and repeat/cutoff filters mapped |

- Backward scope check: PASS — Task 1 serves strictly `REQ-048` (`AC-048-1`, `AC-048-2`).
- Reference and catalog consistency: PASS — all links, anchors, and `docs/specs/INDEX.md` entries match.
