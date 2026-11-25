# Tasks: Configurable `PreToolUse` `kubectl` Mutation Guard

Sources: [spec.md](./spec.md), [design.md](./design.md)

## Task 1: Implement `scripts/kubectl_guard.py`, wire `enforce-delegation.py`, and verify with TDD + mutation testing

- [x] Complete the work and its applicable checks.
- Covers: `REQ-047` / `AC-047-1`, `AC-047-2`
- Files: `scripts/kubectl_guard.py`, `scripts/enforce-delegation.py`, `tests/test_kubectl_guard.py`
- Dependencies: None
- Blocked by: None
- Work: Write failing tests in `tests/test_kubectl_guard.py`, implement `scripts/kubectl_guard.py` and hook it into `scripts/enforce-delegation.py`, verify full `pytest tests/`, `mutation_runner.py` (`>= 80%`), `surface_validator.py --json`, `validate_specs.py`, `prepare_code_review.py`, and live `deploy_plugin.py`.
- Completion evidence: Recorded in [Run 1](./verification.md#run-1--2026-11-26).

## Gate 2: traceability and readiness

| Requirement | AC | ADR or rationale | Design | Task | Planned verification | Status / reason |
| --- | --- | --- | --- | --- | --- | --- |
| REQ-047 | AC-047-1 | [ADR-008](./decisions.md#adr-008-fail-closed-kubectl-verb--current-context-inspection-without-shelling-out) | [Components](./design.md#components) | [Task 1](#task-1-implement-scriptskubectl_guardpy-wire-enforce-delegationpy-and-verify-with-tdd--mutation-testing) | [AC-047-1](./verification.md#ac-047-1-req-047) | PASS — read-only verbs, lab allowlist, and missing policy mapped |
| REQ-047 | AC-047-2 | [ADR-008](./decisions.md#adr-008-fail-closed-kubectl-verb--current-context-inspection-without-shelling-out) | [Boundaries](./design.md#boundaries-and-recovery) | [Task 1](#task-1-implement-scriptskubectl_guardpy-wire-enforce-delegationpy-and-verify-with-tdd--mutation-testing) | [AC-047-2](./verification.md#ac-047-2-req-047) | PASS — mutating verbs, `exec`, kubeconfig fallback, malformed JSON mapped |

- Backward scope check: PASS — Task 1 serves strictly `REQ-047` (`AC-047-1`, `AC-047-2`).
- Reference and catalog consistency: PASS — all links, anchors, and `docs/specs/INDEX.md` entries match.
