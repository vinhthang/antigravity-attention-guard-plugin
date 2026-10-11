# Execution Checklist: Dynamic Summary Length

- **Feature ID**: `dynamic-summary-length`
- **Document**: `tasks.md`
- **Status**: Implemented & Verified

---

## Tasks

- [x] **Task 1: Remove `maxLength` from Subagent JSON Schemas** (`REQ-DSL-001`)
  - [x] Remove `maxLength: 5000` from [`schemas/executor-payload.json`](file:///Users/thanghoang/github/antigravity-attention-guard-plugin/schemas/executor-payload.json)
  - [x] Remove `maxLength: 5000` from [`schemas/diagnostician-payload.json`](file:///Users/thanghoang/github/antigravity-attention-guard-plugin/schemas/diagnostician-payload.json)
  - [x] Remove `maxLength: 5000` from [`schemas/coordinator-payload.json`](file:///Users/thanghoang/github/antigravity-attention-guard-plugin/schemas/coordinator-payload.json)

- [x] **Task 2: Update Payload Validator Logic and Self-Tests** (`REQ-DSL-002`, `REQ-DSL-004`)
  - [x] Update `validate_payload_builtin` in [`scripts/payload_validator.py`](file:///Users/thanghoang/github/antigravity-attention-guard-plugin/scripts/payload_validator.py) to check `len(summary) >= 10` without upper cap
  - [x] Update self-tests in [`scripts/payload_validator.py`](file:///Users/thanghoang/github/antigravity-attention-guard-plugin/scripts/payload_validator.py) to assert large summaries (e.g. 10,000 characters) pass

- [x] **Task 3: Refine Subagent Governance Rule** (`REQ-DSL-003`)
  - [x] Update summary constraint in [`rules/EXECUTOR.md`](file:///Users/thanghoang/github/antigravity-attention-guard-plugin/rules/EXECUTOR.md) to instruct task-proportional calibration without character ceiling

- [x] **Task 4: Add Regression Tests & Verify Full Suite** (`REQ-DSL-004`)
  - [x] Add tests in [`tests/test_dalio_conformance.py`](file:///Users/thanghoang/github/antigravity-attention-guard-plugin/tests/test_dalio_conformance.py) validating >5,000 character summaries
  - [x] Run full test suite (`rtk pytest`) and document verbatim evidence in `docs/specs/dynamic-summary-length/verification.md`
