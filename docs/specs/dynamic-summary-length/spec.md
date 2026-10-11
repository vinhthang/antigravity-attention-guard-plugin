# Feature Specification: Dynamic Subagent Summary Length

- **Feature ID**: `dynamic-summary-length`
- **Status**: `review`
- **Created**: 2026-10-11
- **Domain**: Agent Governance & Payload Schema Validation

---

## 1. Problem Statement

Attention Guard originally enforced strict summary lengths (first a 200-word limit in prompt instructions, then a 1,200-character cap, and recently a 5,000-character cap in JSON schema Draft-07 contracts and python validators). 

While intended to prevent context dilution caused by terminal log dumps, enforcing a rigid character ceiling via JSON schema validation (`maxLength`) created severe failure modes:
1. **False-Positive Failures**: When a subagent performs complex multi-file refactoring or deep root-cause diagnosis, a comprehensive summary or stack trace can legitimately exceed fixed character limits. Exceeding the boundary by even one character results in `PAYLOAD_SCHEMA_VIOLATION`, rejecting an otherwise successful run.
2. **Artificial Recovery Loops**: The orchestrator triggers Dalio error recovery loops simply to force subagents to shorten wording, wasting turns, latency, and tokens on formatting mechanics.
3. **Loss of Technical Nuance**: Forcing all tasks into the same arbitrary length window deprives the Primary Agent of essential diagnostics for intricate tasks, while being unnecessarily loose for 1-line changes.

Subagents are capable of contextually calibrating their summary depth to the scope of their assigned task.

---

## 2. Requirements & Acceptance Criteria

### REQ-DSL-001: Schema Uncapping
- **Description**: Subagent Draft-07 JSON schemas must not enforce a `maxLength` boundary on the `summary` property.
- **Scope**:
  - `schemas/executor-payload.json`
  - `schemas/diagnostician-payload.json`
  - `schemas/coordinator-payload.json`
- **Acceptance Criteria**:
  - `summary` property retains `"type": "string"` and `"minLength": 10`.
  - The `"maxLength"` key is removed from all three schema files.

### REQ-DSL-002: Built-in Validator Realignment
- **Description**: The zero-dependency payload validator in `scripts/payload_validator.py` must permit valid summaries of arbitrary length.
- **Acceptance Criteria**:
  - `validate_payload_builtin()` in `scripts/payload_validator.py` validates `len(summary) >= 10` without any upper character ceiling.
  - Payloads with arbitrarily long summaries (e.g. 10,000+ characters) evaluate to `(True, None)`.

### REQ-DSL-003: Subagent Self-Determination Guidelines
- **Description**: Rule specifications governing subagents must replace hard character bounds with guidance emphasizing task-proportional conciseness.
- **Acceptance Criteria**:
  - `rules/EXECUTOR.md` constraint section removes `between 10 and 5000 characters`.
  - Guidelines instruct subagents to calibrate depth based on task complexity (brief for minor fixes, detailed for multi-module refactors/diagnostics) while avoiding raw unstructured log dumps.

### REQ-DSL-004: Regression & Falsifiable Test Coverage
- **Description**: Automated tests must prove that summaries exceeding 5,000 characters pass cleanly, and zero regressions occur across existing test suites.
- **Acceptance Criteria**:
  - `scripts/payload_validator.py` self-tests assert that summaries > 5,000 characters pass validation.
  - `tests/test_dalio_conformance.py` includes explicit test coverage for large summaries across roles (`executor`, `diagnostician`, `coordinator`).
  - Full test suite passes (`pytest`).
