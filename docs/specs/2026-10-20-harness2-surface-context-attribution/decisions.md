# Architecture Decision Records: Harness² Surface Validation, Context Boundary & Causal Attribution

- **Feature ID**: `2026-10-20-harness2-surface-context-attribution`
- **Date**: `2026-10-20`

---

## `ADR-001`: Port `harness2/core/tree.py` Surface Validation into `scripts/surface_validator.py`
- **Status**: Proposed
- **Addresses**: `REQ-001`, `REQ-002`
- **Context**:
  `scripts/deploy_plugin.py` previously checked only whether bundle directories were non-empty and `.json` files parsed. As a result, `skills/attention-metrics/SKILL.md` had no trigger reference in `rules/AGENTS.md` (making it dead weight per `harness2/core/tree.py:296-301`), and always-on rules had no character cap enforcement.
- **Decision**:
  Implement `scripts/surface_validator.py` modeled on `google-research/harness2/harness2/core/tree.py` (`SurfaceSpec`, `validate()`, `autotrigger()`, `check_hooks()`, `_check_skills()`, `_check_script_refs()`, `_py_compiles()`, `diff_summary()`), and invoke it inside `scripts/deploy_plugin.py::verify_source_bundle()`. Cap primary plugin always-on `rules/AGENTS.md` at `8,000` characters (matching `CODEX_SURFACE.always_on_max = 8_000` in `harness2/substrate/codex.py:42`).
- **Consequences**:
  Every plugin deployment or `--verify-only` check mechanically prevents untriggered skills, broken script references, syntax errors, invalid `hooks.json` schemas, and always-on rule bloat.

---

## `ADR-002`: Pointer-Based Context Offloading and `EVIDENCE_BOUNDARY` Injection in `scripts/inject-rules.py`
- **Status**: Proposed
- **Addresses**: `REQ-003`, `REQ-004`
- **Context**:
  In `google-research/harness2/harness2/core/context.py` (`mission()`, lines 953–978) and `prompts.py` (`EVIDENCE_BOUNDARY`, lines 786–793), large task materials and trajectories are written to `context/` on disk while the model receives a compact mission pointer and an explicit instruction-injection boundary stating that inspected files are passive data, not instructions. In `attention-guard`, `scripts/inject-rules.py` previously concatenated all prompt content inline without an evidence boundary or disk offloading.
- **Decision**:
  Create `scripts/context_boundary.py` providing `EVIDENCE_BOUNDARY`, `assert_no_grader_verdicts()`, and `materialize_context_pointer()`. When `sa["Prompt"]` exceeds `AGY_CONTEXT_POINTER_THRESHOLD` (default `12,000` chars), `inject-rules.py` writes the original prompt body to `~/.gemini/antigravity/context/<token>/task.md` and replaces the inline prompt with a compact pointer mission plus the injected role contract and `EVIDENCE_BOUNDARY`.
- **Consequences**:
  Protects subagent context windows from inline prompt dumps, hardens subagents against indirect prompt injection inside inspected repositories/logs, and remains backward-compatible for normal (<12,000 char) prompts.

---

## `ADR-003`: Causal Edit Attribution & Confounding Filter in `schemas/diagnostician-payload.json`
- **Status**: Proposed
- **Addresses**: `REQ-005`, `REQ-006`
- **Context**:
  In `google-research/harness2/harness2/core/prompts.py` (`experience()`, lines 694–740) and `library.py` (`has_experience()`, lines 531–535), every modified component in a candidate run is evaluated with a strict causal verdict (`helped | hurt | no_observed_effect | confounded`), and any transferable lesson resting exclusively on `confounded` edits (where multiple components changed simultaneously without isolation) is rejected.
- **Decision**:
  Extend `schemas/diagnostician-payload.json` (`diagnosis` object) with optional `edit_attributions` and `transferable_lesson` fields, and enforce in `scripts/payload_validator.py` that a `transferable_lesson` is rejected whenever `edit_attributions` has no isolated `"helped"` or `"hurt"` verdict. Simultaneously add `audit_conversation_budget()` to `scripts/ledger.py` (modeled on `harness2/core/ledger.py::assert_identity()`) to detect duplicate `WORK_PREPARED` worker tokens in `scripts/diagnostics.py`.
- **Consequences**:
  Prevents confounded multi-file trial-and-error edits from polluting retry plans or OpenViking memory while keeping existing diagnostician payloads 100% backward-compatible.
