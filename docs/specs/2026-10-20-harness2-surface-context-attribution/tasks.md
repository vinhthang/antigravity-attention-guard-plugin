# Execution Checklist: Harness² Surface Validation, Context Boundary & Causal Attribution

- **Feature ID**: `2026-10-20-harness2-surface-context-attribution`
- **Spec**: [spec.md](spec.md)
- **Design**: [design.md](design.md)

---

## Step 1: Surface & Budget Validator (`REQ-001`, `REQ-002`, `REQ-004`)

- [x] **Task 1.1 (`REQ-001`)**: Create `scripts/surface_validator.py` implementing `PluginSurfaceSpec`, `read_plugin_tree()`, `autotrigger()`, `check_hooks()`, `validate_plugin_surface()`, `diff_summary()`, and a CLI entrypoint (`--plugin-dir`, `--always-on-max`, `--autotrigger`, `--json`).
  - **Produces**: `scripts/surface_validator.py`
  - **Verification**: `rtk python3 scripts/surface_validator.py --plugin-dir . --json`
- [x] **Task 1.2 (`REQ-001`, `REQ-002`)**: Integrate `validate_plugin_surface()` into `scripts/deploy_plugin.py::verify_source_bundle()`.
  - **Consumes**: `scripts/surface_validator.py`
  - **Produces**: Updated `scripts/deploy_plugin.py`
  - **Verification**: `rtk python3 scripts/deploy_plugin.py --verify-only`
- [x] **Task 1.3 (`REQ-002`, `REQ-004`)**: Update `rules/AGENTS.md` in `attention-guard` to add the explicit `attention-metrics` skill trigger and the Subagent Input/Output Shape constraint (`large input -> small structured JSON output`), keeping `rules/AGENTS.md <= 8000` characters. Also slim `agent-translator/rules/AGENTS.md` to add explicit skill triggers (`translate`, `translate-book`, `translate-zh-book`, `summarize-book`, `en-vi-book-translation-review`) and reduce global always-on character overhead.
  - **Produces**: Updated `rules/AGENTS.md` (and `agent-translator/rules/AGENTS.md`)
  - **Verification**: `rtk python3 scripts/surface_validator.py --plugin-dir .`

---

## Step 2: Pointer-Based Context, Causal Attribution & Budget Identity (`REQ-003`, `REQ-005`, `REQ-006`)

- [x] **Task 2.1 (`REQ-003`)**: Create `scripts/context_boundary.py` implementing `EVIDENCE_BOUNDARY`, `GRADER_VERDICT_MARKERS`, `assert_no_grader_verdicts()`, and `materialize_context_pointer()`, and wire it into `scripts/inject-rules.py`.
  - **Produces**: `scripts/context_boundary.py`, updated `scripts/inject-rules.py`
  - **Verification**: `rtk pytest tests/test_harness2_improvements.py -k "context_boundary or inject_rules"`
- [x] **Task 2.2 (`REQ-005`)**: Extend `schemas/diagnostician-payload.json` and `scripts/payload_validator.py` with `edit_attributions` (`helped | hurt | no_observed_effect | confounded`), `transferable_lesson` (`cue`, `lesson`, `evidence`, `confidence`), and the Confounding Guard (`validate_causal_attribution()`).
  - **Produces**: Updated `schemas/diagnostician-payload.json`, updated `scripts/payload_validator.py`
  - **Verification**: `rtk python3 scripts/payload_validator.py --test`
- [x] **Task 2.3 (`REQ-006`)**: Add `audit_conversation_budget()` to `scripts/ledger.py` and surface `duplicate_tokens` and `budget_ok` in `scripts/diagnostics.py`.
  - **Produces**: Updated `scripts/ledger.py`, updated `scripts/diagnostics.py`
  - **Verification**: `rtk pytest tests/test_harness2_improvements.py -k "ledger or diagnostics"`
- [x] **Task 2.4 (`REQ-001`..`REQ-006`)**: Author comprehensive TDD test suite in `tests/test_harness2_improvements.py` and `tests/test_surface_validator.py` covering `REQ-001` through `REQ-006` and record verbatim test evidence in `docs/specs/2026-10-20-harness2-surface-context-attribution/verification.md`.
  - **Produces**: `tests/test_harness2_improvements.py`, `tests/test_surface_validator.py`, `docs/specs/2026-10-20-harness2-surface-context-attribution/verification.md`
  - **Verification**: `rtk pytest -v`
