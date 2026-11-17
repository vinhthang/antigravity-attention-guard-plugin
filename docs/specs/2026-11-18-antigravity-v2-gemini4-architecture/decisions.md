# Decisions: Antigravity 2.0 orchestration, Gemini 4 detection, and native worker governance

Governing specification: [spec.md](./spec.md)

## Architectural rationale

- Governs: REQ-038, REQ-040, REQ-041

`REQ-038`, `REQ-040`, and `REQ-041` are directly constrained by Antigravity 2.0's tool schemas and existing `attention-guard` contracts: `DEFAULT_THINKING_MODELS` and `resolve_context_budget()` extend `scripts/common.py` with backward-compatible defaults (`128k` when `modelName` is absent so existing unit tests remain untouched; `1000k`/`400k` for Gemini models), `run_workflow` and `swarm` are top-level orchestration primitives that must never run inside `invoke_subagent` children (`is_sub == True`), and `rules/AGENTS.md` must stay portable and `<= 8,000` characters per `surface_validator.py`.

## ADR-006: Positive-signal `is_native_worker()` plus lightweight `swarm(add)` brief tagging

- Governs: REQ-039
- State: Accepted
- Context and constraints: Native `swarm` authors inherit the coordinator's model (`Gemini 4 Argon` / `Carbon`) per `native_swarm/SKILL.md` and run without `invoke_subagent`'s `[ANTIGRAVITY_TOKEN:...]`. Injecting full `EXECUTOR.md` rules into `swarm{action:"add"}` briefs would pollute the shared swarm message board read by every worker, while inferring worker status from the absence of `<USER_REQUEST>` tags would misclassify synthetic Primary Agent unit-test transcripts (`{"source": "USER", "type": "USER_INPUT", "content": "..."}`) as workers.
- Viable options:
  1. **Positive-signal `is_native_worker()` + compact `[AGY_SWARM_WORKER]` tag on `swarm(add)` briefs:** Append only a 18-character `[AGY_SWARM_WORKER]` marker on `swarm{action:"add"}` briefs (skipping `narrator`/`monitor`) in `inject-rules.py`, and match positive worker signals (`swarmMember`/`workflowId` payload fields, or `<swarm_worker>` / `[AGY_SWARM_WORKER]` / `[AGY_WORKFLOW_WORKER]` strictly inside `USER_INPUT`/`SYSTEM_MESSAGE` steps when the conversation has not acted as a swarm coordinator).
  2. **Force `model="flash"` overwrite on `swarm{action:"add"}`:** Mutate `swarm{action:"add"}` in `inject-rules.py` to pin `model="flash"`.
- Decision: Option 1 (positive-signal `is_native_worker()` + lightweight `[AGY_SWARM_WORKER]` brief marker).
- Costs and risks: Adds a small `[AGY_SWARM_WORKER]` suffix to author briefs on the swarm board; mitigated by ignoring `GENERIC` (`read_board`) and `PLANNER_RESPONSE` steps in `is_native_worker()` so the Coordinator never matches its own tag.
- Rejected alternatives: Option 2 directly violates Antigravity 2.0's `native_swarm` contract ("Run every worker on your own model — the one the user chose for this conversation — by leaving `model` off `add`. Do not pick other models on your own initiative").
- Affected components: `hooks.json`, `scripts/inject-rules.py`, `scripts/common.py::is_native_worker`, `scripts/enforce-delegation.py::main`, `scripts/attention-refresh.py::main`.

## Gate 1: normative review

| Check | Status | Evidence / required correction |
| --- | --- | --- |
| Codebase grounding | PASS | Inspected `scripts/{common,enforce-delegation,inject-rules,attention-refresh,deploy_plugin}.py`, `hooks.json`, `rules/AGENTS.md`, `templates/*.md`, and live `transcript.jsonl`. |
| Attributable intent and explicit scope | PASS | `REQ-038`..`REQ-041` trace to user's Antigravity 2.0 + Gemini 4 upgrade request and approved `implementation_plan.md`; `Non-goals` exclude `attention-metrics-server` UI and swarm `work_items` gating. |
| Observable requirements and meaningful acceptance criteria | PASS | Every requirement has deterministic success and boundary/failure ACs (`AC-038-1`..`AC-041-2`). |
| Assumptions and owner-deferred questions are explicit | PASS | Unset `modelName` backward-compatibility assumption recorded; zero unresolved questions or `[PROVISIONAL]` items. |
| Architectural rationale respects requirements | PASS | `ADR-006` preserves `native_swarm`'s model-inheritance contract while preventing Gemini 4 worker deadlocks and Coordinator false positives. |
| IDs, references, and revision route are consistent | PASS | Allocates `REQ-038`..`REQ-041` and `ADR-006` above prior highest `REQ-037` / `ADR-005` in `docs/specs/INDEX.md`. |
