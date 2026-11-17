# Tasks: Antigravity 2.0 orchestration, Gemini 4 detection, and native worker governance

Sources: [spec.md](./spec.md), [design.md](./design.md)

## Task 1: Implement Gemini 4 detection, context budgets, native worker recognition, and async workflow parsing

- [x] Complete the work and its applicable checks.
- Covers: REQ-038 / AC-038-1, AC-038-2; REQ-039 / AC-039-1, AC-039-2; REQ-040 / AC-040-1, AC-040-2
- Files: `hooks.json`, `scripts/common.py`, `scripts/inject-rules.py`, `scripts/enforce-delegation.py`, `scripts/attention-refresh.py`, `tests/test_antigravity_v2_gemini4.py`
- Dependencies: None
- Blocked by: None
- Work: Write failing unit tests in `tests/test_antigravity_v2_gemini4.py` covering `Argon`/`Carbon` detection, `resolve_context_budget()` + `<CONTEXT_SUMMARY>` compaction reset, `swarm(add)` brief tagging (`[AGY_SWARM_WORKER]` / leaf `[AGY_SWARM_HELPER]`) + `is_native_worker()` Gemini 4 execution vs Coordinator/destructive/tampering/doom-loop blocks, subagent `run_workflow`/`swarm` denial, and `run_workflow` + `run_command(IsDaemon=True)` background task matching; implement minimal production changes and verify `mutation_runner.py` (`>= 80%` kill rate).
- Completion evidence: Verified in [Run 1](./verification.md#run-1--2026-11-18) (`261/261` unit tests passing; mutation kill rates `95.0%`–`100.0%`).

## Task 2: Sync Antigravity 2.0 rules, templates, skills, documentation, and live deployment

- [x] Complete the work and its applicable checks.
- Covers: REQ-041 / AC-041-1, AC-041-2
- Files: `rules/AGENTS.md`, `templates/EXECUTOR.md`, `templates/COORDINATOR.md`, `skills/git-worktree-sandbox/SKILL.md`, `plugin.json`, `README.md`, `tests/test_standalone_packaging.py`
- Dependencies: Task 1
- Blocked by: None
- Work: Update governance rules, subagent templates, `git-worktree-sandbox` skill, `README.md`, and `plugin.json` (`"1.1.0"`); run `deploy_plugin.py --deploy`, `surface_validator.py`, `system_audit.py`, `agy plugin validate`, and full `pytest tests/` suite.
- Completion evidence: Verified in [Run 1](./verification.md#run-1--2026-11-18) (`deploy_plugin.py --deploy`, `surface_validator.py` `7344/8000` chars, `agy plugin validate`, and `[PASS] attention-guard` in `system_audit.py`).

## Gate 2: traceability and readiness

| Requirement | AC | ADR or rationale | Design | Task | Planned verification | Status / reason |
| --- | --- | --- | --- | --- | --- | --- |
| REQ-038 | AC-038-1 | [Rationale](./decisions.md#architectural-rationale) | [Interfaces](./design.md#interfaces-and-flow) | [Task 1](#task-1-implement-gemini-4-detection-context-budgets-native-worker-recognition-and-async-workflow-parsing) | [AC-038-1](./verification.md#ac-038-1-req-038) | PASS — Gemini 4 codenames and 1000k/128k budgets mapped |
| REQ-038 | AC-038-2 | [Rationale](./decisions.md#architectural-rationale) | [Boundaries](./design.md#boundaries-and-recovery) | [Task 1](#task-1-implement-gemini-4-detection-context-budgets-native-worker-recognition-and-async-workflow-parsing) | [AC-038-2](./verification.md#ac-038-2-req-038) | PASS — env overrides and malformed fallback mapped |
| REQ-039 | AC-039-1 | [ADR-006](./decisions.md#adr-006-positive-signal-is_native_worker-plus-lightweight-swarmadd-brief-tagging) | [Interfaces](./design.md#interfaces-and-flow) | [Task 1](#task-1-implement-gemini-4-detection-context-budgets-native-worker-recognition-and-async-workflow-parsing) | [AC-039-1](./verification.md#ac-039-1-req-039) | PASS — swarm tagging and native worker allow/suppress mapped |
| REQ-039 | AC-039-2 | [ADR-006](./decisions.md#adr-006-positive-signal-is_native_worker-plus-lightweight-swarmadd-brief-tagging) | [Boundaries](./design.md#boundaries-and-recovery) | [Task 1](#task-1-implement-gemini-4-detection-context-budgets-native-worker-recognition-and-async-workflow-parsing) | [AC-039-2](./verification.md#ac-039-2-req-039) | PASS — Coordinator isolation and safety guards mapped |
| REQ-040 | AC-040-1 | [Rationale](./decisions.md#architectural-rationale) | [Interfaces](./design.md#interfaces-and-flow) | [Task 1](#task-1-implement-gemini-4-detection-context-budgets-native-worker-recognition-and-async-workflow-parsing) | [AC-040-1](./verification.md#ac-040-1-req-040) | PASS — async `run_workflow` vs `IsDaemon` matching mapped |
| REQ-040 | AC-040-2 | [Rationale](./decisions.md#architectural-rationale) | [Boundaries](./design.md#boundaries-and-recovery) | [Task 1](#task-1-implement-gemini-4-detection-context-budgets-native-worker-recognition-and-async-workflow-parsing) | [AC-040-2](./verification.md#ac-040-2-req-040) | PASS — subagent `run_workflow`/`swarm` denial mapped |
| REQ-041 | AC-041-1 | [Rationale](./decisions.md#architectural-rationale) | [Components](./design.md#components) | [Task 2](#task-2-sync-antigravity-20-rules-templates-skills-documentation-and-live-deployment) | [AC-041-1](./verification.md#ac-041-1-req-041) | PASS — v1.1.0 rules, docs, deployment, and CLI audits mapped |
| REQ-041 | AC-041-2 | [Rationale](./decisions.md#architectural-rationale) | [Components](./design.md#components) | [Task 2](#task-2-sync-antigravity-20-rules-templates-skills-documentation-and-live-deployment) | [AC-041-2](./verification.md#ac-041-2-req-041) | PASS — 8k budget, portability, and skill trigger checks mapped |

- Backward scope check: PASS — every modified component and task serves `REQ-038`..`REQ-041`.
- Reference and catalog consistency: PASS — all relative links, `#heading-anchors`, and `docs/specs/INDEX.md` IDs match.
