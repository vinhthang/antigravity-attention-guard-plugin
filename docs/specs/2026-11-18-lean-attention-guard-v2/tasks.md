# Tasks: Lean Attention Guard v2.0.0

Sources: [spec.md](./spec.md), [design.md](./design.md)

## Task 1: Author Lean v2 governance rules, subagent templates, and documentation

- [x] Complete the work and its applicable checks.
- Covers: REQ-046 / AC-046-1, AC-046-2
- Files: `rules/AGENTS.md`, `templates/EXECUTOR.md`, `templates/COORDINATOR.md`, `README.md`
- Dependencies: None
- Blocked by: None
- Work: Rewrite `rules/AGENTS.md` (`<= 4,000` chars, advisory delegation, explicit plan approval, zero error suppression, skill triggers `attention-metrics` and `git-worktree-sandbox`, zero `schedule(300s)` or `payload_validator.py` ceremony), simplify `templates/{EXECUTOR,COORDINATOR}.md`, and update `README.md` for `v2.0.0`.
- Completion evidence: Completed in [Run 1](./verification.md#run-1--2026-11-18) (`rules/AGENTS.md` reduced from `7,344` to `3,362` chars; `surface_validator.py` and `agy plugin validate` pass).

## Task 2: Implement Lean v2 hooks, O(1) subagent detection, slim SQLite v3 ledger, deployment pruning, and test suite

- [x] Complete the work and its applicable checks.
- Covers: REQ-042 / AC-042-1, AC-042-2; REQ-043 / AC-043-1, AC-043-2; REQ-044 / AC-044-1, AC-044-2; REQ-045 / AC-045-1, AC-045-2; REQ-046 / AC-046-1, AC-046-2
- Files: `hooks.json`, `plugin.json`, `scripts/ledger.py`, `scripts/common.py`, `scripts/enforce-delegation.py`, `scripts/inject-rules.py`, `scripts/diagnostics.py`, `scripts/system_audit.py`, `scripts/deploy_plugin.py`, `tests/test_lean_v2_architecture.py`
- Dependencies: Task 1
- Blocked by: None
- Work: Delete retired `scripts/{attention-check,attention-refresh,record-tool-result,fsm,payload_validator}.py`, `schemas/`, and obsolete `v1.x` test modules; write failing `tests/test_lean_v2_architecture.py` (including `< 5 ms` in-process / `< 100 ms` subprocess `3 MB` transcript benchmark and SQLite v2->v3 migration test); update `hooks.json`, `plugin.json` (`"2.0.0"`), `ledger.py`, `common.py`, `enforce-delegation.py`, `inject-rules.py`, `diagnostics.py`, `system_audit.py`, `deploy_plugin.py`, and remaining test modules; verify `pytest tests/`, `mutation_runner.py` (`>= 80%`), `deploy_plugin.py --deploy`, `surface_validator.py`, `agy plugin validate`, and `prepare_code_review.py`.
- Completion evidence: Completed in [Run 1](./verification.md#run-1--2026-11-18) (`117/117` tests passing, `95%`–`100%` mutation kill rates, `40.2 ms` cached subprocess median on `3.11 MB` transcript, zero `P0`/`P1` code-review defects, `v2.0.0` deployed live).

## Gate 2: traceability and readiness

| Requirement | AC | ADR or rationale | Design | Task | Planned verification | Status / reason |
| --- | --- | --- | --- | --- | --- | --- |
| REQ-042 | AC-042-1 | [Rationale](./decisions.md#architectural-rationale) | [Components](./design.md#components) | [Task 2](#task-2-implement-lean-v2-hooks-o1-subagent-detection-slim-sqlite-v3-ledger-deployment-pruning-and-test-suite) | [AC-042-1](./verification.md#ac-042-1-req-042) | PASS — PreToolUse-only hooks, deleted scripts, and Primary allow mapped |
| REQ-042 | AC-042-2 | [Rationale](./decisions.md#architectural-rationale) | [Interfaces](./design.md#interfaces-and-flow) | [Task 2](#task-2-implement-lean-v2-hooks-o1-subagent-detection-slim-sqlite-v3-ledger-deployment-pruning-and-test-suite) | [AC-042-2](./verification.md#ac-042-2-req-042) | PASS — destructive command, test-tamper, and denial telemetry mapped |
| REQ-043 | AC-043-1 | [ADR-007](./decisions.md#adr-007-o1-sqlite-claimed_by-cache-plus-10-line-transcript-header-scan-for-is_subagent) | [Interfaces](./design.md#interfaces-and-flow) | [Task 2](#task-2-implement-lean-v2-hooks-o1-subagent-detection-slim-sqlite-v3-ledger-deployment-pruning-and-test-suite) | [AC-043-1](./verification.md#ac-043-1-req-043) | PASS — Model preservation and `< 5 ms` O(1) / `< 100 ms` subprocess 3MB benchmark mapped |
| REQ-043 | AC-043-2 | [ADR-007](./decisions.md#adr-007-o1-sqlite-claimed_by-cache-plus-10-line-transcript-header-scan-for-is_subagent) | [Interfaces](./design.md#interfaces-and-flow) | [Task 2](#task-2-implement-lean-v2-hooks-o1-subagent-detection-slim-sqlite-v3-ledger-deployment-pruning-and-test-suite) | [AC-043-2](./verification.md#ac-043-2-req-043) | PASS — Primary parent_conv_id self-claim guard mapped |
| REQ-044 | AC-044-1 | [Rationale](./decisions.md#architectural-rationale) | [Interfaces](./design.md#interfaces-and-flow) | [Task 2](#task-2-implement-lean-v2-hooks-o1-subagent-detection-slim-sqlite-v3-ledger-deployment-pruning-and-test-suite) | [AC-044-1](./verification.md#ac-044-1-req-044) | PASS — Markdown/JSON send_message and Coordinator depth=1 mapped |
| REQ-044 | AC-044-2 | [Rationale](./decisions.md#architectural-rationale) | [Interfaces](./design.md#interfaces-and-flow) | [Task 2](#task-2-implement-lean-v2-hooks-o1-subagent-detection-slim-sqlite-v3-ledger-deployment-pruning-and-test-suite) | [AC-044-2](./verification.md#ac-044-2-req-044) | PASS — recursion, doom-loop, bg-task, and raw-log blocks mapped |
| REQ-045 | AC-045-1 | [Rationale](./decisions.md#architectural-rationale) | [Boundaries](./design.md#boundaries-and-recovery) | [Task 2](#task-2-implement-lean-v2-hooks-o1-subagent-detection-slim-sqlite-v3-ledger-deployment-pruning-and-test-suite) | [AC-045-1](./verification.md#ac-045-1-req-045) | PASS — SQLite v2->v3 migration, diagnostics, and sync_metrics mapped |
| REQ-045 | AC-045-2 | [Rationale](./decisions.md#architectural-rationale) | [Boundaries](./design.md#boundaries-and-recovery) | [Task 2](#task-2-implement-lean-v2-hooks-o1-subagent-detection-slim-sqlite-v3-ledger-deployment-pruning-and-test-suite) | [AC-045-2](./verification.md#ac-045-2-req-045) | PASS — missing DB clean exit mapped |
| REQ-046 | AC-046-1 | [Rationale](./decisions.md#architectural-rationale) | [Components](./design.md#components) | [Task 1](#task-1-author-lean-v2-governance-rules-subagent-templates-and-documentation), [Task 2](#task-2-implement-lean-v2-hooks-o1-subagent-detection-slim-sqlite-v3-ledger-deployment-pruning-and-test-suite) | [AC-046-1](./verification.md#ac-046-1-req-046) | PASS — lean AGENTS.md, deploy pruning, and CLI validators mapped |
| REQ-046 | AC-046-2 | [Rationale](./decisions.md#architectural-rationale) | [Boundaries](./design.md#boundaries-and-recovery) | [Task 1](#task-1-author-lean-v2-governance-rules-subagent-templates-and-documentation), [Task 2](#task-2-implement-lean-v2-hooks-o1-subagent-detection-slim-sqlite-v3-ledger-deployment-pruning-and-test-suite) | [AC-046-2](./verification.md#ac-046-2-req-046) | PASS — pre-flight surface validation failure guard mapped |

- Backward scope check: PASS — every component, deletion, and task serves `REQ-042`..`REQ-046`.
- Reference and catalog consistency: PASS — all relative links, `#heading-anchors`, and `docs/specs/INDEX.md` entries match.
