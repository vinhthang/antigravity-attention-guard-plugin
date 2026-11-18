# Decisions: Lean Attention Guard v2.0.0

Governing specification: [spec.md](./spec.md)

## Architectural rationale

- Governs: REQ-042, REQ-044, REQ-045, REQ-046

`REQ-042`, `REQ-044`, `REQ-045`, and `REQ-046` follow directly from the user's explicit `/grill-me` selections (`Q1`–`Q6`) and the `attention-metrics-server` HTTP contract (`main.go:119, 625`): narrowing `hooks.json` to `PreToolUse` on mutating/shell/delegation tools eliminates `PreInvocation`, `PostToolUse`, `Stop`, and read-tool overhead; removing `subprocess.run(verify_cmd, shell=True)` and UUID JSON schemas eliminates arbitrary hook shell execution and the `55%` JSON-formatting denial rate; and keeping `tokens` + `events` in SQLite preserves `attention-metrics-server` syncing while deleting `fsm.py` and `work_items`.

## ADR-007: `O(1)` SQLite `claimed_by` cache plus 10-line transcript header scan for `is_subagent()`

- Governs: REQ-043
- State: Accepted
- Context and constraints: In `v1.1.0`, `is_subagent()` called `parse_transcript()` across every line of `transcript.jsonl` on every `PreToolUse` subprocess (`159.3 ms` on a `2.83 MB` transcript), because in-memory `_TRANSCRIPT_CACHE` is cold across separate hook subprocesses. Meanwhile, `[ANTIGRAVITY_TOKEN:<uuid>]` injected by `inject-rules.py` is always written in the initial prompt (`step_index` `0` or `1`, within the first few lines of `transcript.jsonl`).
- Viable options:
  1. **SQLite `tokens.claimed_by` fast lookup + bounded 10-line header scan:** Store `may_delegate`, `remaining_depth`, and `parent_conv_id` directly on `tokens`. On `is_subagent()`, query `tokens WHERE claimed_by = ?` first (`< 0.5 ms`); if unclaimed, scan at most the first `10` lines of `transcript.jsonl` to extract `[ANTIGRAVITY_TOKEN:...]` (or `first_system_sender`), claim the token once in SQLite, and return immediately without reading the rest of the file.
  2. **Disk-persisted full-transcript parse cache (`~/.gemini/antigravity/cache/*.json`):** Serialize `parse_transcript()` output to JSON files keyed by `(mtime_ns, size)`.
- Decision: Option 1 (`tokens.claimed_by` SQLite lookup + bounded 10-line header scan).
- Costs and risks: Requires `ALTER TABLE tokens ADD COLUMN ...` migration when opening an existing `SCHEMA_VERSION = 2` database; mitigated by idempotent column-inspection migration in `Ledger._init_db()`.
- Rejected alternatives: Option 2 still incurs multi-megabyte full-file reads whenever `transcript.jsonl` appends a new step (which happens on *every* tool call, invalidating `(mtime_ns, size)` every single step!).
- Affected components: `scripts/ledger.py`, `scripts/common.py`, `scripts/inject-rules.py`, `scripts/enforce-delegation.py`.

## Gate 1: normative review

| Check | Status | Evidence / required correction |
| --- | --- | --- |
| Codebase grounding | PASS | Inspected all 15 scripts in `antigravity-attention-guard-plugin/scripts/`, `attention-metrics-server/backend/main.go`, and live `attention_guard.db` (`2,953` events). |
| Attributable intent and explicit scope | PASS | `REQ-042`..`REQ-046` map 1-to-1 to `/grill-me` answers `Q1`–`Q6` and approved `implementation_plan.md`; `Non-goals` exclude `attention-metrics-server` changes. |
| Observable requirements and meaningful acceptance criteria | PASS | Every requirement has falsifiable success and boundary/failure criteria (`AC-042-1`..`AC-046-2`), including `< 5 ms` in-process `O(1)` and `< 100 ms` subprocess latency bounds on a `3 MB` transcript. |
| Assumptions and owner-deferred questions are explicit | PASS | Non-destructive legacy SQLite table retention assumption documented; zero `[PROVISIONAL]` items. |
| Architectural rationale respects requirements | PASS | `ADR-007` achieves true `O(1)` `< 5 ms` subagent detection even as `transcript.jsonl` grows on every step. |
| IDs, references, and revision route are consistent | PASS | Allocates `REQ-042`..`REQ-046` and `ADR-007` above `REQ-041` / `ADR-006`, declaring `Proposed: Replaces` against `2026-11-18-antigravity-v2-gemini4-architecture`. |
