# Architecture Decision Record: Dynamic Summary Length

- **Feature ID**: `dynamic-summary-length`
- **Document**: `decisions.md` (Append-Only)
- **Status**: Accepted
- **Date**: 2026-10-11

---

## ADR-001: Removal of Rigid `maxLength` Schema Boundary in Favor of Subagent Self-Determination

### Context
In earlier iterations of Attention Guard, concerns over Attention Dilution led to capping the subagent return summary:
1. `rules/EXECUTOR.md` initially prescribed a maximum of 200 words.
2. In subsequent schema hardening, this was codified as a hard JSON schema rule: `"maxLength": 1200`, and subsequently `"maxLength": 5000`.
3. In runtime validation ([`scripts/payload_validator.py`](file:///Users/thanghoang/github/antigravity-attention-guard-plugin/scripts/payload_validator.py#L45)), any string exceeding the limit immediately caused `PAYLOAD_SCHEMA_VIOLATION`.

This rigid boundary created operational fragility:
- Legitimate multi-file changes or deep diagnostic reports were rejected on single-character overflows.
- Orchestrators were forced into Dalio error escalation loops over text length rather than code defects.
- Modern foundation models (Gemini Flash, Pro, Opus) are capable of determining appropriate summary density when given clear role guidelines.

### Decision
1. **Remove `maxLength` from all subagent schemas** (`schemas/executor-payload.json`, `schemas/diagnostician-payload.json`, `schemas/coordinator-payload.json`) (`REQ-DSL-001`).
2. **Remove the upper length check from `scripts/payload_validator.py`** (`REQ-DSL-002`).
3. **Retain `minLength: 10`** across all schemas to prevent empty or uninformative return payloads.
4. **Shift responsibility to prompt instructions** (`rules/EXECUTOR.md`) instructing subagents to calibrate depth proportional to task complexity without arbitrary character boundaries (`REQ-DSL-003`).

### Alternatives Considered

| Alternative | Rationale for Rejection |
|---|---|
| **Option A: Increase cap to 20,000 chars** | Still an arbitrary mechanical boundary that can trigger false-positive schema rejections on comprehensive architectural refactors. |
| **Option B: Automatic string truncation in validator** | Mutating payloads inside the validator breaks data immutability, invalidates cryptographic/ledger hashes, and risks corrupting diagnostic payloads mid-flight. |
| **Option C: Uncapped schema with prompt guidance (Selected)** | Eliminates false-positive schema rejections while maintaining structural contracts (`files_modified`, `test_results`, `error_details`). |

### Consequences & Trade-offs
- **Positive**:
  - Eliminates false-positive schema failures and unproductive recovery loops.
  - Allows complex tasks and root-cause diagnoses to include complete diagnostic traces.
  - Subagents naturally scale from 1 sentence on trivial bugfixes to detailed breakdowns on major migrations.
- **Negative / Mitigations**:
  - Potential risk of an undisciplined subagent dumping raw logs into the summary.
  - *Mitigation*: Prompt instructions in `rules/EXECUTOR.md` explicitly forbid dumping raw shell outputs into `summary`, pointing executors to use structured `error_details` for logs instead.
