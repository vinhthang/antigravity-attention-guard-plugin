# Architecture Design Blueprint: Dynamic Summary Length

- **Feature ID**: `dynamic-summary-length`
- **Document**: `design.md`
- **Status**: Draft / Review
- **Date**: 2026-10-11

---

## 1. Component Architecture & Data Flow

```
┌────────────────────────────────────────────────────────┐
│                   Subagent Execution                   │
│  - Calibrates summary depth to task complexity         │
│  - Concise for 1-liners; detailed for deep refactors  │
└───────────────────────────┬────────────────────────────┘
                            │ Returns JSON Payload
                            ▼
┌────────────────────────────────────────────────────────┐
│             Payload Validator Pipeline                 │
│  scripts/payload_validator.py                          │
│                                                        │
│  1. Structural Schema Validation (Draft7Validator)     │
│     - Validates required fields, types, UUID format    │
│     - Validates minLength: 10                          │
│     - (Uncapped: no maxLength constraint)              │
│                                                        │
│  2. Built-in Fallback Validator                        │
│     - isinstance(summary, str) and len(summary) >= 10  │
└───────────────────────────┬────────────────────────────┘
                            │ Valid
                            ▼
┌────────────────────────────────────────────────────────┐
│           Orchestrator Context Window                  │
│  - Receives high-density, appropriately sized summary  │
│  - Zero false-positive schema recovery loops           │
└────────────────────────────────────────────────────────┘
```

---

## 2. Detailed Technical Changes

### Component 1: Draft-07 JSON Schema Updates (Addresses: `REQ-DSL-001`)
- **`schemas/executor-payload.json`**:
  ```diff
  "summary": {
    "type": "string",
  - "minLength": 10,
  - "maxLength": 5000
  + "minLength": 10
  }
  ```
- **`schemas/diagnostician-payload.json`**:
  ```diff
  "summary": {
    "type": "string",
  - "minLength": 10,
  - "maxLength": 5000
  + "minLength": 10
  }
  ```
- **`schemas/coordinator-payload.json`**:
  ```diff
  "summary": {
    "type": "string",
  - "minLength": 10,
  - "maxLength": 5000
  + "minLength": 10
  }
  ```

### Component 2: Validator Implementation (Addresses: `REQ-DSL-002`)
- **`scripts/payload_validator.py`**:
  Modify `validate_payload_builtin()`:
  ```python
  summary = payload["summary"]
  if not isinstance(summary, str) or len(summary) < 10:
      return False, "Invalid summary: must be string of at least 10 characters"
  ```
- Modify self-test suite `run_tests()`:
  - Remove assertion expecting rejection of 5,001-character string.
  - Add positive assertion proving a 10,000-character summary passes validation.

### Component 3: Subagent Rule Alignment (Addresses: `REQ-DSL-003`)
- **`rules/EXECUTOR.md`**:
  Update Summary Length constraint:
  - From: `- **Summary Length**: The summary field MUST be concise, between 10 and 5000 characters.`
  - To: `- **Summary Length**: Calibrate summary depth to task scope. Keep brief for simple edits; provide detailed breakdowns for multi-file refactors or test diagnoses. Do not dump raw shell logs into summary; use structured error_details.`

### Component 4: Test Suite Hardening (Addresses: `REQ-DSL-004`)
- **`tests/test_dalio_conformance.py`**:
  - Add unit test `test_large_summary_accepted()` verifying that payloads with large summaries (> 5,000 chars) are recognized as valid across `executor`, `diagnostician`, and `coordinator`.
